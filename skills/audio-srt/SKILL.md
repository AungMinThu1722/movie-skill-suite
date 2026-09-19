---
name: audio-srt
description: Convert a video/audio (YouTube link, RedNote/Xiaohongshu link incl. xhslink short links, other remote links, or local file) into an SRT subtitle file named "<Movie Name>.srt" using the AssemblyAI speech-to-text API. The SRT keeps the ORIGINAL spoken language and ORIGINAL timestamps — no translation, no rewriting. The whole pipeline is automatic (dependency auto-check, download, audio extraction, transcription, SRT export, cleanup); the agent ONLY runs the exact scripts, verifies their JSON output, and delivers the file. All temp files are deleted afterwards so only this skill folder and "<Movie Name>.srt" remain. Use when the user provides a video/audio link or file and wants subtitles (SRT) of what is spoken.
---

# Audio → SRT (AssemblyAI)

Turn a movie's audio into an **SRT file named `<Movie Name>.srt`**, with
**original spoken language and original timestamps** — generated entirely by
the AssemblyAI API, with zero LLM rewriting.

> Separate skill: do not mix with `video-scene-script` (that one is
> vision-based scene scripting; this one is audio transcription).

## Agent role — run scripts only

The agent does exactly this: **run the exact commands below, read each JSON
output line, verify it says ok, then move on** (plus ask the user when
something is genuinely missing — no input, no API key, login wall).
No frame extraction, no SRT editing, no timestamp typing, no file
management beyond the commands shown.

## Pipeline

Work dir: `.work` in the current folder (deleted at the end).
Final output: `<Movie Name>.srt` in the current folder.

### 0. Dependency auto-check (MANDATORY — before ANYTHING)

Tools may be wiped between sessions, so this is always the first command:

```bash
python3 scripts/check_deps.py
```

It auto-installs **ffmpeg/ffprobe** (static build → `~/.local/`),
**yt-dlp** and the **assemblyai** SDK (pip). Read the JSON:
- `path_add` → `export PATH="$PATH:<path_add>"` for all later commands
- `api_key_set: false` → ask the user for their AssemblyAI API key, save it
  to `~/.assemblyai_env` as `ASSEMBLYAI_API_KEY=<key>`, re-run check
- `ok: false` → tell the user what failed

### 1. Resolve the input (auto)

```bash
python3 scripts/fetch_media.py "<url or local file>" --work-dir .work
```

JSON: `{"media": "/abs/file.mp4", "title": "Movie Name", ...}`
- YouTube / remote links → yt-dlp; **RedNote/XHS** links → built-in
  extractor (anonymous for public notes, `--cookies` for login-protected)
- Local file → used in place, never modified
- No input given → ask the user first

### 2. Transcribe + export SRT (auto)

```bash
python3 scripts/transcribe_srt.py <media from step 1> --title "<Title>"
```

- Extracts 16 kHz mono mp3 (if input is video) → AssemblyAI upload +
  transcribe (auto language detection) → **native SRT export** (original
  language, original timestamps) → writes `<Title>.srt` in the current
  folder → deletes the remote transcript.
- JSON: `{"ok": true, "srt": "...", "language_code": "zh",
  "duration_seconds": ..., "entries": N, "transcript_deleted": true, ...}`
- Options:
  - `--lang zh` — force a language only when the USER names one (default:
    auto-detect)
  - `--chars-per-caption 42` — caption line length (default 32)
  - `--bom` — CJK/other scripts where some players want a UTF-8 BOM
  - `--keep-transcript` — keep the remote transcript (re-export possible)
- Read `language_code` from the JSON and mention it when delivering.

### 3. Cleanup (auto — mandatory)

```bash
rm -rf .work
ls
```

Only the skill folder and `<Movie Name>.srt` may remain (plus pre-existing
user files — a local input file must still exist). Verify with `ls`.

### 4. Deliver

Present the `.srt`, state: movie title, detected language, duration,
entry count, and where the file is.

## Troubleshooting

- `no AssemblyAI API key` → ask user; save to `~/.assemblyai_env`.
- `Transcription failed: ...401.../unauthorized` → bad/expired key.
- Quota/balance errors → user must top up on assemblyai.com.
- `not available in this language` with `--lang` → the script already
  retries on universal-2; if it still fails, that language isn't supported
  (see `references/usage-notes.md`).
- Empty SRT / "no speech detected" → the media has no usable audio; tell
  the user.
- XHS login wall → ask for Netscape `cookies.txt`, rerun step 1 with
  `--cookies`; use the link the user just sent (short-link tokens expire).
- YouTube region/age restrictions → ask for `cookies.txt` or a direct file.
- Tools missing after session restart → rerun step 0 (it self-repairs).

## Run book

| Step | Command | Produces |
|---|---|---|
| 0 deps | `python3 scripts/check_deps.py` | JSON: versions, `api_key_set`, `path_add` |
| 1 fetch | `python3 scripts/fetch_media.py "<input>" --work-dir .work` | JSON: `media` path + real `title` |
| 2 srt | `python3 scripts/transcribe_srt.py <media> --title "<Title>" [--lang xx]` | `<Title>.srt` + JSON summary |
| 3 cleanup | `rm -rf .work && ls` | only skill + `<Title>.srt` |
| 4 deliver | (present the .srt) | — |

## Files

- `scripts/check_deps.py` — auto-check/install ffmpeg, yt-dlp, assemblyai (+ API key check)
- `scripts/fetch_media.py` — resolve URL/local input (yt-dlp + built-in XHS extractor, `--cookies`)
- `scripts/transcribe_srt.py` — audio extract → AssemblyAI → SRT (original language/timestamps)
- `references/usage-notes.md` — AssemblyAI API cheat-sheet, models, languages, billing
- `requirements.txt` — Python deps (ffmpeg is a system dependency)
