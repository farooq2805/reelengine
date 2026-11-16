"""Local dashboard API. Run with `engine serve`, open http://localhost:8765."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .config import CARDS, DATA, REELS, REPORTS, ROOT, SCRIPTS, list_niches, load_niche
from .score import leaderboard

app = FastAPI(title="Reel Engine")
DASH = ROOT / "dashboard"


def _read(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else p.read_text(encoding="utf-8")


@app.get("/api/niches")
def niches():
    out = []
    for slug in list_niches():
        n = load_niche(slug)
        out.append({"slug": slug, "name": n.get("name", slug), "self": n.get("self_username") or ""})
    return out


@app.get("/api/stats")
def stats(niche: str | None = None):
    with db.connect() as con:
        w, a = ("WHERE niche=?", (niche,)) if niche else ("", ())
        r = con.execute(f"""SELECT COUNT(*) total, SUM(saved) saved, SUM(status='analyzed') analyzed,
                            COUNT(DISTINCT owner) creators, MAX(last_seen) last_scan FROM reels {w}""", a).fetchone()
        return dict(r)


@app.get("/api/reels")
def reels(niche: str | None = None, window: int = 7, sort: str = "outlier", limit: int = 60, offset: int = 0,
          saved: int | None = None, q: str | None = None, owner: str | None = None, mine: int = 0):
    rows = leaderboard(niche, window_days=window, sort=sort, limit=2000 if (q or mine) else limit + offset,
                       saved=None if saved is None else bool(saved), owner=owner)
    if mine:
        rows = [r for r in rows if r["is_self"]]
    else:
        rows = [r for r in rows if not r["is_self"]]
    if q:  # search captions, transcripts and breakdowns too
        ql = q.lower()
        keep = []
        for r in rows:
            hay = " ".join(str(r.get(k) or "") for k in ("caption", "owner", "tags", "board")).lower()
            an = REELS / r["shortcode"] / "analysis.json"
            bd = REELS / r["shortcode"] / "breakdown.md"
            if an.exists():
                hay += " " + (json.loads(an.read_text(encoding="utf-8"))["transcript"]["text"] or "").lower()
            if bd.exists():
                hay += " " + bd.read_text(encoding="utf-8").lower()
            if all(word in hay for word in ql.split()):
                keep.append(r)
        rows = keep
    return rows[offset: offset + limit]


@app.get("/api/reels/{sc}")
def reel(sc: str):
    with db.connect() as con:
        r = con.execute("SELECT * FROM reels WHERE shortcode=?", (sc,)).fetchone()
        if not r:
            raise HTTPException(404)
        snaps = [dict(x) for x in con.execute(
            "SELECT ts, COALESCE(plays, views) views, likes, comments FROM snapshots WHERE shortcode=? ORDER BY ts", (sc,))]
    row = next((x for x in leaderboard(r["niche"], window_days=0, limit=100000) if x["shortcode"] == sc), dict(r))
    d = REELS / sc
    return {**row, "snapshots": snaps, "analysis": _read(d / "analysis.json"),
            "stylecard": _read(d / "stylecard.json"), "breakdown": _read(d / "breakdown.md")}


class SaveBody(BaseModel):
    saved: bool | None = None
    board: str | None = None
    tags: str | None = None


@app.post("/api/reels/{sc}/save")
def save(sc: str, body: SaveBody):
    with db.connect() as con:
        if body.saved is not None:
            con.execute("UPDATE reels SET saved=? WHERE shortcode=?", (int(body.saved), sc))
        if body.board is not None:
            con.execute("UPDATE reels SET board=? WHERE shortcode=?", (body.board.strip(), sc))
        if body.tags is not None:
            con.execute("UPDATE reels SET tags=? WHERE shortcode=?", (body.tags.strip(), sc))
    return {"ok": True}


@app.get("/api/boards")
def boards(niche: str | None = None):
    with db.connect() as con:
        w, a = ("AND niche=?", (niche,)) if niche else ("", ())
        return [dict(x) for x in con.execute(
            f"SELECT board, COUNT(*) n FROM reels WHERE board IS NOT NULL AND board != '' {w} GROUP BY board ORDER BY n DESC", a)]


@app.get("/api/cards")
def cards():
    out = []
    for p in sorted(REELS.glob("*/stylecard.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        c = json.loads(p.read_text(encoding="utf-8"))
        c["_shortcode"] = p.parent.name
        c["_kind"] = "reel"
        out.append(c)
    for p in sorted(CARDS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        c = json.loads(p.read_text(encoding="utf-8"))
        c["_file"] = p.name
        c["_kind"] = "house"
        out.append(c)
    return out


@app.get("/api/scripts")
def scripts():
    out = []
    for p in sorted(SCRIPTS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        text = p.read_text(encoding="utf-8")
        title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), p.stem)
        out.append({"file": p.name, "title": title, "text": text, "modified": p.stat().st_mtime})
    return out


@app.get("/api/reports")
def reports():
    out = []
    if REPORTS.exists():
        for p in sorted(REPORTS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            text = p.read_text(encoding="utf-8")
            title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), p.stem)
            out.append({"file": p.name, "title": title, "text": text, "modified": p.stat().st_mtime})
    return out


@app.get("/api/pipeline")
def pipeline(niche: str | None = None):
    """Pipeline overview: how many reels at each stage."""
    n = niche
    with db.connect() as con:
        w, a = ("WHERE niche=?", (n,)) if n else ("", ())
        st = con.execute(f"SELECT COUNT(*) total, SUM(status='analyzed') analyzed FROM reels {w}", a).fetchone()
    total = st["total"] or 0
    analyzed = st["analyzed"] or 0
    with_card = 0
    for p in REELS.glob("*/stylecard.json"):
        if not n:
            with_card += 1
        else:
            sc = p.parent.name
            with db.connect() as con2:
                r = con2.execute("SELECT niche FROM reels WHERE shortcode=?", (sc,)).fetchone()
                if r and r["niche"] == n:
                    with_card += 1
    scripts_count = sum(1 for _ in SCRIPTS.glob("*.md"))
    reports_count = sum(1 for _ in REPORTS.glob("*.md")) if REPORTS.exists() else 0
    return {
        "stages": [
            {"name": "Scout", "icon": "radar", "count": total, "label": "reels collected"},
            {"name": "Analyst", "icon": "analytics", "count": analyzed, "label": "analyzed"},
            {"name": "Decoder", "icon": "style", "count": with_card, "label": "style cards"},
            {"name": "Reporter", "icon": "summarize", "count": reports_count, "label": "reports"},
        ]
    }


@app.get("/api/hooks")
def hooks(niche: str | None = None, limit: int = 100):
    """Hook bank: all hooks extracted from analysis.json, ranked by views."""
    out = []
    with db.connect() as con:
        w, a = ("WHERE niche=?", (niche,)) if niche else ("", ())
        rows = con.execute(f"SELECT shortcode, owner, niche, COALESCE(plays,views,0) v, likes FROM reels {w}", a).fetchall()
    for r in rows:
        an = REELS / r["shortcode"] / "analysis.json"
        sc_file = REELS / r["shortcode"] / "stylecard.json"
        hook = None
        if sc_file.exists():
            try:
                card = json.loads(sc_file.read_text(encoding="utf-8"))
                if card.get("hook"):
                    hook = card["hook"]
            except Exception:
                pass
        if not hook and an.exists():
            try:
                analysis = json.loads(an.read_text(encoding="utf-8"))
                ht = analysis.get("metrics", {}).get("hook_text")
                if ht:
                    hook = {"text": ht, "type": "unknown"}
            except Exception:
                pass
        if hook and hook.get("text"):
            out.append({
                "shortcode": r["shortcode"],
                "owner": r["owner"],
                "views": r["v"],
                "likes": r["likes"],
                "hook_text": hook.get("text", ""),
                "hook_type": hook.get("type", "unknown"),
                "hook_seconds": hook.get("seconds"),
                "visual": hook.get("visual", ""),
            })
    out.sort(key=lambda x: (x["views"] or 0, x["likes"] or 0), reverse=True)
    return out[:limit]


@app.get("/api/trends")
def trends(niche: str | None = None, window: int = 7):
    """Rising hashtags, audio tracks, and topics in the niche."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()
    with db.connect() as con:
        w = "WHERE posted_at >= ?"
        a = [cutoff]
        if niche:
            w += " AND niche=?"
            a.append(niche)
        rows = con.execute(f"SELECT hashtags, audio, caption, COALESCE(plays,views,0) v FROM reels {w}", a).fetchall()

    hashtag_counts: dict[str, dict] = {}
    audio_counts: dict[str, dict] = {}
    for r in rows:
        v = r["v"] or 0
        tags = json.loads(r["hashtags"] or "[]")
        for t in tags:
            t = t.lower().strip("#")
            if t not in hashtag_counts:
                hashtag_counts[t] = {"count": 0, "total_views": 0}
            hashtag_counts[t]["count"] += 1
            hashtag_counts[t]["total_views"] += v
        aud = r["audio"]
        if aud:
            if aud not in audio_counts:
                audio_counts[aud] = {"count": 0, "total_views": 0}
            audio_counts[aud]["count"] += 1
            audio_counts[aud]["total_views"] += v

    top_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1]["count"], reverse=True)[:15]
    top_audio = sorted(audio_counts.items(), key=lambda x: x[1]["count"], reverse=True)[:10]

    return {
        "hashtags": [{"tag": t, **d} for t, d in top_hashtags],
        "audio": [{"name": a, **d} for a, d in top_audio],
    }


@app.get("/api/calendar")
def calendar_list(niche: str | None = None):
    """List calendar items."""
    cal_file = DATA / "calendar.json"
    if not cal_file.exists():
        return []
    items = json.loads(cal_file.read_text(encoding="utf-8"))
    if niche:
        items = [i for i in items if i.get("niche") == niche or not i.get("niche")]
    return items


class CalendarItem(BaseModel):
    date: str
    title: str
    type: str = "idea"
    niche: str | None = None
    reference: str | None = None
    notes: str | None = None
    status: str = "planned"


@app.post("/api/calendar")
def calendar_add(item: CalendarItem):
    """Add a calendar item."""
    cal_file = DATA / "calendar.json"
    items = json.loads(cal_file.read_text(encoding="utf-8")) if cal_file.exists() else []
    entry = item.model_dump()
    entry["id"] = len(items) + 1
    items.append(entry)
    cal_file.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return entry


@app.post("/api/calendar/{item_id}/update")
def calendar_update(item_id: int, item: CalendarItem):
    """Update a calendar item."""
    cal_file = DATA / "calendar.json"
    items = json.loads(cal_file.read_text(encoding="utf-8")) if cal_file.exists() else []
    for i in items:
        if i.get("id") == item_id:
            i.update(item.model_dump())
            break
    cal_file.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return {"ok": True}


@app.delete("/api/calendar/{item_id}")
def calendar_delete(item_id: int):
    """Delete a calendar item."""
    cal_file = DATA / "calendar.json"
    items = json.loads(cal_file.read_text(encoding="utf-8")) if cal_file.exists() else []
    items = [i for i in items if i.get("id") != item_id]
    cal_file.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return {"ok": True}


@app.get("/api/performance")
def performance(niche: str | None = None):
    """Compare own reels against reference reels."""
    with db.connect() as con:
        self_users = {x[0] for x in con.execute("SELECT username FROM creators WHERE is_self=1")}
        if not self_users:
            return {"own": [], "summary": None}
        placeholders = ",".join("?" * len(self_users))
        w = f"WHERE owner IN ({placeholders})"
        a = list(self_users)
        if niche:
            w += " AND niche=?"
            a.append(niche)
        own = [dict(r) for r in con.execute(f"SELECT * FROM reels {w} ORDER BY posted_at DESC", a).fetchall()]

    for r in own:
        v = int(r["plays"] or r["views"] or 0)
        r["views_best"] = v
        d = REELS / r["shortcode"]
        r["has_thumb"] = (d / "thumb.jpg").exists()
        r["has_analysis"] = (d / "analysis.json").exists()
        r["has_card"] = (d / "stylecard.json").exists()

    total_views = sum(r["views_best"] for r in own)
    total_likes = sum(int(r["likes"] or 0) for r in own)
    avg_eng = round(total_likes / max(total_views, 1) * 100, 2) if total_views else None
    return {
        "own": own,
        "summary": {
            "total_reels": len(own),
            "total_views": total_views,
            "total_likes": total_likes,
            "avg_engagement": avg_eng,
        }
    }


@app.get("/api/agents")
def agents_status():
    from .agents import get_agent_status, scheduler_status
    return {"agents": get_agent_status(), "scheduler": scheduler_status()}


@app.get("/api/agents/{agent}/logs")
def agent_logs(agent: str, limit: int = 20):
    from .agents import get_agent_logs
    return get_agent_logs(agent, limit)


@app.get("/api/agents/live-log")
def live_log(limit: int = 50):
    from .agents import get_live_log
    return get_live_log(limit)


@app.post("/api/agents/start")
def agents_start():
    from .agents import start_scheduler
    return start_scheduler()


@app.post("/api/agents/stop")
def agents_stop():
    from .agents import stop_scheduler
    return stop_scheduler()


@app.post("/api/agents/{agent}/run")
def agent_run_now(agent: str, niche: str | None = None):
    from .agents import run_agent
    import threading
    n = niche or (list_niches() or ["real-estate-india"])[0]
    t = threading.Thread(target=run_agent, args=(agent, n), daemon=True)
    t.start()
    return {"status": "started", "agent": agent, "niche": n}


@app.get("/media/{sc}/{path:path}")
def media(sc: str, path: str):
    base = (REELS / sc).resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


app.mount("/static", StaticFiles(directory=DASH), name="static")


@app.get("/")
def index():
    return FileResponse(DASH / "index.html")
