"""Design Language Decoder: turn one reel's video into analysis.json.

Steps: probe -> audio -> Whisper transcript -> PySceneDetect cuts -> key frames
-> colour palette -> loudness curve -> (optional) Qwen3-VL frame reading -> metrics.
Everything runs locally and free.
"""
from __future__ import annotations

import json
import subprocess
import time
import wave
from pathlib import Path

import numpy as np

from . import db, vision
from .config import reel_dir, settings

_whisper = None


def _run(args: list[str]) -> str:
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {p.stderr[-500:]}")
    return p.stdout


def probe(video: Path) -> dict:
    out = json.loads(_run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(video)]))
    v = next((s for s in out["streams"] if s["codec_type"] == "video"), {})
    num, _, den = (v.get("avg_frame_rate") or "30/1").partition("/")
    return {
        "duration": float(out["format"].get("duration", 0)),
        "width": int(v.get("width", 0)),
        "height": int(v.get("height", 0)),
        "fps": round(float(num) / float(den or 1), 2) if float(den or 1) else 30.0,
        "has_audio": any(s["codec_type"] == "audio" for s in out["streams"]),
    }


def extract_audio(video: Path, wav: Path) -> None:
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", str(wav)])


def _load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        size = settings()["whisper_model"]
        try:  # GPU if the CUDA libraries are present, else CPU.
            _whisper = WhisperModel(size, device="cuda", compute_type="int8_float16")
            _whisper.transcribe(np.zeros(16000, dtype=np.float32))  # fail fast if CUDA DLLs are missing
        except Exception:
            _whisper = WhisperModel(size, device="cpu", compute_type="int8")
    return _whisper


def transcribe(wav: Path) -> dict:
    model = _load_whisper()
    # Pass samples, not a path: avoids faster-whisper's PyAV decoder (version clashes on Windows).
    with wave.open(str(wav), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    segs, info = model.transcribe(audio, word_timestamps=True, vad_filter=True, beam_size=5)
    segments, words = [], []
    for s in segs:
        segments.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        for w in s.words or []:
            words.append({"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()})
    return {"language": info.language, "language_probability": round(info.language_probability, 2),
            "text": " ".join(s["text"] for s in segments), "segments": segments, "words": words}


def detect_cuts(video: Path, duration: float) -> list[dict]:
    from scenedetect import ContentDetector, detect

    scenes = detect(str(video), ContentDetector(threshold=27.0, min_scene_len=8))
    shots = [{"start": round(a.get_seconds(), 2), "end": round(b.get_seconds(), 2)} for a, b in scenes]
    if not shots:
        shots = [{"start": 0.0, "end": round(duration, 2)}]
    for s in shots:
        s["length"] = round(s["end"] - s["start"], 2)
    return shots


def grab_frames(video: Path, shots: list[dict], out_dir: Path, max_frames: int = 10) -> list[dict]:
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    picks = shots if len(shots) <= max_frames else [shots[round(i * (len(shots) - 1) / (max_frames - 1))] for i in range(max_frames)]
    times = [0.4] + [round((s["start"] + s["end"]) / 2, 2) for s in picks]
    frames, seen = [], set()
    for i, t in enumerate(times):
        key = round(t, 1)
        if key in seen:
            continue
        seen.add(key)
        path = out_dir / f"{i:02d}.jpg"
        _run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
              "-vf", "scale=540:-2", "-q:v", "3", str(path)])
        if path.exists():
            frames.append({"t": t, "file": f"frames/{path.name}", "hook": i == 0})
    return frames


def colour_profile(frame_paths: list[Path]) -> dict:
    import cv2

    pixels, stats = [], []
    for p in frame_paths:
        img = cv2.imread(str(p))
        if img is None:
            continue
        small = cv2.resize(img, (96, 170))
        pixels.append(small.reshape(-1, 3))
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
        b, g, r = [small[:, :, i].mean() for i in range(3)]
        stats.append({"brightness": hsv[:, :, 2].mean() / 255, "saturation": hsv[:, :, 1].mean() / 255,
                      "contrast": lab[:, :, 0].std() / 128, "warmth": (r - b) / 255})
    if not pixels:
        return {}
    data = np.vstack(pixels).astype(np.float32)
    k = 6
    _, labels, centers = cv2.kmeans(data, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
                                    3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    palette = [{"hex": "#{:02x}{:02x}{:02x}".format(int(centers[i][2]), int(centers[i][1]), int(centers[i][0])),
                "share": round(float(counts[i] / counts.sum()), 3)} for i in order]
    avg = {key: round(float(np.mean([s[key] for s in stats])), 3) for key in stats[0]}
    avg["grade"] = ("warm" if avg["warmth"] > 0.04 else "cool" if avg["warmth"] < -0.04 else "neutral") + \
                   (", bright" if avg["brightness"] > 0.6 else ", dark" if avg["brightness"] < 0.35 else "") + \
                   (", punchy" if avg["saturation"] > 0.45 else ", muted" if avg["saturation"] < 0.2 else "")
    return {"palette": palette, **avg}


def loudness(wav: Path, step: float = 0.5) -> dict:
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = int(sr * step)
    if len(x) < n:
        return {"step": step, "rms_db": [], "silence_ratio": 1.0}
    frames = x[: len(x) // n * n].reshape(-1, n)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    db_ = 20 * np.log10(rms)
    return {"step": step, "rms_db": [round(float(v), 1) for v in db_],
            "silence_ratio": round(float((db_ < -40).mean()), 3), "mean_db": round(float(db_.mean()), 1)}


def metrics(meta: dict, transcript: dict, shots: list[dict], audio: dict) -> dict:
    dur = meta["duration"] or 1
    words = transcript.get("words", [])
    hook_words = [w["word"] for w in words if w["start"] < 3.0]
    speech_time = sum(max(w["end"] - w["start"], 0) for w in words)
    lengths = [s["length"] for s in shots]
    return {
        "duration": round(dur, 2),
        "shots": len(shots),
        "cuts_per_10s": round((len(shots) - 1) / dur * 10, 2),
        "avg_shot_seconds": round(float(np.mean(lengths)), 2) if lengths else None,
        "first_cut_at": shots[1]["start"] if len(shots) > 1 else None,
        "words_per_minute": round(len(words) / dur * 60, 1),
        "speech_ratio": round(speech_time / dur, 2),
        "hook_text": " ".join(hook_words),
        "first_line": (transcript.get("segments") or [{"text": ""}])[0]["text"],
        "silence_ratio": audio.get("silence_ratio"),
    }


def analyze(shortcode: str, use_vision: bool = True, max_frames: int = 10, log=print) -> dict:
    d = reel_dir(shortcode)
    video = d / "video.mp4"
    if not video.exists():
        from .media import download

        log("  downloading ...")
        download(shortcode)
    t0 = time.time()
    meta = probe(video)
    log(f"  {meta['duration']:.0f}s video, {meta['width']}x{meta['height']}")

    wav = d / "audio.wav"
    transcript = {"language": None, "text": "", "segments": [], "words": []}
    audio = {"rms_db": [], "silence_ratio": None}
    if meta["has_audio"]:
        extract_audio(video, wav)
        log("  transcribing ...")
        transcript = transcribe(wav)
        audio = loudness(wav)
        wav.unlink(missing_ok=True)

    log("  finding cuts ...")
    shots = detect_cuts(video, meta["duration"])
    frames = grab_frames(video, shots, d / "frames", max_frames=max_frames)
    colours = colour_profile([d / f["file"] for f in frames])

    vision_notes = None
    if use_vision and vision.available():
        model = settings()["vision_model"]
        if vision.has_model(model):
            log(f"  reading {len(frames)} frames with {model} ...")
            for f in frames:
                f["vision"] = vision.read_frame(d / f["file"], model)
            vision_notes = model
        else:
            log(f"  vision skipped: run `ollama pull {model}` first")
    elif use_vision:
        log("  vision skipped: Ollama is not running")

    result = {
        "shortcode": shortcode,
        "analyzed_at": db.now(),
        "seconds_taken": None,
        "video": meta,
        "metrics": metrics(meta, transcript, shots, audio),
        "transcript": transcript,
        "shots": shots,
        "frames": frames,
        "colour": colours,
        "audio": audio,
        "vision_model": vision_notes,
    }
    result["seconds_taken"] = round(time.time() - t0, 1)
    (d / "analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    with db.connect() as con:
        db.set_status(con, shortcode, "analyzed")
    log(f"  done in {result['seconds_taken']}s")
    return result


def queue(niche: str, window_days: int = 7, top: int = 20, min_outlier: float | None = None) -> list[str]:
    """Pick the top reels that have no analysis yet."""
    from .score import leaderboard

    rows = leaderboard(niche, window_days=window_days, sort="outlier", limit=500)
    picks = []
    for r in rows:
        if r["has_analysis"] or r["status"] == "failed":
            continue
        if min_outlier and (r["outlier"] or 0) < min_outlier:
            continue
        picks.append(r["shortcode"])
        if len(picks) >= top:
            break
    return picks
