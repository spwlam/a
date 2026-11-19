"""Step 5: export approved clips as ready-to-post files and log them in STATUS.md."""
from __future__ import annotations

import shutil
from datetime import date

from .common import OUT, ROOT, find_streamer, log

STATUS = ROOT / "STATUS.md"


def _hook_line(clip: dict) -> str:
    if clip.get("keywords"):
        return clip["keywords"][0].upper() + " 😳"
    words = [w["text"] for w in clip.get("words") or []][:8]
    return (" ".join(words).strip() + " 😳") if words else "wait for it 😳"


def export(cfg: dict, state: dict) -> int:
    day = date.today().isoformat()
    n = 0
    for cid, clip in state["clips"].items():
        if clip["status"] != "approved":
            continue
        camp, st = find_streamer(cfg, clip["campaign"], clip["handle"])
        dest = OUT / "export" / day / camp["name"]
        dest.mkdir(parents=True, exist_ok=True)
        video = dest / f"{cid}.mp4"
        shutil.copy2(clip["render"], video)

        tags = " ".join(camp.get("required_tags", []) + cfg["output"].get("extra_hashtags", []))
        credit = st.get("credit", f"🎥 @{clip['handle']}")
        caption = f"{_hook_line(clip)}\n\n{credit}\n{tags}".strip()
        (dest / f"{cid}.txt").write_text(
            f"CAPTION (paste this):\n{caption}\n\n"
            f"Post on: {', '.join(camp.get('platforms', ['tiktok', 'youtube_shorts', 'instagram_reels']))}\n"
            f"Campaign: {camp['name']}\n"
            f"Submit links at: {camp.get('submit_url') or '(add submit_url to config.yaml)'}\n"
            f"Campaign rules: {camp.get('notes', '').strip() or '(see campaign page)'}\n"
            f"Source: {clip.get('source_url', '')}\n\n"
            f"After posting, record each link:\n"
            f"  python clipper.py posted {cid} tiktok <url>\n"
        )
        with STATUS.open("a") as fh:
            fh.write(f"| {day} | {cid} | @{clip['handle']} | {camp['name']} | "
                     f"`{video.relative_to(ROOT)}` | exported | |\n")
        clip["status"] = "exported"
        clip["export"] = str(video)
        n += 1
    log(f"export done: {n} clip(s) → {OUT / 'export' / day}")
    return n


def record_post(state: dict, cid: str, platform: str, url: str) -> None:
    clip = state["clips"][cid]
    clip.setdefault("posts", {})[platform] = url
    clip["status"] = "posted"
    with STATUS.open("a") as fh:
        fh.write(f"| {date.today()} | {cid} | @{clip['handle']} | {clip['campaign']} | "
                 f"{platform} | posted | {url} |\n")
    log(f"{cid}: posted on {platform} — remember to submit {url} to the campaign")
