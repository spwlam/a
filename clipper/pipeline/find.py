"""Step 2: find the moments worth clipping.

Scores each half-second of audio by how much louder it is than the
surrounding minute (streamer yelling, explosions, chat-worthy reactions),
then transcribes the best windows and boosts the ones where the streamer
says reaction words ("no way", "let's go", ...).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .common import log, probe_duration, run

HOP = 0.5          # seconds per loudness sample
RATE = 4000        # audio sample rate used for loudness analysis

DEFAULT_KEYWORDS = [
    "no way", "let's go", "lets go", "oh my god", "what the", "bro", "wait",
    "are you serious", "insane", "holy", "clutch", "he did it", "i did it",
    "no no no", "run", "get out", "yes", "what just happened",
]

_whisper = None
_whisper_failed = False


def loudness_curve(path: Path) -> np.ndarray:
    """Return RMS loudness in dB per HOP seconds, streamed so long VODs fit in memory."""
    block = int(RATE * HOP)
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE),
         "-f", "s16le", "-"],
        stdout=subprocess.PIPE,
    )
    out = []
    while True:
        buf = proc.stdout.read(block * 2)
        if not buf:
            break
        x = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
        out.append(20 * np.log10(max(rms, 1e-5)))
    proc.wait()
    return np.array(out, dtype=np.float32)


def excitement(db: np.ndarray, baseline_s: float = 60.0) -> np.ndarray:
    """dB above the local (rolling-median) baseline, lightly smoothed."""
    n = len(db)
    half = int(baseline_s / HOP / 2)
    base = np.empty(n, dtype=np.float32)
    for i in range(n):
        base[i] = np.median(db[max(0, i - half): i + half + 1])
    ex = db - base
    k = np.ones(3, dtype=np.float32) / 3
    return np.convolve(ex, k, mode="same")


def pick_peaks(ex: np.ndarray, count: int, min_gap_s: float, threshold_db: float) -> list[int]:
    order = np.argsort(ex)[::-1]
    gap = int(min_gap_s / HOP)
    picked: list[int] = []
    for i in order:
        if ex[i] < threshold_db or len(picked) >= count:
            break
        if all(abs(i - p) >= gap for p in picked):
            picked.append(int(i))
    return picked


def _get_whisper(model_name: str):
    global _whisper, _whisper_failed
    if _whisper is None and not _whisper_failed:
        try:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(model_name, device="auto", compute_type="int8")
        except Exception as exc:  # model download blocked, no package, etc.
            _whisper_failed = True
            log(f"WARNING: speech-to-text unavailable ({type(exc).__name__}). "
                "Clips will render WITHOUT captions until this works.")
    return _whisper


def transcribe_window(video: Path, start: float, end: float, model_name: str) -> list[dict] | None:
    """Words with times relative to the source video. None if whisper is unavailable."""
    model = _get_whisper(model_name)
    if model is None:
        return None
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
             "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        segments, _ = model.transcribe(str(wav), language="en", word_timestamps=True,
                                       vad_filter=True)
        words = []
        for seg in segments:
            for w in seg.words or []:
                words.append({"start": round(start + w.start, 2), "end": round(start + w.end, 2),
                              "text": w.word.strip()})
    return words


def keyword_hits(words: list[dict], keywords: list[str]) -> list[str]:
    text = " ".join(w["text"].lower().strip(".,!?") for w in words)
    return [k for k in keywords if k in text]


def find_clips(cfg: dict, state: dict, campaigns: dict) -> int:
    fcfg = cfg["find"]
    per_video = int(fcfg.get("clips_per_video", 6))
    threshold = float(fcfg.get("min_excitement_db", 6.0))
    pre_roll = float(fcfg.get("pre_roll_seconds", 10))
    post_roll = float(fcfg.get("post_roll_seconds", 5))
    keywords = [k.lower() for k in fcfg.get("keywords", DEFAULT_KEYWORDS)]
    model_name = cfg["captions"].get("whisper_model", "base.en")

    made = 0
    for vid, v in state["videos"].items():
        if v.get("analyzed"):
            continue
        camp = campaigns.get(v["campaign"], {})
        min_s = float(camp.get("min_seconds", 15))
        max_s = float(camp.get("max_seconds", 60))
        cold = float(cfg["output"].get("cold_open_seconds", 2.0))
        main_max = max_s - cold  # the cold open counts toward the platform/campaign length

        path = Path(v["path"])
        dur = probe_duration(path)
        log(f"analyze {vid} ({dur/60:.1f} min)")
        db = loudness_curve(path)
        if len(db) == 0:
            v["analyzed"] = True
            continue
        ex = excitement(db)

        if dur <= max_s + 10:
            # Already a short clip (e.g. a Twitch clip): one candidate, find its peak.
            peaks = [int(np.argmax(ex))]
        else:
            peaks = pick_peaks(ex, per_video * 2, min_gap_s=main_max, threshold_db=threshold)

        cands = []
        for p in peaks:
            peak_t = p * HOP
            if dur <= max_s + 10:
                start, end = 0.0, min(dur, main_max)
            else:
                start = max(0.0, peak_t - pre_roll)
                end = min(dur, peak_t + post_roll)
                if end - start < min_s:  # stretch the build-up to reach the minimum
                    start = max(0.0, end - min_s)
                if end - start > main_max:
                    start = end - main_max
            words = transcribe_window(path, start, end, model_name)
            hits = keyword_hits(words or [], keywords)
            score = float(ex[p]) + 3.0 * len(hits)
            cands.append({"start": round(start, 2), "end": round(end, 2), "peak": round(peak_t, 2),
                          "score": round(score, 2), "loudness_db": round(float(ex[p]), 2),
                          "keywords": hits, "words": words})

        cands.sort(key=lambda c: c["score"], reverse=True)
        for i, c in enumerate(cands[:per_video]):
            cid = f"{vid}-{int(c['peak'])}"
            state["clips"][cid] = {
                "video": vid, "handle": v["handle"], "campaign": v["campaign"],
                "source_url": v.get("url", ""), "status": "candidate", "verdicts": [], **c,
            }
            made += 1
        v["analyzed"] = True
    log(f"find done: {made} candidate clip(s)")
    return made
