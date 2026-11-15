"""Leaderboards: outlier score, velocity and engagement, computed from the stored reels."""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone

from . import db
from .config import REELS

SORTS = {"outlier", "views", "likes", "comments", "shares", "engagement", "velocity", "recent"}


def _views(r) -> int:
    # Instagram exposes both; "plays" counts replays and is what the app shows on reels.
    return int(r["plays"] or r["views"] or 0)


def _hours_since(iso: str | None) -> float:
    if not iso:
        return 0.0
    t = datetime.fromisoformat(iso)
    return max((datetime.now(timezone.utc) - t).total_seconds() / 3600, 1.0)


def _velocity(con, shortcode: str, fallback_views: int, posted_at: str | None) -> float:
    """Views gained per hour between the last two snapshots; else views / hours since posting."""
    snaps = con.execute(
        "SELECT ts, COALESCE(plays, views) v FROM snapshots WHERE shortcode=? AND COALESCE(plays, views) IS NOT NULL "
        "ORDER BY ts DESC LIMIT 2", (shortcode,)
    ).fetchall()
    if len(snaps) == 2:
        dt = (datetime.fromisoformat(snaps[0]["ts"]) - datetime.fromisoformat(snaps[1]["ts"])).total_seconds() / 3600
        if dt >= 1:
            return max(snaps[0]["v"] - snaps[1]["v"], 0) / dt
    return fallback_views / _hours_since(posted_at)


def leaderboard(niche: str | None, window_days: int = 7, sort: str = "outlier", limit: int = 60,
                saved: bool | None = None, query: str | None = None, owner: str | None = None,
                offset: int = 0) -> list[dict]:
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {sorted(SORTS)}")
    where, args = ["1=1"], []
    if niche:
        where.append("niche=?"); args.append(niche)
    if window_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        where.append("(posted_at >= ? OR posted_at IS NULL)"); args.append(cutoff)
    if saved is not None:
        where.append("saved=?"); args.append(int(saved))
    if owner:
        where.append("owner=?"); args.append(owner.lower())
    if query:
        where.append("(caption LIKE ? OR owner LIKE ? OR tags LIKE ? OR board LIKE ?)")
        args += [f"%{query}%"] * 4

    with db.connect() as con:
        rows = [dict(r) for r in con.execute(f"SELECT * FROM reels WHERE {' AND '.join(where)}", args)]
        # Creator medians over everything we have for them (not just this window).
        # Views when known; reels collected without a login only have likes, so those compare on likes.
        medians: dict[tuple[str, str], float] = {}
        for o in {r["owner"] for r in rows if r["owner"]}:
            for basis, col in (("views", "COALESCE(plays, views)"), ("likes", "likes")):
                vals = [int(x[0]) for x in con.execute(
                    f"SELECT {col} FROM reels WHERE owner=? AND {col} > 0", (o,))]
                medians[(o, basis)] = statistics.median(vals) if len(vals) >= 3 else 0.0
        self_users = {x[0] for x in con.execute("SELECT username FROM creators WHERE is_self=1")}

        for r in rows:
            v = _views(r)
            basis = "views" if v else "likes"
            val = v or int(r["likes"] or 0)
            med = medians.get((r["owner"] or "", basis), 0.0)
            r["views_best"] = v
            r["outlier_basis"] = basis
            r["creator_median"] = round(med)
            r["outlier"] = round(val / med, 2) if med else None
            # Likes + comments + shares (when known) per view.
            r["engagement"] = round((int(r["likes"] or 0) + int(r["comments"] or 0) + int(r.get("shares") or 0))
                                    / v * 100, 2) if v else None
            r["velocity"] = round(_velocity(con, r["shortcode"], v, r["posted_at"]), 1)
            r["hashtags"] = json.loads(r["hashtags"] or "[]")
            r["is_self"] = r["owner"] in self_users
            d = REELS / r["shortcode"]
            r["has_thumb"] = (d / "thumb.jpg").exists()
            r["has_video"] = (d / "video.mp4").exists()
            r["has_analysis"] = (d / "analysis.json").exists()
            r["has_card"] = (d / "stylecard.json").exists()

    key = {
        "outlier": lambda r: (r["outlier"] or 0, r["views_best"], int(r["likes"] or 0)),
        "views": lambda r: (r["views_best"], int(r["likes"] or 0)),
        "likes": lambda r: int(r["likes"] or 0),
        "comments": lambda r: int(r["comments"] or 0),
        "shares": lambda r: int(r.get("shares") or 0),
        "engagement": lambda r: r["engagement"] or 0,
        "velocity": lambda r: r["velocity"] or 0,
        "recent": lambda r: r["posted_at"] or "",
    }[sort]
    rows.sort(key=key, reverse=True)
    return rows[offset: offset + limit]
