"""Step 1: download new VODs / clips, only from streamers listed in config.yaml."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .common import WORK, iter_streamers, log, now_iso


def _make_filter(must_contain: list[str] | None):
    words = [w.lower() for w in (must_contain or [])]

    def _filter(info, *, incomplete=False):
        # Skip streams that are still live; their replay is picked up on a later run.
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return "still live"
        # Only this campaign's game (e.g. titles containing "gta").
        title = (info.get("title") or "").lower()
        if words and title and not any(w in title for w in words):
            return "title doesn't match title_must_contain"
        return None

    return _filter


def fetch(cfg: dict, state: dict) -> int:
    import yt_dlp

    fcfg = cfg["fetch"]
    max_items = int(fcfg.get("max_videos_per_source", 3))
    max_age = int(fcfg.get("max_age_days", 3))
    max_height = int(fcfg.get("max_height", 1080))
    # "audio_first": download only the audio (a 6-hour VOD is ~300 MB instead of ~8 GB),
    # find the moments, then download just those video sections at render time.
    audio_first = fcfg.get("mode", "audio_first") == "audio_first"
    date_after = (datetime.now(timezone.utc) - timedelta(days=max_age)).strftime("%Y%m%d")

    new = 0
    for camp, st in iter_streamers(cfg):
        handle = st["handle"]
        dest = WORK / "videos" / handle
        dest.mkdir(parents=True, exist_ok=True)
        for src in st.get("sources", []):
            log(f"fetch {handle}: {src}")
            opts = {
                "outtmpl": str(dest / "%(id)s.%(ext)s"),
                "format": ("ba/b" if audio_first
                           else f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"),
                "merge_output_format": None if audio_first else "mp4",
                "match_filter": _make_filter(st.get("title_must_contain")),
                "playlistend": max_items,
                "daterange": yt_dlp.utils.DateRange(date_after),
                "download_archive": str(WORK / "downloaded.txt"),
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(src, download=True)
            entries = (info or {}).get("entries") or ([info] if info else [])
            for e in entries:
                if not e or not e.get("id"):
                    continue
                files = list(dest.glob(f"{e['id']}.*"))
                files = [f for f in files if f.suffix in (".mp4", ".mkv", ".webm", ".m4a", ".opus", ".mp3")]
                if not files:
                    continue
                vid = f"{handle}-{e['id']}"
                if vid in state["videos"]:
                    continue
                state["videos"][vid] = {
                    "path": str(files[0]),
                    "handle": handle,
                    "campaign": camp["name"],
                    "title": e.get("title", ""),
                    "url": e.get("webpage_url") or src,
                    "view_count": e.get("view_count"),
                    "fetched_at": now_iso(),
                    "analyzed": False,
                    "audio_only": audio_first,
                }
                new += 1
    log(f"fetch done: {new} new video(s)")
    return new


def add_local(state: dict, path: str, handle: str, campaign: str, url: str = "") -> str:
    """Register a file you already have (e.g. downloaded by hand) as a source video."""
    from pathlib import Path

    p = Path(path).resolve()
    vid = f"{handle}-{p.stem}"
    state["videos"][vid] = {
        "path": str(p), "handle": handle, "campaign": campaign, "title": p.stem,
        "url": url, "view_count": None, "fetched_at": now_iso(), "analyzed": False,
    }
    return vid
