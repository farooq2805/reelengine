"""Local dashboard API. Run with `engine serve`, open http://localhost:8765."""
from __future__ import annotations

import json
import re
import statistics
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


HOOK_RULES = [
    ("Comment CTA", re.compile(r"\bcomment\b", re.I)),
    ("POV", re.compile(r"^\s*pov\b", re.I)),
    ("Ranked list", re.compile(r"^\s*(top\s*\d+|\d+\s+\w+)|\brank(s|ed)?\b", re.I)),
    ("Myth vs truth", re.compile(r"\b(myth|truth|stop|mistake|don'?t|never)\b", re.I)),
    ("How-to", re.compile(r"\bhow\s+to\b", re.I)),
]


def hook_type(caption: str | None) -> str:
    cap = (caption or "").strip()
    first = re.split(r"[\n.!]", cap, maxsplit=1)[0]
    for name, rx in HOOK_RULES:
        if rx.search(cap if name == "Comment CTA" else first):
            return name
    return "Question" if first.endswith("?") else "Statement"


def _radar_rows(niche: str | None, window: int) -> list[dict]:
    rows = leaderboard(niche, window_days=window, sort="outlier", limit=100000)
    tracked = set(c.lower() for c in (load_niche(niche).get("creators") or [])) if niche else set()
    if tracked:  # collab posts land under co-authors' handles; keep the creators this niche tracks
        rows = [r for r in rows if r["owner"] in tracked or r["is_self"]]
    for r in rows:
        r["hook_type"] = hook_type(r.get("caption"))
    return rows


@app.get("/api/radar")
def radar(niche: str | None = None, window: int = 7, sort: str = "outlier", q: str | None = None,
          decoded: int = 0, max_dur: int = 0, hook: str | None = None, min_outlier: float = 0,
          limit: int = 18, offset: int = 0):
    rows = [r for r in _radar_rows(niche, window) if not r["is_self"]]
    if decoded:
        rows = [r for r in rows if r["has_analysis"]]
    if max_dur:
        rows = [r for r in rows if r.get("duration") and r["duration"] <= max_dur]
    if hook:
        rows = [r for r in rows if r["hook_type"] == hook]
    if min_outlier:
        rows = [r for r in rows if (r["outlier"] or 0) >= min_outlier]
    if q:
        words = q.lower().split()
        rows = [r for r in rows if all(w in " ".join(str(r.get(k) or "") for k in ("caption", "owner", "audio", "hook_type")).lower() for w in words)]
    keys = {"outlier": lambda r: r["outlier"] or 0, "velocity": lambda r: r["velocity"] or 0,
            "views": lambda r: r["views_best"], "likes": lambda r: int(r["likes"] or 0),
            "comments": lambda r: int(r["comments"] or 0), "engagement": lambda r: r["engagement"] or 0,
            "recent": lambda r: r["posted_at"] or ""}
    rows.sort(key=keys.get(sort, keys["outlier"]), reverse=True)
    return {"total": len(rows), "rows": rows[offset: offset + limit]}


@app.get("/api/radar/side")
def radar_side(niche: str | None = None, window: int = 7):
    from datetime import datetime, timedelta, timezone
    rows = [r for r in _radar_rows(niche, 0) if not r["is_self"]]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window or 3650)).isoformat()
    recent = [r for r in rows if (r.get("posted_at") or "") >= cutoff]

    def group(items, keyfn, min_n, min_owners=1):
        g: dict[str, list[float]] = {}
        owners: dict[str, set] = {}
        for r in items:
            for k in keyfn(r):
                if k and r["outlier"] is not None:
                    g.setdefault(k, []).append(r["outlier"])
                    owners.setdefault(k, set()).add(r["owner"])
        out = [{"name": k, "n": len(v), "creators": len(owners[k]), "median": round(statistics.median(v), 2),
                "hit_rate": round(sum(x >= 3 for x in v) / len(v), 2)}
               for k, v in g.items() if len(v) >= min_n and len(owners[k]) >= min_owners]
        return sorted(out, key=lambda x: (x["median"], x["n"]), reverse=True)

    audio = group(recent, lambda r: [r["audio"]] if r.get("audio") and r["audio"] != "Original audio" else [], 1)[:4]
    tags = group(recent, lambda r: [t.lower() for t in r.get("hashtags") or []], 3, min_owners=2)[:5]
    hooks = group(recent if len(recent) >= 40 else rows, lambda r: [r["hook_type"]], 5)
    now = datetime.now(timezone.utc)
    days = []
    with db.connect() as con:
        w, a = ("AND niche=?", (niche,)) if niche else ("", ())
        for i in range(13, -1, -1):
            d0 = (now - timedelta(days=i + 1)).isoformat()
            d1 = (now - timedelta(days=i)).isoformat()
            days.append(con.execute(f"SELECT COUNT(*) FROM reels WHERE first_seen >= ? AND first_seen < ? {w}", (d0, d1, *a)).fetchone()[0])
        last48 = con.execute(f"SELECT COUNT(*) FROM reels WHERE first_seen >= ? {w}", ((now - timedelta(hours=48)).isoformat(), *a)).fetchone()[0]
        new_today = con.execute(f"SELECT COUNT(*) FROM reels WHERE posted_at >= ? {w}", ((now - timedelta(hours=24)).isoformat(), *a)).fetchone()[0]
    return {"audio": audio, "hashtags": tags, "hooks": hooks, "telemetry": {"days": days, "last48": last48},
            "creators": len({r["owner"] for r in rows}), "reels": len(rows), "new_today": new_today,
            "audio_original_share": round(sum(r.get("audio") == "Original audio" for r in recent) / len(recent), 2) if recent else None}


_KW = re.compile(r"[Cc]omment\s+(?:[\"“'‘]([A-Za-z0-9]+)[\"”'’]|([A-Z][A-Z0-9]{2,})\b)")


def cta_keyword(caption: str | None) -> str | None:
    m = _KW.search(caption or "")
    return (m.group(1) or m.group(2)).upper() if m else None


def first_line(caption: str | None) -> str:
    for line in (caption or "").strip().splitlines():
        line = line.strip()
        if re.search(r"[A-Za-z]{3}", re.sub(r"#\w+", "", line)):
            return line[:200]
    return ""


def _dur_bucket(d):
    if not d:
        return None
    return "under 15s" if d < 15 else "15-30s" if d < 30 else "30-60s" if d < 60 else "over 60s"


def _local_slot(posted_at: str | None, niche: str):
    from datetime import datetime, timedelta, timezone
    if not posted_at:
        return None, None, None
    usa = "usa" in (niche or "")
    tz, label = (timezone(timedelta(hours=-5)), "ET") if usa else (timezone(timedelta(hours=5, minutes=30)), "IST")
    t = datetime.fromisoformat(posted_at).astimezone(tz)
    h = t.hour
    slot = "6-10am" if 6 <= h < 10 else "10am-2pm" if h < 14 else "2-6pm" if h < 18 else "6-10pm" if h < 22 else "10pm-6am"
    return slot, f"{t.strftime('%a %I:%M %p').replace(' 0', ' ')} {label}", label


def _stat(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {"n": len(vals), "median": round(statistics.median(vals), 2), "hit_rate": round(sum(v >= 3 for v in vals) / len(vals), 2)}


def reel_insights(row: dict) -> dict:
    niche = row["niche"]
    peers = _radar_rows(niche, 0)
    mine = [p for p in peers if p["owner"] == row["owner"]]
    v = row["views_best"] or 0

    def med(items, fn):
        vals = [fn(x) for x in items if fn(x) is not None]
        return statistics.median(vals) if vals else None

    eng_med = med(mine, lambda x: x.get("engagement"))
    cr = lambda x: (int(x.get("comments") or 0) / x["views_best"] * 100) if x.get("views_best") else None
    cr_med = med(mine, cr)
    rank = sorted(mine, key=lambda x: x["views_best"] or 0, reverse=True)
    rank_i = next((i for i, x in enumerate(rank, 1) if x["shortcode"] == row["shortcode"]), None)

    htype = hook_type(row.get("caption"))
    bucket = _dur_bucket(row.get("duration"))
    slot, posted_local, tzl = _local_slot(row.get("posted_at"), niche)
    is_orig = row.get("audio") == "Original audio"
    hook_line = first_line(row.get("caption"))
    kw = cta_keyword(row.get("caption"))

    by = lambda fn: _stat([p["outlier"] for p in peers if fn(p)])
    groups = {
        "hook": by(lambda p: p["hook_type"] == htype),
        "length": by(lambda p: _dur_bucket(p.get("duration")) == bucket) if bucket else None,
        "slot": by(lambda p: _local_slot(p.get("posted_at"), niche)[0] == slot) if slot else None,
        "audio": by(lambda p: (p.get("audio") == "Original audio") == is_orig) if row.get("audio") else None,
        "niche": by(lambda p: True),
    }

    why = []
    if row.get("outlier"):
        why.append(f"{row['outlier']}x @{row['owner']}'s median of {row['creator_median']:,} views" +
                   (f", their #{rank_i} of {len(mine)} recent reels." if rank_i else "."))
    if row.get("engagement") and eng_med:
        ratio = row["engagement"] / eng_med if eng_med else 0
        if ratio >= 1.25:
            why.append(f"Engagement {row['engagement']}% vs their usual {eng_med:.1f}%: people acted on it, not just watched.")
        elif ratio <= 0.8:
            why.append(f"Engagement {row['engagement']}% is below their usual {eng_med:.1f}%: reach came from non-followers, likely via shares or Explore.")
    c = cr(row)
    if c is not None and cr_med and c >= 2 * cr_med and int(row.get("comments") or 0) >= 50:
        why.append(f"Comments ran {c / cr_med:.1f}x their normal rate ({int(row['comments']):,})" +
                   (f", driven by the 'Comment {kw}' keyword." if kw else "."))
    base = groups["niche"]["hit_rate"] if groups["niche"] else 0
    odds = []
    for key, label in (("hook", f"'{htype}' hooks"), ("length", f"{bucket} reels"), ("slot", f"reels posted {slot} {tzl}")):
        g = groups[key]
        if not g or g["n"] < 5:
            continue
        line = f"{label[0].upper() + label[1:]} hit 3x {round(g['hit_rate']*100)}% of the time in this niche (baseline {round(base*100)}%, n={g['n']})"
        if g["hit_rate"] > base:
            why.append(line + ": a tailwind.")
        else:
            odds.append(line)
    if odds:
        why.append("It beat the odds on: " + "; ".join(odds) + ". The content itself carried it.")

    copy = []
    if hook_line:
        copy.append(f"Open with a line in the same shape: \"{hook_line[:120]}\"")
    if kw:
        copy.append(f"Add a comment keyword CTA (\"Comment {kw}\") and set up an auto-DM.")
    if bucket in ("under 15s", "15-30s"):
        copy.append(f"Keep it {bucket}; short reels break out most often here.")
    copy.append("Speak over it in your own voice." if is_orig else f"It uses a licensed track ({row.get('audio')}); test the same audio while it's rising.")
    return {"why": why, "copy": copy, "hook_type": htype, "first_line": hook_line, "cta_keyword": kw,
            "posted_local": posted_local, "length_bucket": bucket, "audio": row.get("audio"), "groups": groups,
            "creator": {"reels": len(mine), "median_views": row.get("creator_median"), "median_engagement": round(eng_med, 2) if eng_med else None,
                        "rank": rank_i}, "hashtags": row.get("hashtags") or [], "views": v}


ANGLES = {
    "Comment CTA": ("Resource giveaway", "Show the finished result in the first 2 seconds, then offer the prompts, template or tool list behind it: \"Comment {KW} and I'll send it.\""),
    "POV": ("First-person moment", "Film a \"POV:\" from inside an event, launch or workplace moment your audience can't access, within 48 hours of it happening."),
    "Ranked list": ("Ranked list", "Rank 5 tools or products your audience argues about, worst to best. Hold number 1 for the last 3 seconds."),
    "Myth vs truth": ("Myth vs truth", "Call out one thing your audience is doing wrong (\"Stop...\"), then show the right way with proof on screen."),
    "How-to": ("Fast tutorial", "Show one workflow end to end. Result first, then the 3 steps, all in under 30 seconds."),
    "Question": ("Question hook", "Open with the exact question your audience types into search, answer it in one line, then prove it."),
    "Statement": ("Bold claim", "Lead with your strongest opinion or result as text on screen, then spend the rest proving it."),
}
TRAIT_DROP_ORDER = ["audio", "slot", "length", "cta", "hook"]


def _traits(p: dict, niche: str) -> dict:
    return {"hook": p.get("hook_type") or hook_type(p.get("caption")), "length": _dur_bucket(p.get("duration")),
            "slot": _local_slot(p.get("posted_at"), niche)[0],
            "cta": "yes" if re.search(r"\bcomment\b", p.get("caption") or "", re.I) else "no",
            "audio": "original" if p.get("audio") == "Original audio" else ("licensed" if p.get("audio") else None)}


def _q(vals: list[float], q: float) -> float:
    s = sorted(vals)
    if not s:
        return 0.0
    i = (len(s) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _peers(niche: str) -> list[dict]:
    peers = [p for p in _radar_rows(niche, 0) if not p["is_self"] and p["outlier"] is not None]
    for p in peers:
        p["_t"] = _traits(p, niche)
    return peers


def baseline_for(niche: str) -> dict:
    self_user = (load_niche(niche).get("self_username") or "").lower()
    if not self_user:
        return {"account": None, "median": None, "n": 0}
    with db.connect() as con:
        vals = [int(x[0]) for x in con.execute(
            "SELECT COALESCE(plays, views) FROM reels WHERE owner=? AND COALESCE(plays, views) > 0", (self_user,))]
    return {"account": self_user, "median": round(statistics.median(vals)) if vals else None, "n": len(vals)}


def forecast_from(peers: list[dict], want: dict, baseline: float | None, relax: bool = True) -> dict:
    want = {k: v for k, v in want.items() if k in TRAIT_DROP_ORDER and v not in (None, "", "any")}
    used = dict(want)
    while True:
        match = [p for p in peers if all(p["_t"].get(k) == v for k, v in used.items())]
        if len(match) >= 12 or not used or not relax:
            break
        used.pop(next(k for k in TRAIT_DROP_ORDER if k in used))
    vals = [p["outlier"] for p in match]
    allv = [p["outlier"] for p in peers]
    niche_med = statistics.median(allv) if allv else 1
    lifts = []
    for k, v in want.items():
        sub = [p["outlier"] for p in peers if p["_t"].get(k) == v]
        if len(sub) >= 5:
            lifts.append({"trait": k, "value": v, "n": len(sub), "lift": round(statistics.median(sub) / niche_med, 2),
                          "hit_rate": round(sum(x >= 3 for x in sub) / len(sub), 2)})
    mult = {"low": round(_q(vals, .25), 2), "likely": round(_q(vals, .5), 2), "high": round(_q(vals, .75), 2),
            "breakout": round(_q(vals, .9), 2)} if vals else None
    views = {k: round(baseline * m) for k, m in mult.items()} if (mult and baseline) else None
    return {"n": len(match), "used": used, "dropped": [k for k in want if k not in used], "multiple": mult, "views": views,
            "hit_rate": round(sum(x >= 3 for x in vals) / len(vals), 2) if vals else None,
            "niche_hit_rate": round(sum(x >= 3 for x in allv) / len(allv), 2) if allv else None, "lifts": lifts, "baseline": baseline}


@app.get("/api/forecast")
def forecast(niche: str, hook: str | None = None, length: str | None = None, slot: str | None = None,
             cta: str | None = None, audio: str | None = None, baseline: float | None = None):
    b = baseline or baseline_for(niche)["median"]
    return forecast_from(_peers(niche), {"hook": hook, "length": length, "slot": slot, "cta": cta, "audio": audio}, b)


@app.get("/api/ideas")
def ideas(niche: str, window: int = 30, limit: int = 9, baseline: float | None = None):
    from datetime import datetime, timedelta, timezone
    peers = _peers(niche)
    base = baseline_for(niche)
    b = baseline or base["median"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window or 3650)).isoformat()
    pool = sorted([p for p in peers if (p.get("posted_at") or "") >= cutoff], key=lambda p: p["outlier"], reverse=True)
    per, out = {}, []
    for p in pool:
        if per.get(p["owner"], 0) >= 2 or p["outlier"] < 2:
            continue
        per[p["owner"]] = per.get(p["owner"], 0) + 1
        t = p["_t"]
        name, angle = ANGLES.get(t["hook"], ANGLES["Statement"])
        kw = cta_keyword(p.get("caption"))
        out.append({"shortcode": p["shortcode"], "owner": p["owner"], "outlier": p["outlier"], "views": p["views_best"],
                    "has_thumb": p["has_thumb"], "posted_at": p["posted_at"], "duration": p.get("duration"),
                    "reference_hook": first_line(p.get("caption"))[:160],
                    "format": name, "angle": angle.replace("{KW}", kw or "GUIDE"), "traits": t,
                    "forecast": forecast_from(peers, t, b)})
        if len(out) >= limit:
            break
    hooks = []
    for h in sorted({p["_t"]["hook"] for p in peers}):
        f = forecast_from(peers, {"hook": h}, b, relax=False)
        if f["n"] >= 8:
            hooks.append({"hook": h, "format": ANGLES.get(h, ANGLES["Statement"])[0], **f})
    hooks.sort(key=lambda x: x["multiple"]["likely"] if x["multiple"] else 0, reverse=True)
    return {"baseline": base, "baseline_used": b, "ideas": out, "formats": hooks, "reels": len(peers)}


_gap_refreshing: set[str] = set()


@app.get("/api/gaps")
def gaps(niche: str, baseline: float | None = None):
    from .demand import analyze
    data = analyze(niche)
    peers = _peers(niche)
    base = baseline_for(niche)
    b = baseline or base["median"]
    for t in data["topics"]:
        t["forecast"] = forecast_from(peers, {"hook": t["format"]}, b)
    return {**data, "baseline": base, "baseline_used": b, "refreshing": niche in _gap_refreshing}


@app.post("/api/gaps/refresh")
def gaps_refresh(niche: str):
    import threading
    from .demand import collect
    if niche in _gap_refreshing:
        return {"status": "running"}
    _gap_refreshing.add(niche)

    def run():
        try:
            collect(niche)
        finally:
            _gap_refreshing.discard(niche)
    threading.Thread(target=run, daemon=True).start()
    return {"status": "started"}


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
    insights = reel_insights(row) if row.get("views_best") is not None else None
    base = baseline_for(r["niche"])
    fc = forecast_from(_peers(r["niche"]), _traits({**row, "hook_type": hook_type(row.get("caption"))}, r["niche"]), base["median"])
    return {**row, "snapshots": snaps, "insights": insights, "forecast": fc, "baseline": base, "decoding": sc in _decoding,
            "analysis": _read(d / "analysis.json"), "stylecard": _read(d / "stylecard.json"), "breakdown": _read(d / "breakdown.md")}


_decoding: set[str] = set()


@app.post("/api/reels/{sc}/decode")
def reel_decode(sc: str):
    import threading
    from .decode import decode
    if sc in _decoding:
        return {"status": "running"}
    _decoding.add(sc)

    def run():
        try:
            decode(sc)
        finally:
            _decoding.discard(sc)
    threading.Thread(target=run, daemon=True).start()
    return {"status": "started"}


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
