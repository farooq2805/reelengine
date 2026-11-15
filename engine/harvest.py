"""Fill in details for reel links collected by hand or from a browser (no Instagram login needed).

Input file: one line per hashtag, `<hashtag> <shortcode> <shortcode> ...` (or one URL/shortcode per line).
Uses yt-dlp's public reel pages: creator, likes, comments, caption, date, duration, thumbnail.
View counts are not public there, so leaderboards fall back to likes for those reels.
"""
from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .scrape import save_thumb


def parse(path: str) -> list[tuple[str, str]]:
    pairs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = ""
        if not re.search(r"instagram\.com|^[A-Za-z0-9_-]{9,}$", parts[0]):
            tag, parts = parts[0].lstrip("#"), parts[1:]
        for p in parts:
            m = re.search(r"/(?:reel|reels|p)/([A-Za-z0-9_-]+)", p)
            pairs.append((m.group(1) if m else p, tag))
    return pairs


def harvest(path: str, niche: str, skip_known: bool = True, log=print) -> dict:
    import yt_dlp

    pairs = parse(path)
    stats = {"new": 0, "updated": 0, "failed": 0, "skipped": 0}
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True})
    with db.connect() as con:
        known = {r[0] for r in con.execute("SELECT shortcode FROM reels WHERE likes IS NOT NULL")}
    for i, (sc, tag) in enumerate(pairs, 1):
        if skip_known and sc in known:
            stats["skipped"] += 1
            continue
        try:
            info = ydl.extract_info(f"https://www.instagram.com/reel/{sc}/", download=False)
        except Exception as e:
            stats["failed"] += 1
            log(f"[{i}/{len(pairs)}] {sc}: failed ({str(e)[:80]})")
            time.sleep(random.uniform(3, 6))
            continue
        posted = (datetime.fromtimestamp(info["timestamp"], timezone.utc).isoformat()
                  if info.get("timestamp") else None)
        thumb = info.get("thumbnail")
        row = {
            "shortcode": sc, "niche": niche,
            "owner": (info.get("channel") or info.get("uploader_id") or "").lower(),
            "caption": info.get("description") or "",
            "hashtags": re.findall(r"#(\w+)", info.get("description") or ""),
            "posted_at": posted, "duration": info.get("duration"),
            "thumb_url": thumb,
            "views": info.get("view_count"), "likes": info.get("like_count"),
            "comments": info.get("comment_count"),
            "source": f"hashtag:{tag}" if tag else "harvest",
        }
        with db.connect() as con:
            stats["new" if db.upsert_reel(con, row) else "updated"] += 1
        save_thumb(sc, thumb)
        log(f"[{i}/{len(pairs)}] {sc} @{row['owner']} likes={row['likes']} comments={row['comments']}")
        time.sleep(random.uniform(2, 5))
    return stats
