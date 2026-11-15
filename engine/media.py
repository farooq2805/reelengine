"""Getting reel videos onto disk: from Instagram (Instaloader / yt-dlp) or from a local file."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import db
from .config import reel_dir

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _fetch(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=60, headers=UA) as r:
            if not r.ok:
                return False
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return dest.stat().st_size > 10_000
    except requests.RequestException:
        return False


def download(shortcode: str, browser_cookies: str | None = None) -> Path:
    """Download one reel's video to data/reels/<shortcode>/video.mp4."""
    out = reel_dir(shortcode) / "video.mp4"
    if out.exists() and out.stat().st_size > 10_000:
        return out
    with db.connect() as con:
        row = con.execute("SELECT video_url FROM reels WHERE shortcode=?", (shortcode,)).fetchone()

    # 1. Stored CDN link (works if it hasn't expired yet).
    if row and row["video_url"] and _fetch(row["video_url"], out):
        _mark(shortcode)
        return out

    # 2. Fresh link through the logged-in spare account.
    try:
        import instaloader

        from .scrape import loader

        L = loader(require_login=False)
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        if post.video_url and _fetch(post.video_url, out):
            _mark(shortcode)
            return out
    except Exception:
        pass

    # 3. yt-dlp, optionally with cookies from a browser where the spare account is logged in.
    cmd = ["yt-dlp", "-q", "--no-warnings", "-f", "mp4/best", "-o", str(out),
           f"https://www.instagram.com/reel/{shortcode}/"]
    if browser_cookies:
        cmd[1:1] = ["--cookies-from-browser", browser_cookies]
    subprocess.run([_ytdlp(), *cmd[1:]], capture_output=True, text=True)
    if out.exists() and out.stat().st_size > 10_000:
        _mark(shortcode)
        return out
    with db.connect() as con:
        db.set_status(con, shortcode, "failed")
    raise RuntimeError(f"Could not download {shortcode}. Log in with `engine login`, or pass --cookies firefox.")


def _ytdlp() -> str:
    exe = Path(__import__("sys").executable).with_name("yt-dlp.exe")
    return str(exe) if exe.exists() else (shutil.which("yt-dlp") or "yt-dlp")


def _mark(shortcode: str):
    with db.connect() as con:
        con.execute("UPDATE reels SET status='downloaded' WHERE shortcode=? AND status IN ('new','failed')", (shortcode,))


def shortcode_from_url(url: str) -> str | None:
    m = re.search(r"instagram\.com/(?:[^/]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


def add_url(url: str, niche: str, browser_cookies: str | None = None) -> str:
    """Save any reel you come across (Instagram, YouTube Shorts, TikTok) as a reference."""
    sc = shortcode_from_url(url)
    key = sc or "x" + hashlib.sha1(url.encode()).hexdigest()[:10]
    out = reel_dir(key) / "video.mp4"
    args = [_ytdlp(), "--no-warnings", "-f", "mp4/best", "-o", str(out), "--write-info-json",
            "--write-thumbnail", "--convert-thumbnails", "jpg", "-o", f"thumbnail:{reel_dir(key) / 'thumb'}", url]
    if browser_cookies:
        args[1:1] = ["--cookies-from-browser", browser_cookies]
    p = subprocess.run(args, capture_output=True, text=True)
    info_files = list(reel_dir(key).glob("*.info.json"))
    if not out.exists():
        raise RuntimeError(f"yt-dlp could not fetch {url}:\n{p.stderr[-800:]}")
    info = json.loads(info_files[0].read_text(encoding="utf-8")) if info_files else {}
    posted = None
    if info.get("timestamp"):
        posted = datetime.fromtimestamp(info["timestamp"], timezone.utc).isoformat()
    with db.connect() as con:
        db.upsert_reel(con, {
            "shortcode": key, "niche": niche,
            "owner": (info.get("channel") or info.get("uploader_id") or info.get("uploader") or "").lower(),
            "caption": info.get("description") or info.get("title") or "",
            "hashtags": re.findall(r"#(\w+)", info.get("description") or ""),
            "posted_at": posted, "duration": info.get("duration"),
            "views": info.get("view_count"), "likes": info.get("like_count"),
            "comments": info.get("comment_count"), "source": "url",
        })
        db.set_status(con, key, "downloaded")
    for f in info_files:
        f.unlink(missing_ok=True)
    return key


def add_file(path: str, niche: str, name: str | None = None) -> str:
    """Use a video already on your laptop as a reference (or to test the pipeline)."""
    src = Path(path)
    if not src.exists():
        raise SystemExit(f"No file at {src}")
    key = "f" + hashlib.sha1(str(src.resolve()).encode()).hexdigest()[:10]
    shutil.copyfile(src, reel_dir(key) / "video.mp4")
    with db.connect() as con:
        db.upsert_reel(con, {"shortcode": key, "niche": niche, "owner": "local",
                             "caption": name or src.stem, "source": "file",
                             "posted_at": datetime.now(timezone.utc).isoformat()})
        db.set_status(con, key, "downloaded")
    return key
