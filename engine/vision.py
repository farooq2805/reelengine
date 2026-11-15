"""Read key frames with a local vision model through Ollama (default: Qwen3-VL)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import requests

from .config import settings

FRAME_PROMPT = """You are a short-form video editor studying one frame of an Instagram reel.
Describe only what is visible. Reply with JSON only, using exactly these keys:
{
 "shot_type": "talking_head | b_roll | walkthrough | drone | screen_recording | text_card | product | other",
 "framing": "close_up | medium | wide",
 "on_screen_text": "exact words visible on screen, or empty string",
 "caption_style": {
   "present": true or false,
   "position": "top | middle | bottom | none",
   "case": "upper | sentence | mixed | none",
   "font_look": "bold_sans | thin_sans | serif | handwritten | none",
   "text_color": "colour name",
   "highlight_color": "colour of emphasised word, or none",
   "background": "none | box | outline | shadow"
 },
 "graphics": ["arrows, emojis, logos, price tags, progress bar, etc."],
 "setting": "where this is, in a few words",
 "person": "who is on screen and what they are doing, or none"
}"""


def available() -> bool:
    try:
        r = requests.get(settings()["ollama_url"] + "/api/tags", timeout=3)
        return r.ok
    except requests.RequestException:
        return False


def has_model(model: str) -> bool:
    try:
        tags = requests.get(settings()["ollama_url"] + "/api/tags", timeout=3).json().get("models", [])
        return any(t.get("name", "").split(":latest")[0] == model.split(":latest")[0] for t in tags)
    except Exception:
        return False


def read_frame(path: Path, model: str | None = None) -> dict | None:
    s = settings()
    model = model or s["vision_model"]
    img = base64.b64encode(path.read_bytes()).decode()
    try:
        r = requests.post(
            s["ollama_url"] + "/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": FRAME_PROMPT, "images": [img]}],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.1, "num_ctx": 4096, "num_predict": 400},
            },
            timeout=300,
        )
        r.raise_for_status()
        text = r.json().get("message", {}).get("content", "")
        return json.loads(text)
    except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
        return {"error": str(e)[:200]}
