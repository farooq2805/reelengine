"""Autopilot pipeline: runs the full content engine end-to-end for a niche.

Agents / stages:
  1. Scout    — scrape hashtags + creators, harvest any pending shortcode files
  2. Analyst  — analyze top outlier reels (download + transcript + cuts + frames + colors + vision)
  3. Decoder  — generate style cards for analyzed reels that don't have one yet
  4. Reporter — produce a summary of what was found
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from . import db
from .config import DATA, REELS, list_niches, load_niche, reel_dir

_status: dict = {}


def status() -> dict:
    return dict(_status)


def _log(agent: str, msg: str):
    _status[agent] = {"msg": msg, "ts": time.time()}
    print(f"  [{agent}] {msg}")


def run_scout(niche: str, harvest_file: str | None = None) -> dict:
    """Stage 1: gather new reels."""
    _log("scout", "Starting — scanning hashtags and creators")
    result = {"new": 0, "updated": 0, "harvested": 0, "errors": []}

    recipe = load_niche(niche)
    has_session = False
    try:
        from .scrape import _session_file
        has_session = _session_file().exists()
    except Exception:
        pass

    if has_session:
        try:
            from .scrape import scrape
            s = scrape(niche, hashtags=True, creators=True)
            result["new"] += s["new"]
            result["updated"] += s["updated"]
            result["errors"].extend(s["errors"])
            _log("scout", f"Scraped: {s['new']} new, {s['updated']} updated")
        except Exception as e:
            result["errors"].append(f"scrape: {e}")
            _log("scout", f"Scrape failed: {e}")

    if harvest_file:
        hf = Path(harvest_file)
        if hf.exists():
            try:
                from .harvest import harvest
                h = harvest(str(hf), niche)
                result["harvested"] = h.get("imported", 0) if isinstance(h, dict) else 0
                _log("scout", f"Harvested from {hf.name}")
            except Exception as e:
                result["errors"].append(f"harvest: {e}")

    try:
        from .scrape import discover
        added = discover(niche, max_new=15)
        _log("scout", f"Discovered {len(added)} new creators")
    except Exception as e:
        result["errors"].append(f"discover: {e}")

    _log("scout", f"Done — {result['new']} new reels, {result['harvested']} harvested")
    return result


def run_analyst(niche: str, top: int = 10, window: int = 7) -> dict:
    """Stage 2: analyze top reels that haven't been decoded yet."""
    from .analyze import analyze, queue

    codes = queue(niche, window_days=window, top=top)
    _log("analyst", f"Queued {len(codes)} reels for analysis")
    result = {"analyzed": 0, "failed": 0, "codes": []}

    for i, sc in enumerate(codes, 1):
        _log("analyst", f"[{i}/{len(codes)}] Analyzing {sc}")
        try:
            analyze(sc, use_vision=True, max_frames=10)
            result["analyzed"] += 1
            result["codes"].append(sc)
        except Exception as e:
            result["failed"] += 1
            _log("analyst", f"  Failed: {e}")

    _log("analyst", f"Done — {result['analyzed']} analyzed, {result['failed']} failed")
    return result


def run_decoder(niche: str, top: int = 10, window: int = 0) -> dict:
    """Stage 3: generate style cards for analyzed reels missing one."""
    from .score import leaderboard

    rows = leaderboard(niche, window_days=window, sort="outlier", limit=200)
    need = []
    for r in rows:
        d = reel_dir(r["shortcode"])
        if (d / "analysis.json").exists() and not (d / "stylecard.json").exists():
            need.append(r["shortcode"])
        if len(need) >= top:
            break

    _log("decoder", f"Queued {len(need)} reels for style cards")
    result = {"decoded": 0, "failed": 0, "codes": []}

    for i, sc in enumerate(need, 1):
        _log("decoder", f"[{i}/{len(need)}] Generating style card for {sc}")
        try:
            _generate_stylecard(sc)
            result["decoded"] += 1
            result["codes"].append(sc)
        except Exception as e:
            result["failed"] += 1
            _log("decoder", f"  Failed: {e}")

    _log("decoder", f"Done — {result['decoded']} style cards created")
    return result


def _generate_stylecard(shortcode: str):
    """Build a stylecard.json from analysis.json for a single reel."""
    d = reel_dir(shortcode)
    an = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
    m = an.get("metrics", {})
    t = an.get("transcript", {})
    c = an.get("colour", {})
    frames = an.get("frames", [])
    vis = an.get("vision", {})

    hook_text = m.get("hook_text", "")
    hook_type = "question" if hook_text.rstrip().endswith("?") else "statement" if len(hook_text.split()) < 8 else "story"
    duration = m.get("duration", 0)

    structure = []
    if m.get("first_cut_at"):
        structure.append({"part": "hook", "start": 0, "end": round(m["first_cut_at"], 1), "what": hook_text[:80]})
    if duration > 10:
        mid_start = m.get("first_cut_at", 3)
        mid_end = duration * 0.85
        structure.append({"part": "body", "start": round(mid_start, 1), "end": round(mid_end, 1), "what": "Main content"})
        structure.append({"part": "cta", "start": round(mid_end, 1), "end": round(duration, 1), "what": "Call to action / close"})

    shots_mix = {}
    if vis.get("frame_descriptions"):
        descs = [f.get("description", "") for f in vis["frame_descriptions"]]
        talking = sum(1 for d_ in descs if any(w in d_.lower() for w in ("person", "face", "talking", "speaking")))
        total = len(descs) or 1
        shots_mix = {"talking_head": round(talking / total, 2), "b_roll": round(1 - talking / total, 2)}

    palette = []
    for p in (c.get("palette") or [])[:5]:
        palette.append(p.get("hex", p) if isinstance(p, dict) else p)

    card = {
        "name": f"Style of {shortcode}",
        "summary": f"{m.get('shots', '?')} shots, {m.get('cuts_per_10s', '?')} cuts/10s, {m.get('words_per_minute', '?'):.0f} WPM" if m.get("words_per_minute") else f"{m.get('shots', '?')} shots",
        "source": shortcode,
        "hook": {"type": hook_type, "text": hook_text, "seconds": round(m.get("first_cut_at", 3), 1)},
        "structure": structure,
        "pacing": {"cuts_per_10s": m.get("cuts_per_10s"), "avg_shot_seconds": m.get("avg_shot_seconds"), "wpm": m.get("words_per_minute")},
        "colour": {"grade": c.get("grade", ""), "palette": palette},
        "shots": {"mix": shots_mix} if shots_mix else None,
        "captions": {"style": "phrase", "font": "sans-serif", "weight": "bold"},
        "audio": {"music": "background" if m.get("speech_ratio", 1) < 0.9 else "none/minimal"},
        "why_it_worked": [],
        "do": [],
        "dont": [],
    }

    reasons = []
    if m.get("cuts_per_10s") and m["cuts_per_10s"] > 3:
        reasons.append("Fast pacing keeps attention — high cut rate")
    if hook_text and len(hook_text.split()) <= 10:
        reasons.append("Short punchy hook grabs in under 3 seconds")
    if m.get("speech_ratio", 0) > 0.7:
        reasons.append("Continuous narration maintains engagement")
    if m.get("words_per_minute") and m["words_per_minute"] > 160:
        reasons.append("High energy delivery — fast speaking pace")
    card["why_it_worked"] = reasons or ["Strong visual storytelling"]

    (d / "stylecard.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")

    breakdown = f"# How to remake: {shortcode}\n\n"
    breakdown += f"**Duration:** {duration:.0f}s | **Shots:** {m.get('shots', '?')} | **Cuts/10s:** {m.get('cuts_per_10s', '?')}\n\n"
    breakdown += f"## Hook\n\"{hook_text}\"\n\n"
    breakdown += f"## Structure\n"
    for s in structure:
        breakdown += f"- **{s['part'].title()}** ({s['start']}–{s['end']}s): {s['what']}\n"
    breakdown += f"\n## Colour\nGrade: {c.get('grade', '?')}\nPalette: {', '.join(palette)}\n"
    if t.get("text"):
        words = t["text"].split()
        breakdown += f"\n## Transcript ({len(words)} words)\n{t['text'][:500]}{'...' if len(t['text'])>500 else ''}\n"
    (d / "breakdown.md").write_text(breakdown, encoding="utf-8")


def run_reporter(niche: str, window: int = 7) -> dict:
    """Stage 4: generate a quick status report."""
    from .score import leaderboard

    rows = leaderboard(niche, window_days=window, sort="outlier", limit=50)
    recipe = load_niche(niche)
    now = datetime.now().strftime("%Y-%m-%d")

    with db.connect() as con:
        w, a = ("WHERE niche=?", (niche,)) if niche else ("", ())
        st = con.execute(f"SELECT COUNT(*) total, SUM(status='analyzed') analyzed FROM reels {w}", a).fetchone()

    top5 = rows[:5]
    decoded = sum(1 for r in rows if (reel_dir(r["shortcode"]) / "stylecard.json").exists())

    report = f"# Autopilot Report — {recipe.get('name', niche)}\n\n"
    report += f"**Date:** {now} | **Window:** {window}d\n\n"
    report += f"## Overview\n"
    report += f"- **Total reels:** {st['total']}\n"
    report += f"- **Analyzed:** {st['analyzed']}\n"
    report += f"- **With style cards:** {decoded}\n"
    report += f"- **Top outlier reels in window:** {len(rows)}\n\n"

    if top5:
        report += f"## Top 5 Outliers\n\n"
        report += "| # | Owner | Outlier | Likes | Link |\n|---|---|---|---|---|\n"
        for i, r in enumerate(top5, 1):
            report += f"| {i} | @{r['owner'] or '?'} | {r['outlier']}x | {r['likes'] or 0:,.0f} | [reel](https://instagram.com/reel/{r['shortcode']}) |\n"

    REPORTS = DATA / "reports"
    REPORTS.mkdir(exist_ok=True)
    fname = f"{now}-autopilot-{niche}.md"
    (REPORTS / fname).write_text(report, encoding="utf-8")
    _log("reporter", f"Wrote {fname}")
    return {"file": fname}


def autopilot(niche: str, top: int = 10, window: int = 7, harvest_file: str | None = None) -> dict:
    """Run the full pipeline for a niche."""
    _status.clear()
    t0 = time.time()
    results = {}

    print(f"\n{'='*60}")
    print(f"  AUTOPILOT — {niche}")
    print(f"{'='*60}\n")

    print("▶ Stage 1: SCOUT")
    results["scout"] = run_scout(niche, harvest_file)

    print("\n▶ Stage 2: ANALYST")
    results["analyst"] = run_analyst(niche, top=top, window=window)

    print("\n▶ Stage 3: DECODER")
    results["decoder"] = run_decoder(niche, top=top, window=0)

    print("\n▶ Stage 4: REPORTER")
    results["reporter"] = run_reporter(niche, window=window)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  DONE in {elapsed:.0f}s")
    print(f"  Scout: {results['scout'].get('new',0)} new + {results['scout'].get('harvested',0)} harvested")
    print(f"  Analyst: {results['analyst']['analyzed']} analyzed")
    print(f"  Decoder: {results['decoder']['decoded']} style cards")
    print(f"  Reporter: {results['reporter']['file']}")
    print(f"{'='*60}\n")

    return results
