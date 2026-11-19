"""Shared helpers: paths, config, state, ffmpeg wrappers."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"          # downloads, audio, intermediate files (gitignored)
OUT = ROOT / "out"            # renders, review sheets, exports (gitignored)
STATE_FILE = WORK / "state.json"

STATUSES = ["candidate", "rendered", "passed", "failed", "approved", "rejected", "exported", "posted"]


def log(msg: str) -> None:
    print(f"[clipper] {msg}", flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if not cfg_path.exists():
        sys.exit(f"No config at {cfg_path}. ")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg.setdefault("output", {})
    cfg.setdefault("fetch", {})
    cfg.setdefault("find", {})
    cfg.setdefault("captions", {})
    cfg.setdefault("campaigns", [])
    return cfg


def iter_streamers(cfg: dict):
    """Yield (campaign, streamer) pairs."""
    for camp in cfg["campaigns"]:
        for st in camp.get("streamers", []):
            yield camp, st


def find_streamer(cfg: dict, campaign: str, handle: str):
    for camp, st in iter_streamers(cfg):
        if camp["name"] == campaign and st["handle"] == handle:
            return camp, st
    sys.exit(f"Streamer {handle} in campaign {campaign} is no longer in config.yaml")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"videos": {}, "clips": {}}


def save_state(state: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def require_bin(name: str) -> None:
    if not shutil.which(name):
        sys.exit(f"'{name}' is not installed. See clipper/README.md setup.")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        tail = "\n".join(res.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"Command failed: {' '.join(cmd[:6])} ...\n{tail}")


def probe_duration(path: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0
