"""Step 3: render vertical 9:16 clips.

Layout: facecam on top, gameplay below (or a full-height gameplay crop if the
streamer has no facecam). The clip opens on the payoff (a short cold open of
the peak moment), then plays the build-up. Word-by-word captions sit on the
seam between facecam and gameplay, clear of the TikTok/Shorts/Reels buttons.
"""
from __future__ import annotations

from pathlib import Path

from .common import OUT, WORK, find_streamer, log, probe_duration, run

YELLOW = r"{\c&H00E6FF&}"   # ASS colours are BGR
WHITE = r"{\c&HFFFFFF&}"


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\\", "/").replace("\n", "\\N")


def _clean(word: str) -> str:
    return word.replace("{", "").replace("}", "").replace("\\", "").upper()


def _chunks(words: list[dict], max_words: int):
    chunk: list[dict] = []
    for w in words:
        if chunk and (len(chunk) >= max_words or w["start"] - chunk[-1]["end"] > 0.6):
            yield chunk
            chunk = []
        chunk.append(w)
        if w["text"].endswith((".", "!", "?")):
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def build_ass(words_out: list[dict], total: float, W: int, H: int, cap_y: int,
              handle: str, ccfg: dict, tag_y: int, title_y: int,
              hook_text: str = "", cta_text: str = "") -> str:
    font = ccfg.get("font", "DejaVu Sans")
    size = int(ccfg.get("font_size", 84))
    max_words = int(ccfg.get("words_per_line", 3))
    tag = ccfg.get("tag_format", "@{handle}").format(handle=handle)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,"
        "100,100,1,0,1,7,3,5,60,60,0,1",
        f"Style: Tag,{font},40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,"
        "100,100,0,0,1,3,1,1,40,40,0,1",
        f"Style: Title,{font},62,&H00FFFFFF,&H00FFFFFF,&H00000000,&HC0000000,-1,0,0,0,"
        "100,100,0,0,3,14,0,5,90,90,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,{_ass_time(0)},{_ass_time(total)},Tag,,0,0,0,,{{\\pos(40,{tag_y})}}{tag}",
    ]
    # Hook title for the first seconds, call-to-action for the last seconds (same slot).
    hook_end = min(3.5, total / 2)
    if hook_text:
        lines.append(f"Dialogue: 2,{_ass_time(0)},{_ass_time(hook_end)},Title,,0,0,0,,"
                     f"{{\\pos({W // 2},{title_y})}}{_esc(hook_text)}")
    if cta_text:
        lines.append(f"Dialogue: 2,{_ass_time(max(hook_end, total - 3.0))},{_ass_time(total)},"
                     f"Title,,0,0,0,,{{\\pos({W // 2},{title_y})\\fad(150,0)}}{_esc(cta_text)}")
    for chunk in _chunks(words_out, max_words):
        for i, w in enumerate(chunk):
            start = w["start"]
            end = chunk[i + 1]["start"] if i + 1 < len(chunk) else w["end"] + 0.15
            text = " ".join(
                (YELLOW if j == i else WHITE) + _clean(x["text"]) for j, x in enumerate(chunk)
            )
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,"
                         f"{{\\pos({W // 2},{cap_y})\\fad(40,0)}}{text}")
    return "\n".join(lines) + "\n"


def _crop(box: dict | None) -> str:
    if not box:
        return ""
    return (f"crop=w=iw*{box['w']}:h=ih*{box['h']}:x=iw*{box.get('x', 0)}:"
            f"y=ih*{box.get('y', 0)},")


def _cover(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def _download_section(url: str, start: float, end: float, dest: Path, max_height: int) -> Path:
    """Download only [start, end] of a long VOD instead of the whole stream."""
    import yt_dlp

    dest.parent.mkdir(parents=True, exist_ok=True)
    for old in dest.parent.glob(dest.stem + ".*"):
        old.unlink()
    opts = {
        "outtmpl": str(dest.with_suffix(".%(ext)s")),
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b",
        "merge_output_format": "mp4",
        "download_ranges": yt_dlp.utils.download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "quiet": True, "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    files = [f for f in dest.parent.glob(dest.stem + ".*") if f.suffix in (".mp4", ".mkv", ".webm")]
    if not files:
        raise RuntimeError(f"section download failed for {url} [{start:.0f}s-{end:.0f}s]")
    return files[0]


def render_clip(cfg: dict, cid: str, clip: dict, video: dict) -> Path:
    ocfg = cfg["output"]
    W, H = int(ocfg.get("width", 1080)), int(ocfg.get("height", 1920))
    camp, st = find_streamer(cfg, clip["campaign"], clip["handle"])
    layout = st.get("layout", "stack" if st.get("facecam") else "crop")
    facecam = st.get("facecam") if layout == "stack" else None
    gameplay = st.get("gameplay")

    s, e, peak = clip["start"], clip["end"], clip["peak"]
    cold = float(clip.get("cold_open_seconds", ocfg.get("cold_open_seconds", 2.0)))
    hs, he = max(0.0, peak - 0.3), peak - 0.3 + cold
    base = min(s, hs) if cold > 0 else s
    span = (max(e, he) if cold > 0 else e) - base

    # Captions on the output timeline (cold open words first, then the main clip).
    words = clip.get("words") or []
    out_words = []
    if cold > 0:
        out_words += [{**w, "start": w["start"] - hs, "end": min(w["end"], he) - hs}
                      for w in words if hs <= w["start"] < he]
    out_words += [{**w, "start": w["start"] - s + (cold if cold > 0 else 0),
                   "end": w["end"] - s + (cold if cold > 0 else 0)}
                  for w in words if s <= w["start"] < e]
    total = (cold if cold > 0 else 0) + (e - s)

    face_h = (int(H * float(ocfg.get("facecam_height_ratio", 0.38))) // 2 * 2) if facecam else 0
    frame_h = (W * 9 // 16) // 2 * 2            # height of the full 16:9 frame in "full" layout
    frame_y = (H - frame_h) // 2 // 2 * 2
    if layout == "full":
        cap_y, tag_y, title_y = frame_y + frame_h + 120, frame_y + frame_h + 10, frame_y - 170
    elif layout == "stack":
        cap_y, tag_y, title_y = face_h, face_h - 70, int(H * 0.12)
    else:
        cap_y, tag_y, title_y = int(H * 0.60), int(H * 0.60) - 110, int(H * 0.12)

    tmp = WORK / "ass"
    tmp.mkdir(parents=True, exist_ok=True)
    ass_name = f"{cid}.ass"
    (tmp / ass_name).write_text(build_ass(
        out_words, total, W, H, cap_y, clip["handle"], cfg["captions"], tag_y, title_y,
        hook_text=clip.get("hook_text", ""), cta_text=camp.get("cta_text", "")))

    # Long VODs are fetched as audio only; grab just the video section we need now.
    src = Path(video["path"]).resolve()
    if video.get("audio_only"):
        src = _download_section(video["url"], base, base + span, WORK / "sections" / cid,
                                int(cfg["fetch"].get("max_height", 1080)))
        seek = 0.0
    else:
        seek = base

    def seg(a: float, b: float, tag: str) -> str:
        a, b = a - base, b - base
        return (f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[{tag}v];"
                f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[{tag}a];")

    fc = ""
    if cold > 0:
        fc += seg(hs, he, "h") + seg(s, e, "m")
        fc += "[hv][ha][mv][ma]concat=n=2:v=1:a=1[cv][ca];"
    else:
        fc += seg(s, e, "m") + "[mv]null[cv];[ma]anull[ca];"
    fc += "[cv]fps=30,"
    if layout == "full":
        # Whole stream frame (keeps the streamer's overlay) over a blurred, zoomed copy.
        fc += "split[a][b];"
        fc += f"[a]{_cover(W, H)},boxblur=30:2,eq=brightness=-0.15[bg];"
        fc += f"[b]{_crop(gameplay)}scale={W}:{frame_h},setsar=1[fg];"
        fc += f"[bg][fg]overlay=0:{frame_y}[st];[st]"
    elif facecam:
        fc += "split[a][b];"
        fc += f"[a]{_crop(facecam)}{_cover(W, face_h)}[f];"
        fc += f"[b]{_crop(gameplay)}{_cover(W, H - face_h)}[g];"
        fc += "[f][g]vstack[st];[st]"
    else:
        fc += f"{_crop(gameplay)}{_cover(W, H)},"
    fc += f"ass={ass_name}[outv];[ca]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[outa]"

    out = OUT / "renders" / f"{cid}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{seek:.3f}", "-t", f"{span:.3f}",
         "-i", str(src), "-filter_complex", fc,
         "-map", "[outv]", "-map", "[outa]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out.resolve())], cwd=tmp)
    return out


def contact_sheet(clip_path: Path, out: Path, frames: int = 6) -> None:
    """A strip of frames from the finished clip, for the fresh-agent review."""
    dur = max(probe_duration(clip_path), 0.1)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(clip_path),
         "-vf", f"fps={frames}/{dur:.2f},scale=270:-1,tile={frames}x1",
         "-frames:v", "1", "-q:v", "3", str(out)])


def render_all(cfg: dict, state: dict) -> int:
    done = 0
    for cid, clip in state["clips"].items():
        if clip["status"] != "candidate":
            continue
        video = state["videos"][clip["video"]]
        log(f"render {cid}")
        try:
            path = render_clip(cfg, cid, clip, video)
            contact_sheet(path, OUT / "review" / f"{cid}.jpg")
        except RuntimeError as exc:
            log(f"  failed: {exc}")
            continue
        clip["render"] = str(path)
        clip["sheet"] = str(OUT / "review" / f"{cid}.jpg")
        clip["duration"] = round(probe_duration(path), 2)
        clip["status"] = "rendered"
        done += 1
    log(f"render done: {done} clip(s)")
    return done
