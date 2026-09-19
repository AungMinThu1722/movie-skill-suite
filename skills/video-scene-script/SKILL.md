---
name: video-scene-script
description: Convert a movie/video (YouTube link, RedNote/Xiaohongshu link incl. xhslink short links, other URLs, or local file) into a minute-by-minute visual script saved as "<Movie Name>.srt", written in the movie's original language as terse phrase entries (distinctive facial expressions noted only when they stand out). Auto-checks/installs dependencies (ffmpeg, yt-dlp, Pillow), downloads the video, extracts 3x3 frame grids per minute, and formats/merges the SRT automatically; long videos are chunked into parts (optionally via sub-agents/background tasks) and merged. The LLM's ONLY jobs are looking at the grids (vision, per references/vision-prompt.md) and writing the per-minute phrase text. All intermediate files are cleaned up afterwards. Use when the user provides a video or video link and wants a scene script / visual screenplay / per-minute description as an SRT file.
---

# Video Scene Script (SRT)

Turn a movie into a **minute-by-minute visual script** as an SRT file named
`<Movie Name>.srt`, written in **the movie's original language**.

Supported sources: **YouTube** links, **RedNote / Xiaohongshu (RED)** notes
(including `xhslink.com` short links), direct video URLs, and local files.

## Session start — dependency auto-check (MANDATORY FIRST STEP)

Tools may be wiped between sessions, so before ANYTHING else:

```bash
python3 scripts/check_deps.py
```

It checks and auto-installs **ffmpeg/ffprobe** (static build → `~/.local/`),
**yt-dlp** and **Pillow** (pip). Read its JSON output:
- `path_add` → prepend to PATH for all later commands:
  `export PATH="$PATH:<path_add>"`
- `ok: false` → tell the user what failed before continuing.

## Division of labor — IMPORTANT

The LLM does exactly **two** things:

1. **Look** at the grid images (vision) — following
   `references/vision-prompt.md`, the set vision prompt for the analysis.
2. **Write** the per-minute phrase text into `script.txt` /
   `script_partN.txt`.

Everything else — downloading the video, extracting frames, building grids,
SRT formatting/timestamps, chunk merging, cleanup — is done by the scripts
below via exact commands. **Never** hand-type SRT timestamps, hand-extract
frames, or leave intermediate files behind.

## Pipeline (run the steps in order)

Work directory: `.work` inside the current folder (create it; it is deleted
at the end). Final output: `<Movie Name>.srt` in the current folder.

### 1. Resolve the input (auto)

```bash
python3 scripts/fetch_video.py "<url or local file>" --work-dir .work
```

Prints one JSON line:
`{"source": ..., "video": "/abs/video.mp4", "title": "Movie Name", "slug": ..., "downloaded": true/false}`

- URL → downloaded automatically. **RedNote / Xiaohongshu** notes
  (xiaohongshu.com, xhslink.com short links) use the built-in XHS extractor
  in `fetch_video.py` (resolves short links, reads the note page state with
  a mobile UA, downloads the stream CDN URL with size verification + backup
  URLs — works anonymously for public notes). All other URLs go through
  yt-dlp (installed via pip if missing).
- Local file → used in place. **Never delete or modify the user's original
  file** at any point in the pipeline.
- If the user gave no input at all, ask for the video URL or file first.
- If an XHS note fails with a login/captcha wall, ask the user for a
  Netscape-format `cookies.txt` (exported from their logged-in browser) and
  rerun step 1 with `--cookies /path/to/cookies.txt`.

### 2. Extract 3x3 frame grids (auto)

```bash
python3 scripts/make_grids.py <video from step 1> --out-dir .work/grids
```

Produces in `.work/grids/`: `video_info.json`, `grid_01.png … grid_NN.png`
(labeled 3x3, chronological left→right, top→bottom), `overview_01.png …`,
`manifest.json` (exact segment ranges + per-cell timestamps).

Options (rarely needed): `--segment-seconds 120` for very long movies,
`--cell-width 640` when on-screen text is too small to read.

### 2b. Plan the run: single or chunked

From the duration (step 1's JSON → ffprobe, or run step 2 once — it prints
`Segments: N total`), with 60 s segments:

- **N ≤ 15 (~25 min):** single run — use steps 3–5 as below.
- **N > 15:** chunk in blocks of **10 segments (10 min)**:
  part 1 = segments 1–10, part 2 = 11–20, …, last part = the rest.
  For each chunk, run steps 2–5 with the range flags (below). Chunks are
  independent — if this environment supports **sub-agents or background
  tasks**, dispatch each chunk as its own task with a brief: *video path,
  segment range A–B, part number N, work dir `.work`, output
  `.work/parts/partN.srt`, "follow SKILL.md steps 3–5 and
  `references/vision-prompt.md`, language <code>"*. Otherwise run chunks
  sequentially, one at a time.

Chunk variant of step 2 (per chunk N, range A–B):

```bash
python3 scripts/make_grids.py <video> --out-dir .work/grids \
    --from-segment A --to-segment B --part N
```

Grids keep GLOBAL segment numbers (`grid_11.png` … `grid_20.png`), so parts
share one out-dir without colliding; the manifest is
`manifest_partN.json`, the overview `overview_partN_*.png`.

### 3. Look at the grids (LLM — vision only)

**First read `references/vision-prompt.md` and follow it exactly** — it is
the complete set vision prompt (what to look for, facial-expression rule:
only distinctive ones, phrase output style, self-check).

Read `overview_*.png` (whole-film arc) first, then `grid_AA.png … grid_BB.png`
in order (AA = range start). Review in batches of 3–5 grids; keep the
running cast list from the vision prompt so naming stays consistent.
(Extra guidance: `references/workflow-notes.md`.)

### 4. Write the script text (LLM — writing only)

Determine **the movie's original language**:
- from on-screen text (title cards, opening/closing credits, burned-in
  subtitles, signs, UI text),
- otherwise from strong visual/cultural cues,
- if genuinely ambiguous → **ask the user**, then continue.

Write the phrase entries: **ONE terse phrase line per segment, in time
order** (one line = one segment; `#` header line first), in the movie's
original language (not the user's language, not mixed). First line:
`# language: <code>`.

- Single run → `.work/script.txt` (all segments).
- Chunk N → `.work/script_partN.txt` (exactly segments A–B, nothing else).

Style: phrases, not subtitle sentences; distinctive facial expressions only
when they stand out; no audio, no invented dialogue.
Rules and examples: `references/script-template.md`.

### 5. Build the SRT (auto)

Single run:

```bash
python3 scripts/make_srt.py .work/grids/manifest.json .work/script.txt --out "<Title>.srt"
```

Chunked (per chunk N):

```bash
python3 scripts/make_srt.py .work/grids/manifest_partN.json .work/script_partN.txt --out .work/parts/partN.srt
```

The script zips each phrase entry with its segment's exact timestamps —
part entries already carry absolute film time. If it warns about a
phrase/segment count mismatch, fix the text file and rerun — do not
hand-edit the .srt. Use `--bom` if the language is CJK or another script
some players mishandle without a BOM.

**Merge (chunked runs only), after every part exists:**

```bash
python3 scripts/merge_srt.py .work/parts/part1.srt .work/parts/part2.srt ... --out "<Title>.srt"
```

Renumbering is automatic; it warns about timeline gaps/overlaps — re-check
that chunk's grids if a warning appears.

### 6. Cleanup (auto — mandatory)

```bash
rm -rf .work
ls
```

After this, **only the skill folder and `<Movie Name>.srt` may remain** in
the working area (plus whatever the user already had there — never delete
user files such as their original video). Verify with `ls` before delivering.

### 7. Deliver

Present the `.srt` file to the user, state the movie title and the language
the script was written in, and show the first 1–2 entries inline as a
preview.

## Troubleshooting

- XHS note fails ("login/captcha wall", "no video stream", download failed
  on all URLs) → ask the user for `cookies.txt` and retry with `--cookies`;
  short-link tokens also expire, so use the link the user just sent.
- `yt-dlp download failed` — URL may need login or be region-locked; ask for
  cookies (with `--cookies`), a direct file, or another source.
- Tools missing after a session restart → rerun `scripts/check_deps.py`
  (step 0); it re-downloads the ffmpeg static build and pip-installs the
  Python deps automatically.
- Grids have no labels (Pillow missing) → timestamps are in
  `.work/grids/manifest.json` (`label_seconds`, in reading order).
- On-screen text unreadable at 480px → re-extract that instant full-size:
  `ffmpeg -ss <t> -i <video> -frames:v 1 .work/zoom.png`
- Very long movie (> 1 h): chunking (step 2b) handles it — 10-segment
  parts, optionally dispatched to sub-agents/background tasks, merged at
  the end. If a part run is itself slow, also add `--segment-seconds 120`
  and use consistent chunk sizes.
- `merge_srt.py` reports a gap/overlap → that chunk's range was mis-set;
  re-run that chunk with the correct `--from-segment/--to-segment` and
  re-merge.
- Audio is not analyzed — this skill is visual only; say so if the user
  expects dialogue transcription.

## Run book — which script, when, on what

| Step | Command | On what | Produces |
|---|---|---|---|
| 0 deps | `python3 scripts/check_deps.py` | always first | JSON (versions, `path_add`, `installed`) |
| 1 fetch | `python3 scripts/fetch_video.py "<input>" --work-dir .work [--cookies f]` | user's URL/file | JSON: `video` path + real `title` |
| 2 grids | `python3 scripts/make_grids.py <video> --out-dir .work/grids [--from-segment A --to-segment B --part N]` | fetched video (whole or chunk A–B) | `grid_AA.png…`, `overview…`, `manifest[_partN].json` |
| 3–4 vision+write | (LLM) read grids → write `.work/script[_partN].txt` | grid images | phrase entries, movie's language |
| 5 srt | `python3 scripts/make_srt.py <manifest> <script.txt> --out <out.srt>` | that run's manifest + text | `.srt` (whole or `.work/parts/partN.srt`) |
| 5b merge | `python3 scripts/merge_srt.py .work/parts/*.srt --out "<Title>.srt"` | all part files (chunked runs) | final `<Title>.srt` |
| 6 cleanup | `rm -rf .work && ls` | work dir | only skill + `<Title>.srt` remain |

Every command prints what it did (video name, ranges, counts, output
paths) — read each output line before moving to the next step.

## Files

- `scripts/check_deps.py` — auto-check/install ffmpeg, yt-dlp, Pillow (run first)
- `scripts/fetch_video.py` — resolve URL/local input (auto-download, `--cookies` for XHS)
- `scripts/make_grids.py` — per-minute 3x3 labeled frame grids (+ `--from-segment/--to-segment/--part` for chunks)
- `scripts/make_srt.py` — phrase text + manifest → .srt (whole or part)
- `scripts/merge_srt.py` — merge part .srt files → final (renumbers, checks timeline)
- `references/vision-prompt.md` — **the set vision prompt** (per-grid analysis rules, facial-expression rule, phrase style)
- `references/script-template.md` — text format, phrase style, language rules
- `references/workflow-notes.md` — grid-reading guide, chunking run book, cleanup
- `examples/demo-script.srt` — sample output
- `requirements.txt` — Python deps (ffmpeg is a system dependency)
