# GTA 6 clipper

Turns GTA 6 streams into ready-to-post vertical clips for paid clipping campaigns. You don't play: you clip streamers who pay for it.

```
fetch  →  find  →  render  →  gauntlet  →  you approve  →  export
(yt-dlp)  (loud moments   (9:16, facecam   (fresh agent     (review.html)   (mp4 + caption
           + reaction      top, captions,   says yes/no                       txt, STATUS.md)
           words)          payoff first)    with faults)
```

Nothing is posted automatically. Export gives you files you upload from your phone.

## 1. One-time setup (on your computer)

You need Python 3.10+ and ffmpeg.

```bash
# macOS:   brew install ffmpeg python
# Windows: winget install ffmpeg Python.Python.3.12
cd clipper
pip install -r requirements.txt
```

The first run downloads the speech-to-text model (~150 MB) automatically.

Optional: install a punchy bold font (e.g. **Montserrat Black** or **Anton**, both free on Google Fonts) and set `captions.font` in `config.yaml`.

## 2. Campaigns (already set up in config.yaml)

`config.yaml` is already filled in for **Tomo GTA VI** and **KreekCraft GTA 6** on Content Rewards: required caption lines, hashtags, call-to-action text and each campaign's extra review checks.

Before your first post:

1. **Join both campaigns** in Content Rewards. Join the Clipping Nation Whop and Discord for Tomo, and read its *Approval Guide*. If you're outside the US/UK/CA/AU, also read *How to Target a Tier 1 Audience*.
2. **Make one dedicated GTA clips account** on TikTok, Instagram and YouTube, connect them in Whop (Settings → Connected Accounts), and do the campaign's **account warm-up** before posting.
3. **Check the channel links** in `config.yaml` (`sources:`) open the right streamers.
4. *(Optional, Tomo only)* Measure Tomo's facecam to get the facecam-on-top layout:
   ```bash
   python clipper.py calibrate "https://www.youtube.com/watch?v=<a Tomo GTA stream>" --at 1200
   ```
   Open `out/calibrate.png`. Each thin line is 0.1 of the frame. Read the facecam box, then set `layout: stack` and `facecam: {x: .., y: .., w: .., h: ..}` for Tomovids. **Keep KreekCraft on `layout: full`**: his campaign requires his overlay to be visible.

Long streams are fetched **audio only** (~300 MB instead of ~8 GB). Only the sections that become clips are downloaded as video.

## 3. Daily routine (~15 min of your time)

```bash
python clipper.py run          # fetch + find + render + gauntlet packet + review page
```

Then **the gauntlet**: open a *new* Claude session with no history and say:

> Read clipper/RULES.md, then review every clip in clipper/out/review/GAUNTLET.md and record a verdict for each.

It runs `python clipper.py verdict <id> yes|no --faults "..."` for each clip. Verdicts are logged in RULES.md.

Then **you**: open `out/review.html` in a browser, watch the clips that passed, and:

```bash
python clipper.py approve <id> <id> ...
python clipper.py reject <id>
python clipper.py adjust <id> --hook "He did NOT see that coming"   # add a hook title (first 3s)
python clipper.py adjust <id> --start 812.5 --end 840   # fix timing → re-render → re-check
python clipper.py render && python clipper.py gauntlet   # after adjusting
python clipper.py export        # approved → out/export/<date>/<campaign>/  (mp4 + caption .txt)
```

AirDrop or sync the export folder to your phone, then post each mp4 with the caption from its .txt. After posting:

```bash
python clipper.py posted <id> tiktok https://www.tiktok.com/@you/video/...
```

Then **submit the link in Content Rewards within 30 minutes** (Tomo's rule). Everything is tracked in `STATUS.md`.

## Running it automatically every morning

macOS/Linux, `crontab -e`:

```
0 9 * * * cd /path/to/a/clipper && /usr/bin/python3 clipper.py run >> work/cron.log 2>&1
```

Windows: Task Scheduler → daily → `python clipper.py run` with "Start in" set to the clipper folder.

## Other commands

```bash
python clipper.py list [--status passed]
python clipper.py add ~/Downloads/vod.mp4 --handle streamer --campaign name   # use a file you already have
python clipper.py fetch | find | render | gauntlet | review                   # run one step
```

## Tuning

| Problem | Change in `config.yaml` |
|---|---|
| Too many boring clips | raise `find.min_excitement_db` (e.g. 8–10) |
| Missing good moments | lower it (4–5), raise `clips_per_video` |
| Clips start too late / too early | `pre_roll_seconds`, `post_roll_seconds` |
| Captions wrong | `whisper_model: small.en` (slower, more accurate) |
| Facecam shows a wall or overlay | fix that streamer's `facecam` box |
| Gameplay shows their overlay | add a `gameplay` box |

Drop screenshots of the campaign's best-performing clips into `references/`. The gauntlet reviewer compares against them.

## Folders

- `work/` holds downloads and `state.json` (every clip's status). Not committed.
- `out/` holds renders, `review.html`, review frame strips and exports. Not committed.
- `RULES.md` has the rules plus the verdict log. Read it before every run.
- `STATUS.md` has every export and posted link.
