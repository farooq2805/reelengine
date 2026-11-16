"""Autonomous agent system: each agent runs on a schedule, makes its own decisions."""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import DATA, REELS, REPORTS, SCRIPTS, list_niches, load_niche, reel_dir

AGENT_DEFS = {
    "scout": {
        "name": "Scout",
        "role": "Finds new reels from hashtags and creators",
        "icon": "radar",
        "color": "#ff5a36",
        "interval": 3600,  # 1 hour
    },
    "analyst": {
        "name": "Analyst",
        "role": "Downloads and analyzes top-performing reels",
        "icon": "analytics",
        "color": "#51df9c",
        "interval": 1800,  # 30 min
    },
    "decoder": {
        "name": "Decoder",
        "role": "Generates style cards from analyzed reels",
        "icon": "style",
        "color": "#ebc300",
        "interval": 1800,
    },
    "reporter": {
        "name": "Reporter",
        "role": "Writes performance reports and trend summaries",
        "icon": "summarize",
        "color": "#7c6bff",
        "interval": 7200,  # 2 hours
    },
}

AGENT_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT NOT NULL,
    niche      TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status     TEXT DEFAULT 'running',  -- running | completed | failed
    summary    TEXT,
    details    TEXT,                     -- JSON
    items      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_agent_runs ON agent_runs(agent, started_at);
"""


def _ensure_schema():
    with db.connect() as con:
        con.executescript(AGENT_RUNS_SCHEMA)


def _log_run(agent: str, niche: str) -> int:
    _ensure_schema()
    with db.connect() as con:
        cur = con.execute(
            "INSERT INTO agent_runs (agent, niche, started_at, status) VALUES (?,?,?,?)",
            (agent, niche, db.now(), "running"),
        )
        return cur.lastrowid


def _finish_run(run_id: int, status: str, summary: str, details: dict | None = None, items: int = 0):
    with db.connect() as con:
        con.execute(
            "UPDATE agent_runs SET finished_at=?, status=?, summary=?, details=?, items=? WHERE id=?",
            (db.now(), status, summary, json.dumps(details or {}), items, run_id),
        )


def get_agent_status() -> list[dict]:
    """Get the current status of all agents."""
    _ensure_schema()
    out = []
    with db.connect() as con:
        for key, defn in AGENT_DEFS.items():
            last = con.execute(
                "SELECT * FROM agent_runs WHERE agent=? ORDER BY started_at DESC LIMIT 1", (key,)
            ).fetchone()
            total_runs = con.execute(
                "SELECT COUNT(*) FROM agent_runs WHERE agent=?", (key,)
            ).fetchone()[0]
            total_items = con.execute(
                "SELECT COALESCE(SUM(items), 0) FROM agent_runs WHERE agent=? AND status='completed'", (key,)
            ).fetchone()[0]

            info = {
                **defn,
                "key": key,
                "total_runs": total_runs,
                "total_items": total_items,
                "last_run": dict(last) if last else None,
                "running": _runner is not None and _runner.is_alive() and key in _active_agents,
            }
            out.append(info)
    return out


def get_agent_logs(agent: str, limit: int = 20) -> list[dict]:
    _ensure_schema()
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM agent_runs WHERE agent=? ORDER BY started_at DESC LIMIT ?",
            (agent, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Autonomous decision-making per agent ──────────────────────────

def _decide_scout(niche: str) -> dict:
    """Scout decides what to do based on current state."""
    recipe = load_niche(niche)
    has_session = False
    try:
        from .scrape import _session_file
        has_session = _session_file().exists()
    except Exception:
        pass

    harvest_files = list(DATA.glob(f"harvest-{niche}*.txt"))
    return {
        "has_session": has_session,
        "harvest_files": [str(f) for f in harvest_files],
        "hashtag_count": len(recipe.get("hashtags", [])),
        "creator_count": len(recipe.get("creators", [])),
    }


def _decide_analyst(niche: str) -> dict:
    """Analyst figures out what needs analyzing."""
    from .analyze import queue
    codes = queue(niche, window_days=7, top=20)
    with db.connect() as con:
        total = con.execute("SELECT COUNT(*) FROM reels WHERE niche=?", (niche,)).fetchone()[0]
        analyzed = con.execute(
            "SELECT COUNT(*) FROM reels WHERE niche=? AND status='analyzed'", (niche,)
        ).fetchone()[0]
    return {"queue": codes, "total": total, "analyzed": analyzed, "pending": len(codes)}


def _decide_decoder(niche: str) -> dict:
    """Decoder finds analyzed reels without style cards."""
    from .score import leaderboard
    rows = leaderboard(niche, window_days=0, sort="outlier", limit=200)
    need = []
    for r in rows:
        d = reel_dir(r["shortcode"])
        if (d / "analysis.json").exists() and not (d / "stylecard.json").exists():
            need.append(r["shortcode"])
    return {"need": need, "count": len(need)}


def _decide_reporter(niche: str) -> dict:
    """Reporter checks if a fresh report is needed."""
    rdir = DATA / "reports"
    today = datetime.now().strftime("%Y-%m-%d")
    has_today = any(
        f.name.startswith(today) and niche in f.name
        for f in rdir.glob("*.md")
    ) if rdir.exists() else False
    return {"has_today_report": has_today, "date": today}


# ── Agent execution ───────────────────────────────────────────────

def run_agent(agent: str, niche: str) -> dict:
    """Run a single agent autonomously for a niche."""
    run_id = _log_run(agent, niche)
    try:
        if agent == "scout":
            result = _exec_scout(niche)
        elif agent == "analyst":
            result = _exec_analyst(niche)
        elif agent == "decoder":
            result = _exec_decoder(niche)
        elif agent == "reporter":
            result = _exec_reporter(niche)
        else:
            raise ValueError(f"Unknown agent: {agent}")

        _finish_run(run_id, "completed", result["summary"], result.get("details"), result.get("items", 0))
        return result
    except Exception as e:
        _finish_run(run_id, "failed", f"Error: {e}", {"traceback": traceback.format_exc()})
        return {"summary": f"Failed: {e}", "items": 0}


def _exec_scout(niche: str) -> dict:
    ctx = _decide_scout(niche)
    items = 0
    parts = []

    if ctx["has_session"]:
        try:
            from .scrape import scrape
            s = scrape(niche, hashtags=True, creators=True)
            items += s["new"]
            parts.append(f"{s['new']} new reels scraped")
        except Exception as e:
            parts.append(f"Scrape failed: {e}")

    for hf in ctx["harvest_files"]:
        try:
            from .harvest import harvest
            h = harvest(hf, niche)
            n = h.get("imported", 0) if isinstance(h, dict) else 0
            items += n
            parts.append(f"{n} harvested from {Path(hf).name}")
        except Exception as e:
            parts.append(f"Harvest {Path(hf).name} failed: {e}")

    try:
        from .scrape import discover
        added = discover(niche, max_new=15)
        if added:
            parts.append(f"Discovered {len(added)} creators")
    except Exception:
        pass

    summary = "; ".join(parts) if parts else "No data sources available"
    return {"summary": summary, "items": items, "details": ctx}


def _exec_analyst(niche: str) -> dict:
    from .analyze import analyze, queue
    ctx = _decide_analyst(niche)

    if not ctx["queue"]:
        return {"summary": "Nothing to analyze — all top reels done", "items": 0}

    batch = ctx["queue"][:10]
    done = 0
    for sc in batch:
        try:
            analyze(sc, use_vision=True, max_frames=10)
            done += 1
        except Exception:
            pass

    return {
        "summary": f"Analyzed {done}/{len(batch)} reels ({ctx['analyzed']+done}/{ctx['total']} total)",
        "items": done,
        "details": {"codes": batch[:done]},
    }


def _exec_decoder(niche: str) -> dict:
    from .autopilot import _generate_stylecard
    ctx = _decide_decoder(niche)

    if not ctx["need"]:
        return {"summary": "All analyzed reels have style cards", "items": 0}

    batch = ctx["need"][:10]
    done = 0
    for sc in batch:
        try:
            _generate_stylecard(sc)
            done += 1
        except Exception:
            pass

    return {
        "summary": f"Created {done} style cards",
        "items": done,
        "details": {"codes": batch[:done]},
    }


def _exec_reporter(niche: str) -> dict:
    ctx = _decide_reporter(niche)
    if ctx["has_today_report"]:
        return {"summary": "Today's report already exists", "items": 0}

    from .autopilot import run_reporter
    result = run_reporter(niche, window=7)
    return {"summary": f"Wrote report: {result['file']}", "items": 1, "details": result}


# ── Background scheduler ─────────────────────────────────────────

_runner: threading.Thread | None = None
_stop_event = threading.Event()
_active_agents: set[str] = set()
_live_log: list[dict] = []
MAX_LOG = 200


def _push_log(agent: str, msg: str, level: str = "info"):
    _live_log.append({
        "agent": agent,
        "msg": msg,
        "level": level,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    if len(_live_log) > MAX_LOG:
        _live_log.pop(0)


def get_live_log(limit: int = 50) -> list[dict]:
    return _live_log[-limit:]


def _scheduler_loop():
    _push_log("system", "Agent scheduler started")
    last_run: dict[str, float] = {}

    while not _stop_event.is_set():
        niches = list_niches()
        for agent_key, defn in AGENT_DEFS.items():
            if _stop_event.is_set():
                break

            run_key = agent_key
            elapsed = time.time() - last_run.get(run_key, 0)
            if elapsed < defn["interval"]:
                continue

            for niche in niches:
                if _stop_event.is_set():
                    break
                _active_agents.add(agent_key)
                _push_log(agent_key, f"Running for {niche}...")
                try:
                    result = run_agent(agent_key, niche)
                    _push_log(agent_key, result["summary"])
                except Exception as e:
                    _push_log(agent_key, f"Error: {e}", "error")
                finally:
                    _active_agents.discard(agent_key)

            last_run[run_key] = time.time()

        _stop_event.wait(30)

    _push_log("system", "Agent scheduler stopped")


def start_scheduler():
    global _runner
    if _runner and _runner.is_alive():
        return {"status": "already_running"}
    _stop_event.clear()
    _runner = threading.Thread(target=_scheduler_loop, daemon=True, name="agent-scheduler")
    _runner.start()
    return {"status": "started"}


def stop_scheduler():
    global _runner
    if not _runner or not _runner.is_alive():
        return {"status": "not_running"}
    _stop_event.set()
    _runner.join(timeout=5)
    _runner = None
    return {"status": "stopped"}


def scheduler_status() -> dict:
    return {
        "running": _runner is not None and _runner.is_alive(),
        "active_agents": list(_active_agents),
    }
