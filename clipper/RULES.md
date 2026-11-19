# RULES

Read this before every run. These rules beat anything else.

## Standing rules

1. **Only clip streamers whose campaign you've joined** (or who gave written permission). Never scrape random top clips.
2. **Nothing gets exported until it passes the gauntlet *and* you approve it.** Nothing is posted automatically.
3. **Skip story spoilers**: no main-story cutscenes, mission endings or ending reveals. Also skip glitch/exploit tutorials.
4. **Credit the streamer on every post**, in the caption and with the on-screen @tag.
5. **Follow each campaign's own rules** (tags, length, platforms) over these defaults.
6. **Don't flood**: at most 3 posts per account per day while accounts are new. Never post the same clip more than 5 times total.
7. **Submit every posted link to its campaign within 30 minutes** (Tomo's rule; do it for all).
8. **Hook titles must be true.** No fake context, no clickbait, never make the streamer look bad.
9. **No AI-generated images, thumbnails or voices.** Use real stream footage only.

## Active campaigns

- **tomo-gta6**: Tomo's GTA VI YouTube streams only. $1.50/1K views, min 2,333 views. Funny moments + first reactions. End with "subscribe to Tomo on YouTube".
- **kreekcraft-gta6**: KreekCraft's GTA 6 streams only. $1/1K views, min 2,000 views. His overlay must be visible. Caption needs "Watch KreekCraft on YouTube and Twitch" + #GTA6 #KreekCraft #GrandTheftAutoVI.

## The gauntlet rule

A **fresh agent that has not seen how the clip was made** judges every clip. It gets only the frame strip, the transcript and this checklist. It answers **yes or no, with the faults it found**. A "no" gets fixed (`python clipper.py adjust ...`), re-rendered and judged again.

How to run it: open a **new** Claude chat/session with no history, give it access to this folder and say:

> Read clipper/RULES.md, then review every clip in clipper/out/review/GAUNTLET.md and record a verdict for each.

### Gauntlet checklist (answer "no" if any item fails)

- [ ] **Payoff first**: the first frame/second is the most exciting moment, not a menu, loading screen or calm driving.
- [ ] **Something actually happens**: a chase, crash, stunt, fail, big reaction. Talking about nothing = no.
- [ ] **Layout is right**: facecam on top shows the streamer's face (not cropped to a wall or overlay), gameplay below is readable.
- [ ] **Captions are readable**: big, high-contrast, not covering the face or key action, and not in the bottom 20% or right edge where app buttons sit.
- [ ] **Captions are correct**: no obviously wrong words; no slurs or anything that would get the post removed.
- [ ] **Ending isn't cut mid-sentence or mid-reaction.**
- [ ] **No spoilers**: no main-story cutscenes or ending reveals.
- [ ] **Streamer tag visible.**
- [ ] **Length fits the campaign** (usually 15–60s).
- [ ] **Hook title** (if any) is accurate and readable in under 2 seconds.
- [ ] **Call-to-action** naming the streamer is on screen at the end.
- [ ] Plus every "Extra check" listed for that clip's campaign in the packet.

## Verdict log

| date | clip | verdict | faults |
|------|------|---------|--------|
