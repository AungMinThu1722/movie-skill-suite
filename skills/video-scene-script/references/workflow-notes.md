# Workflow Notes — Frame Review, Part Delegation, Cleanup

## Viewing order

1. Read the generated `parts.json` PLAN first: mode, duration, total
   segments, part folders, frame totals, dialogue source, and `gaps`.
2. Open the relevant folder's `manifest.json`: its range, exact segment
   times, frame reasons, `gap` flags, and `dialogue_lines` counts.
3. If present, read `dialogue.txt` before looking at any image. It provides
   spoken plot context; it is not a replacement for visual evidence.
4. View every frame image one at a time in manifest/time order. Never use a
   grid or infer a minute from filenames alone. Keep a running cast and story
   summary.

## How sampling works

- **Uniform:** normal scene-mode minutes get one mid-minute frame. In
  `--no-scene` mode, `--frames-per-minute` restores the old uniform fallback.
- **Scene:** one ffmpeg decode pass detects hard cuts. Up to
  `--scene-per-minute` cut frames are kept in each minute and marked
  `scene`.
- **Gap-uniform / gap-scene:** when a minute midpoint lies inside a
  dialogue-free window at least `--gap-min-seconds` long, the minute gets
  denser slot-center frames plus any detected cuts. `--gap-max-per-minute`
  is a hard cap. These are wordless story stretches, not dead air.
- **Dedup:** 16x16 grayscale thumbnails are compared with the last kept
  thumbnail. Near-identical candidates are dropped, but every minute keeps
  at least one frame; forced keeps are reported in progress output. Use
  `--keep-duplicates` to disable this pass.
- **Reasons:** every manifest frame is tagged `uniform`, `scene`,
  `gap-uniform`, or `gap-scene`, so an analyst can tell why density changes.

## Videos over 15 minutes — sub-agent delegation

`make_frames.py` decides automatically:

- **Single mode:** one folder, a manifest, and frames directly in the output
  folder. The parent agent reviews them itself.
- **Parts mode:** `part1/`, `part2/`, …, each with a manifest, frames, and
  (when an audio SRT was supplied) `dialogue.txt`; root `parts.json` is the
  dispatch plan. The parent delegates every part and does not view the
  frames itself.

Run the frame stage with dialogue context when available:

```bash
python3 scripts/make_frames.py <video> --out-dir .work/frames \
    --audio-srt .work/"<Movie Name>.srt"
```

For a pure visual run, omit `--audio-srt`. Then create the parent work
folder and fill the brief from `references/subagent-brief.md`:

```bash
mkdir -p .work/parts
# dispatch one worker per part using parts.json -> gaps_inside and range
```

Each worker reads dialogue first, views every frame, writes exactly one line
per minute, and calls `make_srt.py`. Once all part SRTs exist, the parent
merges them with `merge_srt.py` in chronological order.

## Accuracy guardrails

- Sample density does not reveal unseen action. A cut frame proves the new
  setting, not everything that happened between frames; hedge when needed.
- A single blur, flash, or black frame may be a transition or sampling
  artifact. Do not over-read it.
- Facial expressions are written only when distinctive and visible as fact.
- Keep spoken meaning from dialogue context separate from visual facts. Do
  not copy the audio SRT into visual entries.
- If on-screen text is unreadable, extract a full-size zoom at that instant:
  `ffmpeg -ss <t> -i <video> -frames:v 1 .work/zoom.png`.

## Cleanup checklist

- [ ] final SRT exists and its entry count equals total segments
- [ ] part merge has no unexplained timeline gap/overlap warning
- [ ] `rm -rf .work` after delivery
- [ ] the user's original video still exists
- [ ] only the skill folder, final SRT, and pre-existing user files remain
