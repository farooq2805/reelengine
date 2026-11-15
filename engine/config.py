"""Paths and settings shared by every part of the engine."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("REELENGINE_DATA", ROOT / "data"))
REELS = DATA / "reels"          # one folder per reel: video, frames, analysis, style card
SCRIPTS = DATA / "scripts"      # scripts written by the Script Studio skill
CARDS = DATA / "cards"          # house styles merged from several Style Cards
EDITS = DATA / "edits"          # edit projects and renders
REPORTS = DATA / "reports"      # weekly research reports
DB_PATH = DATA / "engine.db"
NICHES = ROOT / "niches"
SETTINGS_PATH = DATA / "settings.json"

DEFAULT_SETTINGS = {
    # Spare Instagram account used for scraping (never your main one).
    "ig_username": "",
    # Whisper model: tiny, base, small, medium, large-v3. "small" is a good speed/quality balance on CPU.
    "whisper_model": "small",
    # Ollama vision model for reading frames. The 2B *instruct* build answers directly and fits a 4 GB card.
    # (Plain qwen3-vl tags "think" first and can return empty answers.) With 8 GB+ VRAM try qwen3-vl:8b-instruct.
    "vision_model": "qwen3-vl:2b-instruct",
    "ollama_url": "http://127.0.0.1:11434",
    # Seconds to wait between Instagram requests (random between the two numbers).
    "pause_min": 4,
    "pause_max": 9,
}


def ensure_dirs() -> None:
    for p in (DATA, REELS, SCRIPTS, CARDS, EDITS, REPORTS):
        p.mkdir(parents=True, exist_ok=True)


def settings() -> dict:
    ensure_dirs()
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    return s


def save_settings(**changes) -> dict:
    s = settings()
    s.update({k: v for k, v in changes.items() if v is not None})
    SETTINGS_PATH.write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s


def load_niche(slug: str) -> dict:
    path = NICHES / f"{slug}.yaml"
    if not path.exists():
        raise SystemExit(f"No niche recipe at {path}. Available: {', '.join(list_niches()) or 'none'}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("slug", slug)
    data.setdefault("hashtags", [])
    data.setdefault("creators", [])
    data.setdefault("days_back", 30)
    data.setdefault("max_reels_per_creator", 30)
    data.setdefault("max_reels_per_hashtag", 60)
    data.setdefault("outlier_threshold", 3.0)
    data["creators"] = data["creators"] or []
    return data


def save_niche(slug: str, data: dict) -> None:
    path = NICHES / f"{slug}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def list_niches() -> list[str]:
    return sorted(p.stem for p in NICHES.glob("*.yaml"))


def reel_dir(shortcode: str) -> Path:
    d = REELS / shortcode
    d.mkdir(parents=True, exist_ok=True)
    return d
