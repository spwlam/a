"""Save one frame from a stream with a 10% grid, to read off facecam/gameplay boxes."""
from __future__ import annotations

from pathlib import Path

from .common import OUT, WORK, log, run


def calibrate(cfg: dict, source: str, at: float) -> Path:
    src = Path(source)
    if not src.exists():
        from .render import _download_section
        src = _download_section(source, at, at + 2, WORK / "sections" / "calibrate",
                                int(cfg["fetch"].get("max_height", 1080)))
        at = 0.5
    out = OUT / "calibrate.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Thin white lines every 10%, thick red lines at 50%.
    grid = ("scale=1280:-2,drawgrid=w=iw/10:h=ih/10:t=1:c=white@0.6,"
            "drawgrid=w=iw/2:h=ih/2:t=3:c=red@0.9")
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(src),
         "-frames:v", "1", "-vf", grid, str(out)])
    log(f"saved {out}")
    log("Each thin line is 0.1 of the frame (red lines are 0.5). Read the facecam's top-left")
    log("corner as x, y and its size as w, h, e.g. facecam: {x: 0.7, y: 0.0, w: 0.3, h: 0.3}")
    return out
