"""SQLite storage: reels, stats history, creators."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    username   TEXT NOT NULL,
    niche      TEXT NOT NULL,
    followers  INTEGER,
    is_self    INTEGER DEFAULT 0,
    source     TEXT,                 -- recipe | discovered | manual
    added_at   TEXT,
    PRIMARY KEY (username, niche)
);

CREATE TABLE IF NOT EXISTS reels (
    shortcode  TEXT PRIMARY KEY,
    niche      TEXT,
    owner      TEXT,
    caption    TEXT,
    hashtags   TEXT,                 -- JSON list
    posted_at  TEXT,                 -- ISO UTC
    duration   REAL,
    video_url  TEXT,
    thumb_url  TEXT,
    views      INTEGER,              -- Instagram "views" (video_view_count)
    plays      INTEGER,              -- Instagram "plays" (video_play_count), often higher
    likes      INTEGER,
    comments   INTEGER,
    source     TEXT,                 -- creator | hashtag | url | file
    first_seen TEXT,
    last_seen  TEXT,
    saved      INTEGER DEFAULT 0,
    board      TEXT,
    tags       TEXT,
    status     TEXT DEFAULT 'new'    -- new | downloaded | analyzed | failed
);

CREATE TABLE IF NOT EXISTS snapshots (
    shortcode  TEXT,
    ts         TEXT,
    views      INTEGER,
    plays      INTEGER,
    likes      INTEGER,
    comments   INTEGER
);

CREATE INDEX IF NOT EXISTS ix_reels_niche ON reels(niche, posted_at);
CREATE INDEX IF NOT EXISTS ix_reels_owner ON reels(owner);
CREATE INDEX IF NOT EXISTS ix_snap ON snapshots(shortcode, ts);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect():
    ensure_dirs()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(reels)")}
    for col, typ in (("shares", "INTEGER"), ("audio", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE reels ADD COLUMN {col} {typ}")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def upsert_reel(con: sqlite3.Connection, r: dict) -> bool:
    """Insert or update a reel and record a stats snapshot. Returns True if new."""
    ts = now()
    existing = con.execute("SELECT shortcode FROM reels WHERE shortcode=?", (r["shortcode"],)).fetchone()
    fields = {
        "niche": r.get("niche"),
        "owner": r.get("owner"),
        "caption": r.get("caption"),
        "hashtags": json.dumps(r.get("hashtags") or []),
        "posted_at": r.get("posted_at"),
        "duration": r.get("duration"),
        "video_url": r.get("video_url"),
        "thumb_url": r.get("thumb_url"),
        "views": r.get("views"),
        "plays": r.get("plays"),
        "likes": r.get("likes"),
        "comments": r.get("comments"),
        "shares": r.get("shares"),
        "audio": r.get("audio"),
        "source": r.get("source"),
    }
    if existing:
        # Never overwrite good data with blanks.
        sets = {k: v for k, v in fields.items() if v not in (None, "", "[]")}
        sets["last_seen"] = ts
        con.execute(
            f"UPDATE reels SET {', '.join(f'{k}=?' for k in sets)} WHERE shortcode=?",
            (*sets.values(), r["shortcode"]),
        )
    else:
        fields.update(shortcode=r["shortcode"], first_seen=ts, last_seen=ts)
        con.execute(
            f"INSERT INTO reels ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
            tuple(fields.values()),
        )
    con.execute(
        "INSERT INTO snapshots (shortcode, ts, views, plays, likes, comments) VALUES (?,?,?,?,?,?)",
        (r["shortcode"], ts, r.get("views"), r.get("plays"), r.get("likes"), r.get("comments")),
    )
    return existing is None


def add_creator(con, username: str, niche: str, source: str, followers: int | None = None, is_self: bool = False):
    con.execute(
        """INSERT INTO creators (username, niche, followers, is_self, source, added_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(username, niche) DO UPDATE SET
             followers=COALESCE(excluded.followers, creators.followers),
             is_self=MAX(creators.is_self, excluded.is_self)""",
        (username.lower(), niche, followers, int(is_self), source, now()),
    )


def set_status(con, shortcode: str, status: str):
    con.execute("UPDATE reels SET status=? WHERE shortcode=?", (status, shortcode))
