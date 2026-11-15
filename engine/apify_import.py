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


def import_dataset(dataset_id: str, niche: str, source: str = "apify", token: str | None = None) -> dict:
    stats = {"new": 0, "updated": 0, "skipped": 0}
    offset = 0
    with db.connect() as con:
        while True:
            params = {"fields": FIELDS, "limit": 500, "offset": offset, "clean": 1}
            if token:
                params["token"] = token
            items = requests.get(API.format(id=dataset_id), params=params, timeout=60).json()
            if not items:
                break
            for it in items:
                sc = it.get("shortCode")
                if not sc or not (it.get("videoUrl") or it.get("type") == "Video" or it.get("productType") == "clips"):
                    stats["skipped"] += 1
                    continue
                tag = ""
                if "explore/tags/" in (it.get("inputUrl") or ""):
                    tag = it["inputUrl"].rstrip("/").split("/")[-1]
                song = it.get("musicInfo.song_name") or ""
                artist = it.get("musicInfo.artist_name") or ""
                audio = "Original audio" if it.get("musicInfo.uses_original_audio") else " - ".join(x for x in (song, artist) if x)
                row = {
                    "shortcode": sc, "niche": niche,
                    "owner": (it.get("ownerUsername") or "").lower(),
                    "caption": it.get("caption") or "",
                    "hashtags": it.get("hashtags") or [],
                    "posted_at": (it.get("timestamp") or "").replace("Z", "+00:00") or None,
                    "duration": it.get("videoDuration"),
                    "video_url": it.get("videoUrl"),
                    "thumb_url": it.get("displayUrl"),
                    "views": _num(it.get("igPlayCount")),
                    "plays": _num(it.get("videoPlayCount")),
                    "likes": _num(it.get("likesCount")),
                    "comments": _num(it.get("commentsCount")),
                    "shares": _num(it.get("sharesCount")),
                    "audio": audio or None,
                    "source": f"hashtag:{tag}" if tag else source,
                }
                stats["new" if db.upsert_reel(con, row) else "updated"] += 1
                save_thumb(sc, row["thumb_url"])
            con.commit()
            offset += len(items)
            if len(items) < 500:
                break
    return stats
