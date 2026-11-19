"""Step 4: the gauntlet (fresh-agent check) and your own approval."""
from __future__ import annotations

import html
import os
import sys
from datetime import date

from .common import OUT, ROOT, log, now_iso

RULES = ROOT / "RULES.md"


def _words_text(clip: dict) -> str:
    return " ".join(w["text"] for w in clip.get("words") or []) or "(no transcript)"


def write_gauntlet(state: dict) -> int:
    """Write a review packet for a FRESH agent that has not seen any of your notes."""
    todo = [(cid, c) for cid, c in state["clips"].items() if c["status"] == "rendered"]
    packet = OUT / "review" / "GAUNTLET.md"
    packet.parent.mkdir(parents=True, exist_ok=True)
    refs = sorted((ROOT / "references").glob("*.[jp][pn]g")) if (ROOT / "references").exists() else []
    lines = [
        "# Gauntlet review packet",
        "",
        "You are a strict reviewer who has NOT seen how these clips were made.",
        "Judge each clip only from its frames and transcript, against the checklist in",
        "`clipper/RULES.md` (section *Gauntlet checklist*). Open each frame strip image.",
        "",
        "For every clip, run exactly one command from the `clipper/` folder:",
        "",
        "```",
        'python clipper.py verdict <CLIP_ID> yes|no --faults "short list of faults, or none"',
        "```",
        "",
        "Say **no** if any checklist item fails. Do not edit anything else.",
        "",
    ]
    if refs:
        lines += ["## Reference: clips that performed well (compare against these)", ""]
        lines += [f"- `{r.relative_to(ROOT)}`" for r in refs] + [""]
    for cid, c in todo:
        lines += [
            f"## {cid}",
            f"- Frames (start → end, left to right): `{os.path.relpath(c['sheet'], ROOT)}`",
            f"- Video file: `{os.path.relpath(c['render'], ROOT)}`",
            f"- Length: {c.get('duration')}s · streamer: @{c['handle']} · campaign: {c['campaign']}",
            f"- Transcript: {_words_text(c)}",
            "",
        ]
    packet.write_text("\n".join(lines))
    log(f"gauntlet packet: {packet} ({len(todo)} clip(s))")
    return len(todo)


def record_verdict(state: dict, cid: str, verdict: str, faults: str) -> None:
    clip = _get(state, cid)
    ok = verdict.lower() in ("yes", "y", "pass")
    clip["verdicts"].append({"at": now_iso(), "verdict": "yes" if ok else "no", "faults": faults})
    clip["status"] = "passed" if ok else "failed"
    with RULES.open("a") as fh:
        fh.write(f"| {date.today()} | {cid} | {'yes' if ok else 'no'} | {faults or 'none'} |\n")
    log(f"{cid}: {'PASSED' if ok else 'FAILED'} — {faults or 'no faults'}")


def set_status(state: dict, ids: list[str], status: str, force: bool = False) -> None:
    for cid in ids:
        clip = _get(state, cid)
        if status == "approved" and clip["status"] != "passed" and not force:
            log(f"{cid}: not approved — it hasn't passed the gauntlet "
                f"(status: {clip['status']}). Use --force to override.")
            continue
        clip["status"] = status
        log(f"{cid}: {status}")


def adjust(state: dict, cid: str, start: float | None, end: float | None,
           cold_open: float | None) -> None:
    """Fix a clip's timing and send it back through render + gauntlet."""
    clip = _get(state, cid)
    if start is not None:
        clip["start"] = start
    if end is not None:
        clip["end"] = end
    if cold_open is not None:
        clip["cold_open_seconds"] = cold_open
    clip["status"] = "candidate"
    log(f"{cid}: will re-render ({clip['start']}s → {clip['end']}s)")


def write_review_page(state: dict) -> None:
    """A local HTML page to watch every clip with its verdicts and copy-paste commands."""
    page = OUT / "review.html"
    rows = []
    order = {s: i for i, s in enumerate(["passed", "rendered", "failed", "approved", "exported", "posted"])}
    clips = [(cid, c) for cid, c in state["clips"].items() if c.get("render")]
    clips.sort(key=lambda kv: (order.get(kv[1]["status"], 9), -kv[1].get("score", 0)))
    for cid, c in clips:
        v = c["verdicts"][-1] if c["verdicts"] else None
        verdict = (f"<b>{v['verdict'].upper()}</b> — {html.escape(v['faults'] or 'no faults')}"
                   if v else "not reviewed yet")
        rel = os.path.relpath(c["render"], OUT)
        rows.append(f"""
<article class="{c['status']}">
  <video src="{html.escape(rel)}" controls preload="metadata" playsinline></video>
  <div>
    <h2>{html.escape(cid)}</h2>
    <p><span class="pill">{c['status']}</span> @{html.escape(c['handle'])} · {html.escape(c['campaign'])} · {c.get('duration')}s · score {c.get('score')}</p>
    <p>Gauntlet: {verdict}</p>
    <p class="t">{html.escape(_words_text(c))}</p>
    <code>python clipper.py approve {html.escape(cid)}</code>
    <code>python clipper.py reject {html.escape(cid)}</code>
    <code>python clipper.py adjust {html.escape(cid)} --start {c['start']} --end {c['end']}</code>
  </div>
</article>""")
    page.write_text(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clip review</title>
<style>
body{{font:15px system-ui,sans-serif;margin:0 auto;max-width:900px;padding:16px;background:#111;color:#eee}}
article{{display:flex;gap:16px;padding:16px 0;border-bottom:1px solid #333;flex-wrap:wrap}}
video{{width:220px;aspect-ratio:9/16;background:#000;border-radius:8px}}
article>div{{flex:1;min-width:240px}} h2{{font-size:15px;margin:0 0 6px;word-break:break-all}}
.pill{{background:#333;border-radius:99px;padding:2px 8px}}
.passed .pill{{background:#1f6f3a}} .failed .pill{{background:#7a2323}} .approved .pill{{background:#2b4f9c}}
.t{{color:#aaa}} code{{display:block;background:#222;padding:4px 8px;margin:4px 0;border-radius:4px;overflow-x:auto}}
</style>
<h1>Clip review</h1>
<p>Watch each clip. Approve only the ones you'd be proud to post. Commands run from the <code>clipper/</code> folder.</p>
{''.join(rows) or '<p>No rendered clips yet. Run <code>python clipper.py run</code>.</p>'}
""")
    log(f"review page: {page}")


def _get(state: dict, cid: str) -> dict:
    if cid not in state["clips"]:
        sys.exit(f"No clip with id {cid}. Run `python clipper.py list` to see ids.")
    return state["clips"][cid]
