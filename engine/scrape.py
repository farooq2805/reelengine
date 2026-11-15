"""Niche Radar: pull public reels from hashtags and creators with Instaloader.

Uses a spare Instagram account's saved session (see `engine login`). Never your main account.
Goes slowly on purpose: random pauses between requests, caps per creator and per hashtag.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import instaloader
import requests

from . import db
from .config import DATA, load_niche, reel_dir, save_niche, settings


class RateLimited(Exception):
    pass


def session_file(username: str) -> Path:
    return DATA / f"session-{username.lower()}"


def loader(require_login: bool = True) -> instaloader.Instaloader:
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
        max_connection_attempts=1,
        request_timeout=30,
    )
    user = settings().get("ig_username")
    if user and session_file(user).exists():
        L.load_session_from_file(user, str(session_file(user)))
    elif require_login:
        raise SystemExit(
            "No Instagram session yet. Run this once in your own terminal with a SPARE account:\n"
            "  engine login <spare_username>\n"
            "Hashtag scanning needs a login; public creator pages sometimes work without one."
        )
    return L


def login(username: str) -> None:
    """Interactive login: you type the password yourself in your terminal; it is never stored, only the session."""
    L = instaloader.Instaloader(quiet=False)
    L.interactive_login(username)
    L.save_session_to_file(str(session_file(username)))
    from .config import save_settings

    save_settings(ig_username=username)
    print(f"Saved session for @{username}. You can now run: engine scrape <niche>")


def import_firefox_session(username: str) -> None:
    """Alternative to typing a password: log into the spare account in Firefox, then import its cookies."""
    import glob
    import os
    import sqlite3

    pattern = os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\Profiles\*\cookies.sqlite")
    files = glob.glob(pattern)
    if not files:
        raise SystemExit("No Firefox cookies found. Log into the spare account in Firefox first.")
    con = sqlite3.connect(f"file:{files[0]}?immutable=1", uri=True)
    cookies = con.execute("SELECT name, value FROM moz_cookies WHERE baseDomain='instagram.com'").fetchall()
    L = instaloader.Instaloader(quiet=True)
    L.context._session.cookies.update(dict(cookies))
    who = L.test_login()
    if not who:
        raise SystemExit("Firefox is not logged into Instagram.")
    L.context.username = who
    L.save_session_to_file(str(session_file(who)))
    from .config import save_settings

    save_settings(ig_username=who)
    print(f"Imported Firefox session for @{who}.")


def import_chrome_session() -> None:
    """Import Instagram session from Chrome cookies (Windows, DPAPI-encrypted)."""
    import base64
    import json
    import os
    import shutil
    import sqlite3
    import ctypes
    import ctypes.wintypes

    local = os.environ.get("LOCALAPPDATA", "")
    state_path = os.path.join(local, r"Google\Chrome\User Data\Local State")
    cookie_path = os.path.join(local, r"Google\Chrome\User Data\Default\Cookies")
    if not os.path.exists(cookie_path):
        cookie_path = os.path.join(local, r"Google\Chrome\User Data\Default\Network\Cookies")
    if not os.path.exists(cookie_path):
        raise SystemExit("Chrome cookies database not found.")
    if not os.path.exists(state_path):
        raise SystemExit("Chrome Local State not found.")

    with open(state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)
    encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    encrypted_key = encrypted_key[5:]  # strip DPAPI prefix

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = DATA_BLOB(len(encrypted_key), ctypes.create_string_buffer(encrypted_key, len(encrypted_key)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise SystemExit("Failed to decrypt Chrome key via DPAPI.")
    aes_key = ctypes.string_at(blob_out.pbData, blob_out.cbData)

    # Copy the locked Cookies file using robocopy (handles locked files)
    import subprocess, tempfile
    tmp_dir = tempfile.mkdtemp()
    cookie_dir = os.path.dirname(cookie_path)
    cookie_name = os.path.basename(cookie_path)
    subprocess.run(["robocopy", cookie_dir, tmp_dir, cookie_name, "/R:1", "/W:0"],
                   capture_output=True, timeout=10)
    tmp = os.path.join(tmp_dir, cookie_name)
    if not os.path.exists(tmp):
        # Fallback: try immutable SQLite URI
        try:
            con = sqlite3.connect(f"file:{cookie_path}?immutable=1", uri=True)
            rows = con.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%instagram.com'"
            ).fetchall()
            con.close()
        except sqlite3.OperationalError:
            raise SystemExit("Cannot read Chrome cookies (file locked and robocopy failed).")
    else:
        try:
            con = sqlite3.connect(tmp)
            rows = con.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%instagram.com'"
            ).fetchall()
            con.close()
        finally:
            os.remove(tmp)
            os.rmdir(tmp_dir)

    import struct

    bcrypt_dll = ctypes.windll.bcrypt
    MS_PRIMITIVE_PROVIDER = None
    BCRYPT_AES_ALGORITHM = "AES\0".encode("utf-16-le")
    BCRYPT_CHAINING_MODE = "ChainingMode\0".encode("utf-16-le")
    BCRYPT_CHAIN_MODE_GCM = "ChainingModeGCM\0".encode("utf-16-le")
    BCRYPT_AUTH_TAG_LENGTH = "AuthTagLength\0".encode("utf-16-le")

    BCRYPT_INIT_AUTH_MODE_INFO_VERSION = 1
    SIZEOF_BCRYPT_AUTH = 64  # generous

    def _bcrypt_aes_gcm_decrypt(key_bytes, nonce_bytes, ciphertext_and_tag):
        tag = ciphertext_and_tag[-16:]
        ct = ciphertext_and_tag[:-16]
        if not ct:
            return None

        h_alg = ctypes.c_void_p()
        status = bcrypt_dll.BCryptOpenAlgorithmProvider(
            ctypes.byref(h_alg), BCRYPT_AES_ALGORITHM, MS_PRIMITIVE_PROVIDER, 0)
        if status != 0:
            return None

        status = bcrypt_dll.BCryptSetProperty(
            h_alg, BCRYPT_CHAINING_MODE, BCRYPT_CHAIN_MODE_GCM,
            len(BCRYPT_CHAIN_MODE_GCM), 0)
        if status != 0:
            bcrypt_dll.BCryptCloseAlgorithmProvider(h_alg, 0)
            return None

        h_key = ctypes.c_void_p()
        key_buf = ctypes.create_string_buffer(key_bytes)
        status = bcrypt_dll.BCryptGenerateSymmetricKey(
            h_alg, ctypes.byref(h_key), None, 0, key_buf, len(key_bytes), 0)
        if status != 0:
            bcrypt_dll.BCryptCloseAlgorithmProvider(h_alg, 0)
            return None

        nonce_buf = ctypes.create_string_buffer(nonce_bytes, len(nonce_bytes))
        tag_buf = (ctypes.c_ubyte * 16)(*tag)
        ct_buf = ctypes.create_string_buffer(ct, len(ct))
        pt_buf = ctypes.create_string_buffer(len(ct))

        # BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO structure (packed for 64-bit)
        # cbSize(4) + dwInfoVersion(4) + pbNonce(ptr) + cbNonce(4) + pad(4)
        # + pbAuthData(ptr) + cbAuthData(4) + pad(4) + pbTag(ptr) + cbTag(4) + pad(4)
        # + pbMacContext(ptr) + cbMacContext(4) + pad(4) + cbAAD(4) + cbData(8) + dwFlags(4)
        ptr_size = ctypes.sizeof(ctypes.c_void_p)
        if ptr_size == 8:
            auth_info = (ctypes.c_byte * 104)()
            struct.pack_into("II", auth_info, 0, 104, BCRYPT_INIT_AUTH_MODE_INFO_VERSION)
            struct.pack_into("Q", auth_info, 8, ctypes.addressof(nonce_buf))
            struct.pack_into("I", auth_info, 16, len(nonce_bytes))
            # pbAuthData = NULL, cbAuthData = 0 (offsets 24, 32)
            struct.pack_into("Q", auth_info, 40, ctypes.addressof(tag_buf))
            struct.pack_into("I", auth_info, 48, 16)
        else:
            auth_info = (ctypes.c_byte * 56)()
            struct.pack_into("II", auth_info, 0, 56, BCRYPT_INIT_AUTH_MODE_INFO_VERSION)
            struct.pack_into("I", auth_info, 8, ctypes.addressof(nonce_buf))
            struct.pack_into("I", auth_info, 12, len(nonce_bytes))
            struct.pack_into("I", auth_info, 20, ctypes.addressof(tag_buf))
            struct.pack_into("I", auth_info, 24, 16)

        cb_result = ctypes.c_ulong(0)
        status = bcrypt_dll.BCryptDecrypt(
            h_key, ct_buf, len(ct),
            ctypes.byref(auth_info),
            None, 0,
            pt_buf, len(ct),
            ctypes.byref(cb_result), 0)

        bcrypt_dll.BCryptDestroyKey(h_key)
        bcrypt_dll.BCryptCloseAlgorithmProvider(h_alg, 0)

        if status != 0:
            return None
        return bytes(pt_buf[:cb_result.value])

    cookies = {}
    for name, enc_value in rows:
        if enc_value[:3] == b"v10":
            nonce = enc_value[3:15]
            ciphertext = enc_value[15:]
            pt = _bcrypt_aes_gcm_decrypt(aes_key, nonce, ciphertext)
            if pt:
                try:
                    cookies[name] = pt.decode("utf-8")
                except UnicodeDecodeError:
                    pass

    if not cookies:
        raise SystemExit("No Instagram cookies found in Chrome. Make sure you're logged in.")

    L = instaloader.Instaloader(quiet=True)
    L.context._session.cookies.update(cookies)
    who = L.test_login()
    if not who:
        raise SystemExit("Chrome is not logged into Instagram (cookies found but session invalid).")
    L.context.username = who
    L.save_session_to_file(str(session_file(who)))
    from .config import save_settings
    save_settings(ig_username=who)
    print(f"Imported Chrome session for @{who}.")


def import_sessionid(sessionid: str) -> None:
    """Paste-based login: grab the sessionid from Chrome DevTools and pass it here."""
    import urllib.parse
    sessionid = urllib.parse.unquote(sessionid.strip().strip('"').strip("'"))

    # Try a lightweight API call to verify
    s = requests.Session()
    s.cookies.set("sessionid", sessionid, domain=".instagram.com")
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
    })
    who = ""
    try:
        r = s.get("https://i.instagram.com/api/v1/accounts/current_user/", timeout=15)
        if r.status_code == 200:
            who = r.json().get("user", {}).get("username", "")
    except Exception:
        pass

    if not who:
        # Extract user_id from sessionid format "uid:token:part:hash"
        parts = sessionid.split(":")
        uid = parts[0] if parts and parts[0].isdigit() else ""
        if uid:
            try:
                r2 = s.get(f"https://www.instagram.com/api/v1/users/{uid}/info/", timeout=15)
                if r2.status_code == 200:
                    who = r2.json().get("user", {}).get("username", "")
            except Exception:
                pass

    if not who:
        # Rate-limited or blocked — trust the cookie and save with uid as placeholder
        parts = sessionid.split(":")
        uid = parts[0] if parts and parts[0].isdigit() else ""
        if not uid:
            raise SystemExit("Invalid sessionid format. Copy the full value from Chrome DevTools → Application → Cookies → sessionid.")
        who = f"uid_{uid}"
        print(f"Could not verify session (rate-limited), saving with user ID {uid}.")
        print("The session will be verified on the next scrape run.")

    L = instaloader.Instaloader(quiet=True)
    L.context._session.cookies.set("sessionid", sessionid, domain=".instagram.com")
    L.context.username = who
    L.save_session_to_file(str(session_file(who)))
    from .config import save_settings
    save_settings(ig_username=who)
    print(f"Imported session for @{who}.")


def pause():
    s = settings()
    time.sleep(random.uniform(s["pause_min"], s["pause_max"]))


def post_to_row(p: instaloader.Post, niche: str, source: str) -> dict:
    def g(attr):
        try:
            return getattr(p, attr)
        except Exception:
            return None

    return {
        "shortcode": p.shortcode,
        "niche": niche,
        "owner": (g("owner_username") or "").lower(),
        "caption": g("caption") or "",
        "hashtags": g("caption_hashtags") or [],
        "posted_at": p.date_utc.replace(tzinfo=timezone.utc).isoformat(),
        "duration": g("video_duration"),
        "video_url": g("video_url"),
        "thumb_url": g("url"),
        "views": g("video_view_count"),
        "plays": g("video_play_count"),
        "likes": g("likes"),
        "comments": g("comments"),
        "source": source,
    }


def save_thumb(shortcode: str, url: str | None) -> None:
    if not url:
        return
    path = reel_dir(shortcode) / "thumb.jpg"
    if path.exists():
        return
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.ok and r.content:
            path.write_bytes(r.content)
    except requests.RequestException:
        pass


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (instaloader.exceptions.TooManyRequestsException,) as e:
        raise RateLimited(str(e))
    except instaloader.exceptions.ConnectionException as e:
        if "429" in str(e) or "wait a few minutes" in str(e).lower():
            raise RateLimited(str(e))
        raise


def scan_posts(posts, niche: str, source: str, cutoff: datetime, limit: int, con, stats: dict):
    """Walk a feed of posts, keep video reels newer than cutoff."""
    old_in_a_row = 0
    kept = 0
    for p in posts:
        if kept >= limit:
            break
        posted = p.date_utc.replace(tzinfo=timezone.utc)
        if posted < cutoff:
            # Pinned posts can be old; stop only after several old ones in a row.
            old_in_a_row += 1
            if old_in_a_row >= 4:
                break
            continue
        old_in_a_row = 0
        if not p.is_video:
            continue
        row = post_to_row(p, niche, source)
        is_new = db.upsert_reel(con, row)
        save_thumb(row["shortcode"], row["thumb_url"])
        stats["new" if is_new else "updated"] += 1
        kept += 1
    return kept


def scrape(slug: str, hashtags: bool = True, creators: bool = True, only: list[str] | None = None) -> dict:
    niche = load_niche(slug)
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(niche["days_back"]))
    stats = {"new": 0, "updated": 0, "errors": [], "rate_limited": False}
    L = loader(require_login=hashtags)

    with db.connect() as con:
        users = list(niche["creators"])
        if niche.get("self_username"):
            users.append(niche["self_username"])
            db.add_creator(con, niche["self_username"], slug, "self", is_self=True)
        for u in con.execute("SELECT username FROM creators WHERE niche=?", (slug,)):
            if u["username"] not in users:
                users.append(u["username"])
        if only:
            users = [u for u in users if u in only]

        try:
            if hashtags and not only:
                for tag in niche["hashtags"]:
                    print(f"#{tag} ...", flush=True)
                    try:
                        h = _guard(instaloader.Hashtag.from_name, L.context, tag)
                        n = _guard(scan_posts, h.get_top_posts(), slug, f"hashtag:{tag}", cutoff,
                                   niche["max_reels_per_hashtag"] // 2, con, stats)
                        n += _guard(scan_posts, h.get_posts_resumable(), slug, f"hashtag:{tag}", cutoff,
                                    niche["max_reels_per_hashtag"] // 2, con, stats)
                        print(f"  {n} reels", flush=True)
                    except RateLimited:
                        raise
                    except Exception as e:  # keep going on one bad hashtag
                        stats["errors"].append(f"#{tag}: {e}")
                        print(f"  skipped: {e}", flush=True)
                    con.commit()
                    pause()

            if creators:
                for u in users:
                    print(f"@{u} ...", flush=True)
                    try:
                        prof = _guard(instaloader.Profile.from_username, L.context, u)
                        db.add_creator(con, u, slug, "recipe", followers=prof.followers,
                                       is_self=(u == niche.get("self_username")))
                        feed = prof.get_reels() if hasattr(prof, "get_reels") else prof.get_posts()
                        n = _guard(scan_posts, feed, slug, f"creator:{u}", cutoff,
                                   niche["max_reels_per_creator"], con, stats)
                        print(f"  {n} reels", flush=True)
                    except RateLimited:
                        raise
                    except Exception as e:
                        stats["errors"].append(f"@{u}: {e}")
                        print(f"  skipped: {e}", flush=True)
                    con.commit()
                    pause()
        except RateLimited as e:
            stats["rate_limited"] = True
            stats["errors"].append(f"Instagram asked us to slow down ({e}). Stopped early; try again in a few hours.")
    return stats


def discover(slug: str, min_reels: int = 1, max_new: int = 25) -> list[str]:
    """Add creators who appear in the niche's hashtag reels, best performers first."""
    niche = load_niche(slug)
    with db.connect() as con:
        rows = con.execute(
            """SELECT owner, COUNT(*) n, MAX(COALESCE(plays, views, 0)) best
               FROM reels WHERE niche=? AND source LIKE 'hashtag:%' AND owner != ''
               GROUP BY owner HAVING n >= ? ORDER BY best DESC""",
            (slug, min_reels),
        ).fetchall()
        known = set(niche["creators"]) | {niche.get("self_username") or ""}
        added = []
        for r in rows:
            if r["owner"] in known:
                continue
            db.add_creator(con, r["owner"], slug, "discovered")
            added.append(r["owner"])
            if len(added) >= max_new:
                break
    if added:
        niche["creators"] = sorted(set(niche["creators"]) | set(added))
        save_niche(slug, niche)
    return added
