---
name: video-scene-script
description: Convert a movie/video (YouTube link, RedNote/Xiaohongshu link incl. xhslink short links, other URLs, or local file) into a minute-by-minute visual script saved as "<Movie Name>.srt", written in the movie's original language as terse phrase entries (distinctive facial expressions noted only when they stand out). Auto-checks/installs dependencies (ffmpeg, yt-dlp), downloads the video, and samples individual full-width frames (2 per minute); videos LONGER than 15 minutes are auto-split into per-part frame folders and delegated to sub-agents (ready-made prompt brief in references/subagent-brief.md), then merged. The LLM's ONLY jobs are looking at the frames ONE BY ONE (vision, per references/vision-prompt.md) and writing the per-minute phrase text. All intermediate files are cleaned up afterwards. Use when the user provides a video or video link and wants a scene script / visual screenplay / per-minute description as an SRT file.
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

It checks and auto-installs **ffmpeg/ffprobe** (static build → `~/.local/`)
and **yt-dlp** (pip). Read its JSON output:
- `path_add` → prepend to PATH for all later commands:
  `export PATH="$PATH:<path_add>"`
- `ok: false` → tell the user what failed before continuing.

## Division of labor — IMPORTANT

The LLM does exactly **two** things:

1. **Look** at the frame images **one by one** (vision) — following
   `references/vision-prompt.md`, the set vision prompt for the analysis.
2. **Write** the per-minute phrase text into `script.txt` /
   `script_partN.txt`.

Everything else — downloading the video, sampling frames, splitting parts,
SRT formatting/timestamps, chunk merging, cleanup — is done by the scripts
below via exact commands. **Never** hand-type SRT timestamps, hand-extract
frames, or leave intermediate files behind.

For videos **over 15 minutes**, do NOT view the frames in the main agent —
delegate each part folder to a sub-agent (step 2b).

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

### 2. Sample frames (auto — splits long videos itself)

```bash
python3 scripts/make_frames.py <video from step 1> --out-dir .work/frames
```

One run always covers the **whole video**. The script probes the duration
and decides the layout itself:

- **≤ 15 min → SINGLE mode:** `.work/frames/` gets `manifest.json` +
  `frame_0001_00m00s.jpg …` (2 frames/min, every 30 s, full-width JPEGs,
  exact timestamps inside the manifest).
- **> 15 min → PARTS mode:** `.work/frames/part1/`, `part2/`, … — one
  folder per ≤ 15-minute stretch of film, each with its own
  `manifest.json` and frames, plus `.work/frames/parts.json` (the plan:
  part → folder, segment range, frame count).

The script's last stdout line is `PLAN: {…}` — parse it (or read
`parts.json`) to drive step 2b. Options (rarely needed):
`--frames-per-minute 3` for denser sampling, `--frame-width 1280` when
on-screen text is too small to read.

### 2b. Plan the run: single or sub-agent delegation

From the PLAN JSON:

- **`mode: "single"` (≤ 15 min):** run steps 3–5 yourself — no delegation.
- **`mode: "parts"` (> 15 min):** **delegate every part to a sub-agent /
  background task.** Do not view the frames in the main agent.

  1. `mkdir -p .work/parts`
  2. Read `references/subagent-brief.md` and dispatch **one task per
     part**, copying its brief template with the placeholders filled:
     movie title, part N of M, frames dir (the part folder),
     segment range, language code (if already known), the part's
     `.work/script_partN.txt` path, and the output `.work/parts/partN.srt`.
     The brief tells the sub-agent to follow `references/vision-prompt.md`,
     view its frames one by one, write its text file, and build its part
     SRT with `make_srt.py`.
  3. Briefs are independent — run the tasks **in parallel, as background
     tasks, or sequentially, whichever your environment supports.**
  4. When every part reports back, continue at step 5 (merge).

### 3. Look at the frames (LLM — vision only)

**First read `references/vision-prompt.md` and follow it exactly** — it is
the complete set vision prompt (per-frame viewing, cast list,
facial-expression rule: only distinctive ones, phrase output style,
self-check).

Open the part's `manifest.json` (or `.work/frames/manifest.json` in single
mode), then **view every frame image ONE AT A TIME, in time order** — no
grids, no batching multiple images into one visual. After each minute's
frames, write that minute's phrase line; keep the running cast list from
the vision prompt so naming stays consistent.
(Extra guidance: `references/workflow-notes.md`.)

In delegated runs, this step happens inside each sub-agent, not here.

### 4. Write the script text (LLM — writing only)

Determine **the movie's original language**:
- from on-screen text (title cards, opening/closing credits, burned-in
  subtitles, signs, UI text),
- otherwise from strong visual/cultural cues,
- if genuinely ambiguous → **ask the user**, then continue.

Write the phrase entries: **ONE terse phrase line per minute, in time
order** (one line = one 60 s segment; `#` header line first), in the
movie's original language (not the user's language, not mixed). First
line: `# language: <code>`.

- Single run → `.work/script.txt` (all segments).
- Part N (delegated) → `.work/script_partN.txt` (exactly segments A–B,
  nothing else).

Style: phrases, not subtitle sentences; distinctive facial expressions only
when they stand out; no audio, no invented dialogue.
Rules and examples: `references/script-template.md`.

### 5. Build the SRT (auto)

Single run:

```bash
python3 scripts/make_srt.py .work/frames/manifest.json .work/script.txt --out "<Title>.srt"
```

Delegated part N (this command runs INSIDE the sub-agent; shown for
reference):

```bash
python3 scripts/make_srt.py <part folder>/manifest.json .work/script_partN.txt --out .work/parts/partN.srt
```

The script zips each phrase entry with its segment's exact timestamps —
part entries already carry absolute film time. If it warns about a
phrase/segment count mismatch, fix the text file and rerun — do not
hand-edit the .srt. Use `--bom` if the language is CJK or another script
some players mishandle without a BOM.

**Merge (delegated runs only), after EVERY part SRT exists:** parent
verifies each `.work/parts/partN.srt` is present and non-empty (and each
sub-agent's reported `entries` matches its segment count — re-dispatch a
failed part with the same brief if not), then:

```bash
python3 scripts/merge_srt.py .work/parts/part1.srt .work/parts/part2.srt ... --out "<Title>.srt"
```

Renumbering is automatic; it warns about timeline gaps/overlaps — re-check
that part's frames if a warning appears.

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
  (step 0); it re-downloads the ffmpeg static build and pip-installs
  yt-dlp automatically.
- A frame is missing / `WARNING: no frame at …` → the seek landed past the
  end of a very short final segment; harmless if the manifest's frame list
  for that minute is not empty.
- On-screen text unreadable at 960 px → re-extract that instant full-size:
  `ffmpeg -ss <t> -i <video> -frames:v 1 .work/zoom.png`
- Very long movie (> 1 h) → parts mode handles it automatically (e.g.
  60 min = 4 part folders × ~30 frames = 4 sub-agent tasks, merged at the
  end). If sampling feels too sparse for a fast-cut film, re-run
  `make_frames.py` with `--frames-per-minute 3`.
- A sub-agent fails or its entry count ≠ its segment count → re-dispatch
  just that part with the same brief from `references/subagent-brief.md`.
- `merge_srt.py` reports a gap/overlap → that part's range was mis-set;
  re-run that part (frames carry global minute numbers, so a re-extract is
  never needed).
- Audio is not analyzed — this skill is visual only; say so if the user
  expects dialogue transcription.

## Run book — which script, when, on what

| Step | Command | On what | Produces |
|---|---|---|---|
| 0 deps | `python3 scripts/check_deps.py` | always first | JSON (versions, `path_add`, `installed`) |
| 1 fetch | `python3 scripts/fetch_video.py "<input>" --work-dir .work [--cookies f]` | user's URL/file | JSON: `video` path + real `title` |
| 2 frames | `python3 scripts/make_frames.py <video> --out-dir .work/frames` | fetched video (whole, one run) | `PLAN` JSON, `parts.json`, frame folders + `manifest.json` (auto part split if > 15 min) |
| 2b plan | read PLAN / `parts.json` | — | single → steps 3–5 here; parts → dispatch sub-agents per `references/subagent-brief.md` |
| 3–4 vision+write | (LLM) view frames one by one → write `.work/script[_partN].txt` | frame images + manifest | phrase entries, movie's language |
| 5 srt | `python3 scripts/make_srt.py <manifest> <script.txt> --out <out.srt>` | that run's manifest + text | `.srt` (whole or `.work/parts/partN.srt`) |
| 5b merge | `python3 scripts/merge_srt.py .work/parts/*.srt --out "<Title>.srt"` | all part files (delegated runs) | final `<Title>.srt` |
| 6 cleanup | `rm -rf .work && ls` | work dir | only skill + `<Title>.srt` remain |

Every command prints what it did (video name, ranges, counts, output
paths) — read each output line before moving to the next step.

## Files

- `scripts/check_deps.py` — auto-check/install ffmpeg, yt-dlp (run first)
- `scripts/fetch_video.py` — resolve URL/local input (auto-download, `--cookies` for XHS)
- `scripts/make_frames.py` — individual full-width frames, 2/min, exact
  timestamps in the manifest; auto-splits videos > 15 min into per-part
  folders + `parts.json` plan
- `scripts/make_srt.py` — phrase text + manifest → .srt (whole or part)
- `scripts/merge_srt.py` — merge part .srt files → final (renumbers, checks timeline)
- `references/vision-prompt.md` — **the set vision prompt** (per-frame
  analysis rules, facial-expression rule, phrase style)
- `references/subagent-brief.md` — the ready-made brief for delegating one
  part to a sub-agent/background task (videos > 15 min)
- `references/script-template.md` — text format, phrase style, language rules
- `references/workflow-notes.md` — frame-reading guide, delegation run book, cleanup
- `examples/demo-script.srt` — sample output
- `requirements.txt` — Python deps (ffmpeg is a system dependency)
