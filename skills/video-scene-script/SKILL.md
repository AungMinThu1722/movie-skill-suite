---
name: video-scene-script
description: Convert a movie/video (YouTube, RedNote/Xiaohongshu, direct URL, or local file) into an original-language minute-by-minute visual SRT. Uses scene-aware and dialogue-aware frame sampling: hard-cut frames, dialogue-free gap densification, 16x16 thumbnail deduplication, and automatic >15-minute sub-agent parts. Review individual frames one by one and write plot-aware phrase entries; do not invent dialogue or hand-type timestamps.
---

# Video Scene Script (SRT)

Turn a movie into a **minute-by-minute visual script** named
`<Movie Name>.srt`, written in the movie's **original language**. The visual
pass is scene-aware and, when an audio SRT is available, dialogue-aware:
normal minutes get a baseline frame, hard cuts get additional evidence, and
long dialogue-free minutes get denser sampling for wordless storytelling.

Supported sources: YouTube, RedNote/Xiaohongshu (including `xhslink.com`),
direct video URLs, and local files.

## Division of labor — important

The agent does only two things:

1. Read the manifest/dialogue context and look at every extracted frame
   **one by one**, following `references/vision-prompt.md`.
2. Write one plot-aware phrase line per minute into a script text file.

The scripts do downloading, ffprobe metadata, scene detection, SRT parsing,
frame sampling, thumbnail deduplication, JPEG extraction, part planning, SRT
formatting, merging, and cleanup. Never hand-type SRT timestamps or make a
contact sheet for the visual pass.

For videos longer than 15 minutes, delegate every part to a sub-agent using
`references/subagent-brief.md`; the parent must not view those part frames.

## Pipeline (run in order)

Work directory: `.work` in the current folder. Final output:
`<Movie Name>.srt` in the current folder.

### 0. Dependency check (mandatory first step)

```bash
python3 scripts/check_deps.py
```

Read its JSON. If `path_add` is present, prepend that directory to `PATH`.
If `ok: false`, stop and report the error. This repairs ffmpeg/ffprobe and
yt-dlp after a new session.

### 1. Resolve the video

```bash
python3 scripts/fetch_video.py "<url or local file>" --work-dir .work
```

The script prints JSON with `video`, `title`, and `slug`.

- URL input is downloaded automatically. XHS public notes use the built-in
  extractor; a login/captcha wall requires a Netscape `cookies.txt`.
- A local file is used in place and is never deleted or modified.
- If the user gave no input, ask for a URL or file first.

### 1b. Dialogue track — recommended before frames

For the full pipeline, run the separate **audio-srt** skill on the same
video first. It uses AssemblyAI and produces an original-language SRT with
original timestamps. Keep the video and that SRT, then pass the SRT to the
frame stage:

```bash
python3 skills/audio-srt/scripts/check_deps.py
# run the audio-srt fetch/transcribe steps, retaining its SRT
```

No AssemblyAI key or no `audio-srt` skill? Skip this step. The visual skill
still works standalone in pure-visual mode. When an SRT exists:

```bash
python3 scripts/make_frames.py <video> --out-dir .work/frames \
    --audio-srt ".work/<Movie Name>.srt"
```

The SRT is context only: each part receives a `dialogue.txt` with cues
overlapping its range, and the sampler marks long dialogue-free windows.

### 2. Scene-aware and dialogue-aware frame sampling

```bash
python3 scripts/make_frames.py <video> --out-dir .work/frames \
    --audio-srt ".work/<Movie Name>.srt"
```

Omit `--audio-srt` for pure visual mode. The script probes the video, makes
one ffmpeg scene-detection pass, parses dialogue gaps, selects candidates,
deduplicates 16x16 grayscale thumbnails, and extracts the kept frames.
Its **last stdout line is `PLAN: {json}`**, identical in shape to
`.work/frames/parts.json`.

Sampling defaults:

- Scene mode: one mid-minute `uniform` frame plus up to two `scene` cut
  frames per normal minute.
- A minute whose midpoint is inside a dialogue-free window of at least 45 s
  gets four `gap-uniform` slot-center frames plus eligible `gap-scene` cut
  frames, capped at six total.
- Near-identical frames are dropped, but every minute keeps at least one;
  progress reports forced empty-minute keeps and dropped near-duplicates.
- Frames are scaled to a 960-pixel long edge by default, never upscaled, and
  use even dimensions.
- Videos longer than 15 minutes enter parts mode. Part `k` covers manifest
  segments `((k-1)*15+1)` through `min(k*15,total)`, with a global frame
  counter across part folders.

Useful flags:

| Flag | Meaning |
|---|---|
| `--no-scene` | Disable scene detection and use uniform fallback sampling |
| `--frames-per-minute 1..6` | Uniform fallback count; valid only with `--no-scene` |
| `--uniform-per-minute N` | Normal-minute uniform count in scene mode |
| `--scene-per-minute N` | Maximum hard-cut frames per minute |
| `--scene-threshold 0.20` | ffmpeg scene threshold |
| `--gap-min-seconds 45` | Dialogue-free interval required for gap mode |
| `--gap-uniform 4` | Gap-minute slot-center uniform count |
| `--gap-max-per-minute 6` | Hard gap-minute frame cap |
| `--keep-duplicates` | Disable thumbnail deduplication |
| `--frame-width 960` | Never-upscaled long-edge target |
| `--part-minutes 15` | Part-folder threshold and size |

Outputs are `video_info.json`, `parts.json`, and either a single
`manifest.json`/frame set or `partN/manifest.json`/frame sets. With an audio
SRT, every folder also has `dialogue.txt` in `[m:ss-m:ss] text` form.
Manifests record `reason`, `gap`, and `dialogue_lines` for every segment.

### 2b. Plan delegation

Read `parts.json` before viewing anything:

- `mode: "single"`: continue yourself.
- `mode: "parts"`: create `.work/parts/`, fill one brief per part from
  `references/subagent-brief.md`, and dispatch every part. The brief now
  includes the part's dialogue file and `gaps_inside` windows. Do not view
  part frames in the parent agent.

### 3. Read context, then view frames

Read `references/vision-prompt.md` first. In either a single run or a worker:

1. Read `manifest.json`, including range, reasons, gap flags, and dialogue
   line counts.
2. Read `dialogue.txt` **before the first frame** when it exists. Keep a
   running story summary; use dialogue for plot context, not as a transcript
   to copy.
3. View every frame one at a time in time order. Note `uniform`, `scene`,
   `gap-uniform`, and `gap-scene` reasons. Gap minutes are real wordless
   sequences and deserve richer entries when the frames show them.

### 4. Write the visual script text

Determine the movie's original language from title cards, credits, signs, and
subtitle context. If genuinely ambiguous, ask the user once. Write exactly
one non-comment line per manifest segment, in that language:

- 1–3 plot-aware phrases in normal minutes;
- up to 4–5 phrases in a meaningful gap minute;
- stable clothing tags first; attach real names only when dialogue context
  makes the identity confident;
- visual facts from frames, plot/word meaning from dialogue context and
  readable burned-in subtitles;
- never copy whole subtitle lines, invent speech, or describe audio.

Single mode: `.work/script.txt`. Part N: `.work/script_partN.txt`.
Use `references/script-template.md` for exact phrase style.

### 5. Build or merge the SRT

Single mode:

```bash
python3 scripts/make_srt.py .work/frames/manifest.json \
    .work/script.txt --out "<Title>.srt"
```

Parts are built by their workers:

```bash
python3 scripts/make_srt.py <part-folder>/manifest.json \
    .work/script_partN.txt --out .work/parts/partN.srt
```

If the line count is wrong, fix the text file and rerun. Never hand-edit the
SRT. After every part exists and has the expected segment count, the parent
runs:

```bash
python3 scripts/merge_srt.py .work/parts/part1.srt \
    .work/parts/part2.srt ... --out "<Title>.srt"
```

### 6. Cleanup

```bash
rm -rf .work
ls
```

Only the final SRT, skill folder, and pre-existing user files should remain.
Never delete a local input video.

### 7. Deliver

Present the final `.srt`, state the movie title and original language, give
the entry count, and show a one- or two-entry preview.

## Troubleshooting

- **Tools missing:** rerun `scripts/check_deps.py` and prepend its
  `path_add` value. Some minimal ffmpeg builds need an ffprobe shim for
  testing; real installations should provide both tools.
- **Dialogue SRT missing:** omit `--audio-srt`; the script remains pure
  visual and writes no `dialogue.txt` or gap windows.
- **Sparse fast-cut film:** use `--scene-per-minute 3` or
  `--scene-threshold 0.15`; do **not** use `--frames-per-minute 3` unless
  you deliberately choose `--no-scene` fallback mode.
- **Unreadable on-screen text:** extract a full-size zoom at its manifest
  timestamp with `ffmpeg -ss <t> -i <video> -frames:v 1 .work/zoom.png`.
- **Missing frame near the end:** a seek can land past a very short final
  segment; inspect the manifest and rerun with a valid source if a whole
  minute is empty.
- **Worker failure or wrong entry count:** redispatch only that part with
  the same brief; do not merge partial output.
- **Merge gap/overlap warning:** verify part order and segment ranges before
  rerunning the affected worker.
- **XHS/YouTube access wall:** retry with the user's Netscape cookies file or
  ask for a direct/local video.

## Run book

| Step | Command/action | Produces |
|---|---|---|
| 0 deps | `python3 scripts/check_deps.py` | tool/version JSON |
| 1 fetch | `python3 scripts/fetch_video.py "<input>" --work-dir .work` | video/title JSON |
| 1b audio | run `audio-srt` first when key/skill are available | original-language dialogue SRT |
| 2 frames | `python3 scripts/make_frames.py <video> --out-dir .work/frames [--audio-srt file]` | scene/gap frames, manifests, PLAN |
| 2b plan | read `parts.json`; dispatch brief in parts mode | one worker per part |
| 3–4 vision+write | read dialogue.txt → view frames → write one line/minute | script text |
| 5 SRT | `python3 scripts/make_srt.py <manifest> <script.txt> --out <out.srt>` | single/part SRT |
| 5b merge | `python3 scripts/merge_srt.py .work/parts/*.srt --out <out.srt>` | final parts SRT |
| 6 cleanup | `rm -rf .work && ls` | clean deliverable area |

## Files

- `scripts/check_deps.py` — dependency repair
- `scripts/fetch_video.py` — URL/local input resolver
- `scripts/make_frames.py` — scene-aware sampling, dialogue gaps, dedup,
  parts, manifests, and PLAN
- `scripts/make_srt.py` — manifest + phrase text → SRT
- `scripts/merge_srt.py` — chronological part-SRT merge
- `references/vision-prompt.md` — complete one-frame-at-a-time prompt
- `references/subagent-brief.md` — part worker prompt and parent checklist
- `references/script-template.md` — plot-aware line format/style
- `references/workflow-notes.md` — sampling and delegation run book
