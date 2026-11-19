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
cp config.example.yaml config.yaml
```

The first run downloads the speech-to-text model (~150 MB) automatically.

Optional: install a punchy bold font (e.g. **Montserrat Black** or **Anton**, both free on Google Fonts) and set `captions.font` in `config.yaml`.

## 2. Join campaigns, then fill in config.yaml

1. Find GTA 6 / gaming clipping campaigns. Whop's **Content Rewards** is the biggest marketplace; search "GTA" or "clipping". Look for: pay per 1K views, which platforms count, required tags, minimum length and minimum views to get paid.
2. For each campaign, add a block under `campaigns:`. Paste its rules into `notes`, its tag requirements into `required_tags`, and its streamer(s) under `streamers`.
3. For each streamer, measure where their **facecam** sits. Screenshot their stream, then estimate x, y, w and h as fractions of the frame (e.g. a cam in the top-left quarter is `{x: 0, y: 0, w: 0.25, h: 0.3}`). Delete `facecam` if they have none.
4. Start with the **clips** URL (`/clips?filter=clips&range=24hr`). Those are small downloads of moments viewers already liked. Switch to `/videos?filter=archives` (full broadcasts) once things work; those are big downloads but yield more moments.

**Only list streamers whose campaign you've joined.** That's what makes this legal and paid.

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
python clipper.py adjust <id> --start 812.5 --end 840   # fix timing → re-render → re-check
python clipper.py render && python clipper.py gauntlet   # after adjusting
python clipper.py export        # approved → out/export/<date>/<campaign>/  (mp4 + caption .txt)
```

AirDrop or sync the export folder to your phone, then post each mp4 with the caption from its .txt. After posting:

```bash
python clipper.py posted <id> tiktok https://www.tiktok.com/@you/video/...
```

Then submit those links in the campaign dashboard. Everything is tracked in `STATUS.md`.

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
