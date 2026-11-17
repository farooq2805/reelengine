"""Decode reels end to end: analysis.json, then stylecard.json and breakdown.md."""
from __future__ import annotations

from . import db
from .analyze import analyze
from .autopilot import _generate_stylecard
from .config import REELS


def decode(shortcode: str, frames: int = 5, log=print) -> bool:
    d = REELS / shortcode
    try:
        if not (d / "analysis.json").exists():
            analyze(shortcode, max_frames=frames, log=log)
        if not (d / "stylecard.json").exists():
            _generate_stylecard(shortcode)
        log(f"  card ready: {shortcode}")
        return True
    except Exception as e:  # one bad video shouldn't stop the batch
        log(f"  failed: {str(e).splitlines()[0][:200]}")
        with db.connect() as con:
            db.set_status(con, shortcode, "failed")
        return False


def decode_many(shortcodes: list[str], frames: int = 5, log=print) -> dict:
    ok = 0
    for i, sc in enumerate(shortcodes, 1):
        log(f"[{i}/{len(shortcodes)}] {sc}")
        ok += decode(sc, frames, log)
    return {"decoded": ok, "failed": len(shortcodes) - ok}
