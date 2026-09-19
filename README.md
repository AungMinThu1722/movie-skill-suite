# Movie Skill Suite

Three complementary **agent skills** that turn a movie (link or file) into
SRT deliverables, built for any agent that loads `SKILL.md`-based skills
(Claude Code, Arena Agent Mode, or any agent you point at these folders).

```
                    ┌──────────────────────────┐
 YouTube / RedNote  │  1 · video-scene-script  │  vision → scene script
 (link or file) ───▶│     (3×3 frame grids)    │  → "<Name>.srt"  (per-minute
                    └────────────┬─────────────┘     phrases, original language
                                 │ video
                    ┌────────────▼─────────────┐
                    │  2 · audio-srt           │  AssemblyAI STT
                    │  (mp3 → transcription)   │  → "<Name>.srt"  (subtitles,
                    └────────────┬─────────────┘     original language + time)
                                 │ both SRTs
                    ┌────────────▼─────────────┐
                    │  3 · story-vo-srt        │  LLM (OpenAI-compatible)
                    │  (merge → storyteller)   │  → "<Name> VO.srt" (TTS-ready
                    └──────────────────────────┘     voice-over, hook at 0:00)
```

Each skill is **self-contained** (own scripts, references, prompts, run
book) and **standalone** — it can run from inputs of any session. Every
skill follows the same contract:

- **Session-safe:** step 0 is an auto dependency check/repair
  (`scripts/check_deps.py`) — tools wiped by a new session are re-installed.
- **Auto pipeline:** download / extraction / formatting / timestamps are all
  Python scripts with JSON output; the agent only runs commands and checks
  results.
- **Clean output:** temp dirs are deleted; only the skill folder(s) + the
  final `.srt` file(s) remain.

## Skills

| Skill | Input | Output | Needs |
|---|---|---|---|
| `skills/video-scene-script` | video URL (YouTube / RedNote / direct) or file | `<Name>.srt` — per-minute visual script, phrase style, original language | ffmpeg, yt-dlp, Pillow |
| `skills/audio-srt` | media URL or file | `<Name>.srt` — spoken subtitles via AssemblyAI (original language, original timestamps) | ffmpeg, yt-dlp, `assemblyai`, AssemblyAI API key |
| `skills/story-vo-srt` | the two SRTs above (any session) | `<Name> VO.srt` — TTS-ready storyteller voice-over, generated hook for the opening | LLM API key (OpenAI-compatible, e.g. OpenRouter) |

All scripts are **Python 3.8+ stdlib-friendly** (no mandatory pip deps
beyond the ones listed); no ffmpeg is needed by `story-vo-srt`.

## Install

```bash
git clone <this-repo> movie-skill-suite
cd movie-skill-suite
./install.sh                 # installs to ~/.claude/skills by default
./install.sh --to /some/dir  # or anywhere your agent reads skills from
```

`install.sh` copies each skill folder (each contains its own `SKILL.md`)
into your skills directory. Your agent discovers them by the `SKILL.md`
frontmatter — no other setup needed.

### One-time configuration (per machine)

| What | Where | Format |
|---|---|---|
| AssemblyAI key | `~/.assemblyai_env` | `ASSEMBLYAI_API_KEY=*** |
| LLM API (OpenRouter etc.) | `~/.llm_env` | `LLM_API_BASE=https://openrouter.ai/api/v1` · `LLM_API_KEY=*** · `LLM_MODEL=inclusionai/ling-3.0-flash-fin:free` |

Any skill's `check_deps.py` detects a missing key and tells the agent to
ask the user; the skill then saves it to the file above. **Keys live in your
home directory, never in this repo** — the repo is clean of secrets.

ffmpeg: if not installed, `video-scene-script` and `audio-srt`
`check_deps.py` auto-download a static build into `~/.local/ffmpeg-static`
on first run (Linux x86_64 / arm64).

## Typical flow (what the agent does)

1. User gives a movie link (e.g. a RedNote/YouTube URL).
2. Agent runs skill 1 → `<Name>.srt` (scene script).
3. Agent runs skill 2 → `<Name> audio.srt` (subtitles).
   (Keep distinct names if both live in one folder — both skills default to
   `<Name>.srt`.)
4. Agent runs skill 3 on the two SRTs → `<Name> VO.srt` (TTS-ready).
5. Agent delivers the SRT files; nothing else is left behind.

## Notes

- `story-vo-srt` uses an OpenAI-compatible chat API. Any provider works
  (OpenRouter, OpenAI, DeepSeek, Gemini-compat, local Ollama) — just set
  `LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL`. Free-tier models with
  built-in reasoning spend part of `max_tokens` on thinking; the scripts
  already budget for that and retry on rate limits.
- RedNote/Xiaohongshu links (incl. `xhslink.com`) are handled by a built-in
  extractor in both download scripts; login-protected notes need a Netscape
  `cookies.txt` (passed via `--cookies`, never committed).
- Everything is visual/audio-based: no dialogue is invented; the LLM in
  skill 3 rewrites *what is actually in the two SRTs*.
