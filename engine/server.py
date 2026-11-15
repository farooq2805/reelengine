"""Local dashboard API. Run with `engine serve`, open http://localhost:8765."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .config import CARDS, REELS, REPORTS, ROOT, SCRIPTS, list_niches, load_niche
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
