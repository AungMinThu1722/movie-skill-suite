---
name: story-vo-srt
description: Merge a movie's video-scene-script SRT (visual phrases per minute) with its audio SRT (AssemblyAI subtitles) into one TTS-ready voice-over story script "<Title> VO.srt", written in the movie's original language in an engaging storyteller style, with a generated hook replacing the first ~10 seconds. All LLM work is done automatically by scripts calling an OpenAI-compatible LLM API (chunk pass + consolidation pass); the agent ONLY runs the exact scripts, checks their JSON output, and delivers. Works standalone with SRTs from any session (explicit paths or auto-discovery by title). Temp files are cleaned up afterwards. Use when the user has both a scene script and a subtitle SRT for a movie and wants a narrated voice-over script for TTS.
---

# Story VO SRT (TTS-ready voice-over script)

Combine the two inputs —

- **scene-script SRT** (from `video-scene-script`: visual phrases, ~1 per
  minute)
- **audio SRT** (from `audio-srt`: spoken subtitles, word-timed)

— into a single **storyteller voice-over script** (`<Title> VO.srt`) in the
movie's **original language**, ready to feed into any TTS engine. The first
~10 s become a generated **hook** (gripping story teaser) that replaces the
film's opening.

> Sibling skills (do not mix their internals): `video-scene-script`
> (vision → scene script) and `audio-srt` (AssemblyAI → subtitles). This
> skill consumes their SRTs, from any session.

## Agent role — run scripts only

Run the exact commands below, read each JSON line, verify `ok`, move on.
The LLM story writing happens **inside the scripts** (API calls) — the
agent writes no story text and edits no SRT. Ask the user only when: no
inputs found, LLM key missing/failing, or an explicit choice is needed.

## Pipeline

Work dir: `.work` (deleted at the end). Output: `<Title> VO.srt` in the
current folder.

### 0. Dependency auto-check (MANDATORY — before ANYTHING)

```bash
python3 scripts/check_deps.py --ping
```

No system tools and no pip packages are needed (stdlib only) — this checks
Python + that the LLM API config (base/key/model from env or `~/.llm_env`)
is resolvable and does a tiny real API ping.
- `llm_key_set: false` → ask the user for the LLM API key/model, save to
  `~/.llm_env` (`LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL`), re-run.
- `ok: false` after ping → show the error; fix config and re-run.

### 1. Resolve the two inputs (auto)

```bash
python3 scripts/resolve_inputs.py --scene <scene.srt> --audio <audio.srt> --title "<Title>" > .work/inputs.json
```

- Explicit paths (user-provided / uploaded files, any session), OR
  auto-discovery: `python3 scripts/resolve_inputs.py --title "<Title>"`
  scans the current folder and classifies by structure (~1 entry/minute =
  scene script; many short entries = audio).
- JSON: `{"scene_srt": "...", "audio_srt": "...", "title": "...",
  "audio_entries": 39, "language": "zh (Chinese)", ...}`
- Only one suitable file found → ask the user for the other file.

### 2. Merge into ID-tagged timeline (auto)

```bash
python3 scripts/merge_timeline.py --inputs .work/inputs.json
```

Writes `.work/story/`: `movie.json`, `timeline.json`, `chunk_NN.json`
(10-minute chunks, stable event IDs `E0001...`, original timestamps).
JSON: chunk count, event counts, duration.

### 3. LLM story pass + assembly (auto)

```bash
python3 scripts/story_srt.py --title "<Title>"
```

Internally, all automatic:
1. per-chunk LLM calls (10-min chunks; sequential on free-tier keys;
   resumable via `.work/story/part_NN.json`)
2. consolidation call — whole-film flow, unified character names, and the
   **hook** for 0:00–0:10 (replaces the opening)
3. mechanical assembly — event IDs mapped back to the **original
   timestamps** (the LLM never typed a time), TTS cleanup, SRT written to
   `<Title> VO.srt`
4. verification report (dialogue coverage, fallback lines, hook, duration)

Useful flags: `--hook-seconds 15`, `--model other-model`, `--force` (redo
chunks), `--parallel N` (only with paid keys), `--no-consolidate`.
Long runs: free models can take minutes — wait for the JSON line; don't
kill it early.

### 4. Cleanup (auto — mandatory)

```bash
rm -rf .work
ls
```

Only skill folders and the output SRTs may remain (inputs are never
modified). Verify with `ls`.

### 5. Deliver

Present `<Title> VO.srt`; state title, language, entry count, hook
present?, dialogue coverage (from the JSON report), and the file path.

## Troubleshooting

- `no movie.json` → step 2 not run (or wrong --work).
- LLM 401/402/403 → bad key/billing: fix `~/.llm_env`.
- Repeated 429s on a free key → wait a few minutes and rerun (resume skips
  finished chunks).
- High `fallback_lines` in the report → the model struggled on that chunk;
  rerun with `--force` once; if persistent, try a stronger `--model`.
- `hook: false` → opening not replaced; rerun `story_srt.py` (parts resume,
  hook pass retries).
- Both sibling outputs are named `<Name>.srt` in one workspace → one
  overwrote the other; rename or pass explicit `--scene/--audio`.
- Wrong language detected → pass `--language "zh (Chinese)"` to
  merge_timeline.py.

## Run book

| Step | Command | Produces |
|---|---|---|
| 0 deps | `python3 scripts/check_deps.py --ping` | JSON: llm config ok? |
| 1 inputs | `python3 scripts/resolve_inputs.py ... > .work/inputs.json` | JSON: scene/audio paths + title |
| 2 timeline | `python3 scripts/merge_timeline.py --inputs .work/inputs.json` | `.work/story/chunk_*.json` |
| 3 story | `python3 scripts/story_srt.py --title "<Title>"` | `<Title> VO.srt` + JSON report |
| 4 cleanup | `rm -rf .work && ls` | skill + output SRTs only |
| 5 deliver | (present the SRT) | — |

## Files

- `scripts/check_deps.py` — deps + LLM config check (+ ping)
- `scripts/resolve_inputs.py` — locate/classify the two input SRTs
- `scripts/merge_timeline.py` — merge → event IDs + 10-min chunks
- `scripts/story_srt.py` — LLM chunk pass + consolidation + mechanical
  timestamp assembly + verification
- `scripts/srtutil.py` — shared SRT helpers
- `references/story-prompt.md` — **the set story prompt** (style, TTS rules,
  ID rules, hook rules) — editable without touching the script
- `references/usage-notes.md` — LLM API notes, architecture, limits
- `requirements.txt` — (none — stdlib only)
