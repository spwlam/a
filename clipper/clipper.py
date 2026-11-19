#!/usr/bin/env python3
"""GTA 6 clipping pipeline. Run `python clipper.py -h` for commands."""
from __future__ import annotations

import argparse

from pipeline.common import load_config, load_state, require_bin, save_state, STATUSES


def main() -> None:
    ap = argparse.ArgumentParser(description="Clip, edit and export GTA 6 stream moments.")
    ap.add_argument("--config", help="path to config.yaml (default: clipper/config.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="fetch + find + render + gauntlet packet + review page (the daily job)")
    sub.add_parser("fetch", help="download new VODs/clips from your campaign streamers")
    sub.add_parser("find", help="find the best moments in downloaded videos")
    sub.add_parser("render", help="render vertical clips for new candidates")
    sub.add_parser("gauntlet", help="write the review packet for a fresh agent")
    sub.add_parser("review", help="rebuild out/review.html")
    sub.add_parser("export", help="copy approved clips + captions into out/export/<date>/")

    p = sub.add_parser("add", help="register a video file you already have")
    p.add_argument("path"); p.add_argument("--handle", required=True)
    p.add_argument("--campaign", required=True); p.add_argument("--url", default="")

    p = sub.add_parser("list", help="list clips")
    p.add_argument("--status", choices=STATUSES)

    p = sub.add_parser("verdict", help="record a gauntlet verdict (used by the fresh agent)")
    p.add_argument("id"); p.add_argument("verdict", choices=["yes", "no"])
    p.add_argument("--faults", default="")

    for name in ("approve", "reject"):
        p = sub.add_parser(name, help=f"{name} clips")
        p.add_argument("ids", nargs="+")
        if name == "approve":
            p.add_argument("--force", action="store_true", help="approve without a gauntlet pass")

    p = sub.add_parser("adjust", help="change a clip's timing and re-render it")
    p.add_argument("id"); p.add_argument("--start", type=float); p.add_argument("--end", type=float)
    p.add_argument("--cold-open", type=float, help="seconds of payoff shown first (0 = off)")
    p.add_argument("--hook", help='title shown in the first 3s, e.g. "He did NOT see that coming"')

    p = sub.add_parser("calibrate", help="save a gridded screenshot to measure a facecam position")
    p.add_argument("source", help="a video URL or file")
    p.add_argument("--at", type=float, default=600, help="seconds into the video (default 600)")

    p = sub.add_parser("posted", help="record where you posted a clip")
    p.add_argument("id"); p.add_argument("platform"); p.add_argument("url")

    a = ap.parse_args()
    cfg = load_config(a.config)
    state = load_state()
    campaigns = {c["name"]: c for c in cfg["campaigns"]}

    from pipeline import export as ex, fetch as fe, find as fi, render as re_, review as rv

    try:
        if a.cmd in ("run", "fetch", "find", "render"):
            require_bin("ffmpeg"); require_bin("ffprobe")
        if a.cmd in ("run", "fetch"):
            fe.fetch(cfg, state); save_state(state)
        if a.cmd in ("run", "find"):
            fi.find_clips(cfg, state, campaigns); save_state(state)
        if a.cmd in ("run", "render"):
            re_.render_all(cfg, state); save_state(state)
        if a.cmd in ("run", "gauntlet"):
            rv.write_gauntlet(state, cfg)
        if a.cmd == "add":
            vid = fe.add_local(state, a.path, a.handle, a.campaign, a.url)
            print(f"added {vid}. Now run: python clipper.py find && python clipper.py render")
        elif a.cmd == "list":
            for cid, c in state["clips"].items():
                if a.status and c["status"] != a.status:
                    continue
                print(f"{c['status']:9} {c.get('score', 0):6.1f}  {cid}")
        elif a.cmd == "verdict":
            rv.record_verdict(state, a.id, a.verdict, a.faults)
        elif a.cmd == "approve":
            rv.set_status(state, a.ids, "approved", force=a.force)
        elif a.cmd == "reject":
            rv.set_status(state, a.ids, "rejected")
        elif a.cmd == "adjust":
            rv.adjust(state, a.id, a.start, a.end, a.cold_open, a.hook)
        elif a.cmd == "export":
            ex.export(cfg, state)
        elif a.cmd == "calibrate":
            from pipeline.calibrate import calibrate
            calibrate(cfg, a.source, a.at)
        elif a.cmd == "posted":
            ex.record_post(state, a.id, a.platform, a.url)
    finally:
        save_state(state)

    if a.cmd in ("run", "review", "render", "verdict", "approve", "reject", "export"):
        rv.write_review_page(state)


if __name__ == "__main__":
    main()
