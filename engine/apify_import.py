"""Import reels scraped by Apify's Instagram actors (hashtag / reel / profile scrapers).

Optional paid fallback to the free Instaloader route. Apify also returns share counts,
which Instagram hides from logged-out and Instaloader requests.
"""
from __future__ import annotations

import requests

from . import db
from .scrape import save_thumb

API = "https://api.apify.com/v2/datasets/{id}/items"
FIELDS = ("shortCode,caption,timestamp,ownerUsername,likesCount,commentsCount,videoPlayCount,igPlayCount,"
          "sharesCount,videoDuration,videoUrl,displayUrl,hashtags,productType,type,inputUrl,"
          "musicInfo.song_name,musicInfo.artist_name,musicInfo.uses_original_audio")


def _num(v):
    try:
        n = int(v)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def _get(it: dict, key: str):
    """Get a value supporting both flat dot-keys (API ?fields) and nested dicts (full export)."""
    if key in it:
        return it[key]
    parts = key.split(".")
    cur = it
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def _process_items(items: list[dict], niche: str, source: str = "apify") -> dict:
    stats = {"new": 0, "updated": 0, "skipped": 0}
    with db.connect() as con:
        for it in items:
            sc = _get(it, "shortCode")
            if not sc or not (_get(it, "videoUrl") or _get(it, "type") == "Video" or _get(it, "productType") == "clips"):
                stats["skipped"] += 1
                continue
            tag = ""
            input_url = _get(it, "inputUrl") or ""
            if "explore/tags/" in input_url:
                tag = input_url.rstrip("/").split("/")[-1]
            song = _get(it, "musicInfo.song_name") or ""
            artist = _get(it, "musicInfo.artist_name") or ""
            audio = "Original audio" if _get(it, "musicInfo.uses_original_audio") else " - ".join(x for x in (song, artist) if x)
            row = {
                "shortcode": sc, "niche": niche,
                "owner": (_get(it, "ownerUsername") or "").lower(),
                "caption": _get(it, "caption") or "",
                "hashtags": _get(it, "hashtags") or [],
                "posted_at": (_get(it, "timestamp") or "").replace("Z", "+00:00") or None,
                "duration": _get(it, "videoDuration"),
                "video_url": _get(it, "videoUrl"),
                "thumb_url": _get(it, "displayUrl"),
                "views": _num(_get(it, "igPlayCount")),
                "plays": _num(_get(it, "videoPlayCount")),
                "likes": _num(_get(it, "likesCount")),
                "comments": _num(_get(it, "commentsCount")),
                "shares": _num(_get(it, "sharesCount")),
                "audio": audio or None,
                "source": f"hashtag:{tag}" if tag else source,
            }
            stats["new" if db.upsert_reel(con, row) else "updated"] += 1
            save_thumb(sc, row["thumb_url"])
        con.commit()
    return stats


def import_file(filepath: str, niche: str, source: str = "apify") -> dict:
    """Import from a local JSON file exported from Apify console."""
    import json as _json
    from pathlib import Path
    items = _json.loads(Path(filepath).read_text(encoding="utf-8"))
    return _process_items(items, niche, source)


def import_dataset(dataset_id: str, niche: str, source: str = "apify", token: str | None = None) -> dict:
    stats = {"new": 0, "updated": 0, "skipped": 0}
    offset = 0
    while True:
        params = {"fields": FIELDS, "limit": 500, "offset": offset, "clean": 1}
        if token:
            params["token"] = token
        items = requests.get(API.format(id=dataset_id), params=params, timeout=60).json()
        if not items:
            break
        result = _process_items(items, niche, source)
        for k in stats:
            stats[k] += result[k]
        offset += len(items)
        if len(items) < 500:
            break
    return stats
