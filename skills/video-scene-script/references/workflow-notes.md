# Workflow Notes — Frame Review, Part Delegation, Cleanup

## Viewing order

1. `make_frames.py` output / `.work/frames/parts.json` — the PLAN: mode
   (single vs parts), total segments, part folders with their segment
   ranges. Plan the run from this before viewing anything.
2. Part folder's `manifest.json` — which frames belong to which minute,
   exact timestamps.
3. Frame images **one at a time, in time order** — never a grid, never a
   pile. Defaults: 2 frames/min (one every 30 s), 15 minutes per part
   folder in parts mode.

## What to look for in each frame

- **Setting:** indoor/outdoor, location type, time of day, weather, era cues.
- **People:** how many, clothing/appearance (stable naming), pose,
  interaction.
- **Action:** what the pose suggests; objects in hand; vehicles.
- **Facial expressions — only distinctive ones** (crying, shouting,
  laughing, glaring, fear, shock, pain); visible fact only, never inferred
  emotion; neutral faces are not mentioned.
- **On-screen text:** titles, credits, subtitles, signs, HUD — quote
  exactly (also your main evidence for the movie's language).
- **Transitions:** two consecutive frames in completely different settings
  = a cut between them; black/blurred frame = fade/transition.

Full rules: `vision-prompt.md` (read it before the first frame, every time).

## Determining the movie's original language

1. Look at the first 2–4 frames: title cards, opening credits, burned-in
   subtitle style, logo text.
2. For delegated parts, the brief carries the language code; each
   sub-agent still sanity-checks it against its own first frames.
3. Use visual/cultural cues only as secondary evidence.
4. If still ambiguous → ask the user ONE short question, then proceed.
5. Record it as the first line of every part file: `# language: <code>`.

## Videos over 15 minutes — sub-agent delegation (run book)

`make_frames.py` decides automatically:

- **≤ 15 min → SINGLE mode:** one frame folder + `manifest.json`. The
  agent views the frames itself (steps 3–5 of SKILL.md), no delegation.
- **> 15 min → PARTS mode:** `.work/frames/part1/`, `part2/`, …
  (≤ 15 min of frames each, own `manifest.json` per folder) plus
  `.work/frames/parts.json` (the plan). **Delegate every part** — the
  parent agent must not view the frames itself.

Delegation procedure (parent):

```bash
# 1. frames + plan (one run covers the whole video; parts split automatically)
python3 scripts/make_frames.py <video> --out-dir .work/frames
# read the PLAN JSON / .work/frames/parts.json

mkdir -p .work/parts
# 2. dispatch one sub-agent/background task per part with the brief from
#    references/subagent-brief.md (fill: title, part N of M, frames dir,
#    segment range, language, .work/script_partN.txt, .work/parts/partN.srt)
#    — run them in parallel, as background tasks, or sequentially,
#      whichever your environment supports; briefs are independent
# 3. each sub-agent: views its part's frames (vision-prompt.md), writes its
#    script_partN.txt, builds .work/parts/partN.srt via make_srt.py
# 4. parent merges when ALL parts exist:
python3 scripts/merge_srt.py .work/parts/part1.srt .work/parts/part2.srt ... \
    --out "<Movie Name>.srt"
```

- Manifests carry GLOBAL minute numbers and absolute film timestamps —
  part SRTs merge without time math.
- If a part's sub-agent fails or its entry count ≠ its segment count,
  re-dispatch just that part with the same brief.
- `merge_srt.py` warns about timeline gaps/overlaps — that means a part's
  range was mis-set; re-run that part.

## Accuracy guardrails

- Frames are ~30 s apart — fast events between samples are invisible;
  use hedges (`at 4:36 ...`, `between 4:20 and 4:40`, `appears to`).
- One odd frame (flash, blur, glitch) may be a transition or sampling
  artifact — don't over-read it.
- Unreadable text → zoom that instant full-size:
  `ffmpeg -ss <t> -i <video> -frames:v 1 .work/zoom.png`
- Never describe audio or exact speech.

## Cleanup checklist (run before delivery)

- [ ] final .srt exists, correct name `<Movie Name>.srt`, entry count =
      total segments, opens cleanly
- [ ] `rm -rf .work` (downloaded video, frame folders, manifests, part
      srt files)
- [ ] if input was a local file: the user's original video still exists
- [ ] `ls` — only the skill folder + the .srt (and pre-existing user files)
- [ ] deliver the .srt with title + language noted
