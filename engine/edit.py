"""Edit Engine: raw clips + a Style Card -> Remotion props -> rendered 9:16 reel.

`prepare` transcribes your clips, trims silences and builds a first-cut timeline
(clips + word timings + style). Claude Code then reviews the draft (drops flubs and
repeated takes) and `render` produces the MP4 with Remotion.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .analyze import extract_audio, probe, transcribe
from .config import CARDS, EDITS, REELS, ROOT

EDIT = ROOT / "edit"
PUBLIC = EDIT / "public"
PROPS = EDIT / "props"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")[:40] or "edit"


def load_card(ref: str | None) -> dict:
    """A reel's Style Card by shortcode, or a house style by file name in data/cards."""
    if not ref:
        return {}
    for p in (REELS / ref / "stylecard.json", CARDS / ref, CARDS / f"{ref}.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise SystemExit(f"No Style Card found for '{ref}'.")


def style_from_card(card: dict) -> dict:
    cap = dict(card.get("captions") or {})
    pace = card.get("pacing") or {}
    return {
        "captions": {k: cap[k] for k in ("style", "words_per_chunk", "position", "font", "weight", "size_pct", "case",
                                          "color", "highlight_color", "background", "box_color", "stroke", "pop_in")
                     if k in cap},
        "pacing": {"zoom_on_cut": pace.get("zoom_on_cut", True), "punch_in_pct": pace.get("punch_in_pct", 8),
                   "slow_push": pace.get("slow_push", False)},
        "colour": card.get("colour_edit") or {},
    }


def speech_segments(words: list[dict], duration: float, pad: float = 0.12, gap: float = 0.4) -> list[tuple[float, float]]:
    """Keep the spoken parts, cut pauses longer than `gap` seconds."""
    if not words:
        return [(0.0, duration)]
    segs = []
    s, e = words[0]["start"], words[0]["end"]
    for w in words[1:]:
        if w["start"] - e > gap:
            segs.append((s, e))
            s = w["start"]
        e = w["end"]
    segs.append((s, e))
    return [(max(a - pad, 0), min(b + pad, duration)) for a, b in segs if b - a > 0.25]


def prepare(name: str, clips: list[str], card_ref: str | None, keep_pauses: bool = False, log=print) -> Path:
    name = slug(name)
    pub = PUBLIC / name
    pub.mkdir(parents=True, exist_ok=True)
    PROPS.mkdir(parents=True, exist_ok=True)
    timeline, words_out, takes = [], [], []
    t_final = 0.0
    for i, src in enumerate(clips):
        srcp = Path(src)
        if not srcp.exists():
            raise SystemExit(f"No clip at {srcp}")
        dest = pub / f"clip{i:02d}{srcp.suffix.lower()}"
        shutil.copyfile(srcp, dest)
        meta = probe(dest)
        log(f"[{i + 1}/{len(clips)}] {srcp.name}: {meta['duration']:.1f}s, transcribing ...")
        wav = pub / f"clip{i:02d}.wav"
        extract_audio(dest, wav)
        tr = transcribe(wav)
        wav.unlink(missing_ok=True)
        takes.append({"clip": i, "file": srcp.name, "text": tr["text"], "segments": tr["segments"]})
        segs = [(0.0, meta["duration"])] if keep_pauses else speech_segments(tr["words"], meta["duration"])
        for a, b in segs:
            timeline.append({"src": f"{name}/{dest.name}", "in": round(a, 2), "out": round(b, 2),
                             "label": f"clip{i:02d} {a:.1f}-{b:.1f}"})
            for w in tr["words"]:
                if w["start"] >= a and w["end"] <= b + 0.05:
                    words_out.append({"start": round(t_final + w["start"] - a, 2),
                                      "end": round(t_final + w["end"] - a, 2), "word": w["word"]})
            t_final += b - a
    card = load_card(card_ref)
    props = {"fps": 30, "clips": timeline, "words": words_out, "style": style_from_card(card)}
    if card.get("hook", {}).get("title_overlay"):
        props["style"]["hook_title"] = {"text": card["hook"]["title_overlay"], "seconds": 2.5}
    out = PROPS / f"{name}.json"
    out.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")
    (PROPS / f"{name}.takes.json").write_text(json.dumps(takes, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"\nFirst cut: {len(timeline)} pieces, {t_final:.1f}s. Props: {out}")
    log("Review it in Claude Code (drop flubs and repeated takes), then: engine render " + name)
    return out


def render(name: str, log=print) -> Path:
    name = slug(name)
    props = PROPS / f"{name}.json"
    if not props.exists():
        raise SystemExit(f"No props at {props}. Run engine edit first.")
    if not (EDIT / "node_modules").exists():
        raise SystemExit("Remotion is not installed yet. Run: cd edit && npm install")
    EDITS.mkdir(parents=True, exist_ok=True)
    out = EDITS / f"{name}.mp4"
    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    cmd = [npx, "remotion", "render", "src/index.ts", "StyleReel", str(out), f"--props={props}", "--log=warn"]
    # Use the installed Chrome/Edge: Remotion's own headless Chrome breaks in deep folders (Windows path limit).
    for exe in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(exe).exists():
            cmd.append(f"--browser-executable={exe}")
            break
    # Remotion's compositor .exe can sit past Windows' 260-character path limit in deep folders.
    # Copy it next to the Python environment (short path) and point Remotion there.
    comp = EDIT / "node_modules" / "@remotion" / "compositor-win32-x64-msvc"
    if len(str(comp / "remotion.exe")) > 240:
        import sys

        comp = Path("\\\\?\\" + str(comp.resolve()))  # long-path prefix so Python can read it
    if comp.exists() and len(str(comp / "remotion.exe")) > 240:
        bins = Path(sys.executable).resolve().parents[2] / "remotion-bin"
        version = json.loads((comp / "package.json").read_text(encoding="utf-8")).get("version")
        stamp = bins / "VERSION"
        if not stamp.exists() or stamp.read_text().strip() != version:
            shutil.rmtree(bins, ignore_errors=True)
            shutil.copytree(comp, bins)
            stamp.write_text(version or "")
        cmd.append(f"--binaries-directory={bins}")
    log("Rendering ...")
    p = subprocess.run(cmd, cwd=EDIT)
    if p.returncode != 0 or not out.exists():
        raise SystemExit("Render failed (see the output above).")
    log(f"Done: {out}")
    return out
