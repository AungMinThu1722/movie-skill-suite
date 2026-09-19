# Workflow Notes — Grid Review, Chunking, Cleanup

## Viewing order

1. `.work/grids/video_info.json` — length before planning.
2. `overview_*.png` (or `overview_partN_*.png` for chunks) — one frame per
   minute; identify acts, setting changes, busy vs static segments.
3. `grid_AA.png … grid_BB.png` in order (AA = range start).

## What to look for in each cell

- **Setting:** indoor/outdoor, location type, time of day, weather, era cues.
- **People:** how many, clothing/appearance (stable naming), pose,
  interaction.
- **Action:** what the pose suggests; objects in hand; vehicles.
- **Facial expressions — only distinctive ones** (crying, shouting,
  laughing, glaring, fear, shock, pain); visible fact only, never inferred
  emotion; neutral faces are not mentioned.
- **On-screen text:** titles, credits, subtitles, signs, HUD — quote
  exactly (also your main evidence for the movie's language).
- **Composition/transitions:** framing change between adjacent cells = shot
  change; black/fade cells = transition.

## Determining the movie's original language

1. Read the first 1–2 grids: title cards, opening credits, burned-in
   subtitle style, logo text.
2. For chunked runs, re-check the LAST grid of the final part (closing
   credits).
3. Use visual/cultural cues only as secondary evidence.
4. If still ambiguous → ask the user ONE short question, then proceed.
5. Record it as the first line of every part file: `# language: <code>`.

## Chunking long videos (run book)

Rule of thumb (60 s segments):
- **≤ 15 segments (~25 min):** single run, no chunking.
- **> 15 segments:** chunk in blocks of **10 segments (10 min)**:
  part 1 = segments 1–10, part 2 = 11–20, …, last part = rest.

Per chunk N (range A–B):
```bash
python3 scripts/make_grids.py <video> --out-dir .work/grids \
    --from-segment A --to-segment B --part N
# vision: overview_partN_*.png, then grid_AA.png .. grid_BB.png
# write:  .work/script_partN.txt   (# language: xx header + ONE LINE per
#          segment B-A+1, phrase style per vision-prompt.md)
python3 scripts/make_srt.py .work/grids/manifest_partN.json \
    .work/script_partN.txt --out .work/parts/partN.srt
```

- Grids/manifests keep GLOBAL segment numbers — parts never collide in the
  same out-dir, and part SRTs already carry absolute film timestamps.
- **Parallelism:** chunks are independent. If the environment supports
  sub-agents or background tasks, dispatch each chunk as its own task with a
  brief: video path, segment range A–B, part number N, work dir, output
  `.work/parts/partN.srt`, and "follow SKILL.md steps 3–5 + vision-prompt.md,
  in the movie's language <code>". Otherwise run chunks sequentially, 1–2 at
  a time, appending each part before starting the next (context stays small).
- **Merge** when all parts exist:
```bash
python3 scripts/merge_srt.py .work/parts/part1.srt .work/parts/part2.srt ... \
    --out "<Movie Name>.srt"
```
  It renumbers entries and warns about timeline gaps/overlaps — investigate
  any warning by re-checking that chunk's grids.

## Accuracy guardrails

- Frames sampled ~6.7 s apart — fast events between samples are invisible;
  use hedges (`at 4:36 ...`, `between 4:20 and 4:40`, `appears to`).
- One odd cell (flash, blur, glitch) may be a transition or sampling
  artifact — don't over-read it.
- Unreadable text → `ffmpeg -ss <t> -i <video> -frames:v 1 .work/zoom.png`
- Never describe audio or exact speech.

## Cleanup checklist (run before delivery)

- [ ] final .srt exists, correct name `<Movie Name>.srt`, entry count =
      total segments, opens cleanly
- [ ] `rm -rf .work` (downloaded video, grids, manifests, part srt files)
- [ ] if input was a local file: the user's original video still exists
- [ ] `ls` — only the skill folder + the .srt (and pre-existing user files)
- [ ] deliver the .srt with title + language noted
