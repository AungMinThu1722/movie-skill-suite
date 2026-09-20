# Movie Skill Suite

Three complementary **agent skills** turn a movie into original-language
subtitles, scene scripts, and TTS-ready story narration. The recommended full
pipeline runs audio first so the visual sampler can use dialogue context.

```
 YouTube / RedNote / file
          │
          ▼
┌──────────────────────────┐
│ 1 · audio-srt             │  AssemblyAI speech → original-language SRT
│    (run first)            │  + original timestamps
└────────────┬─────────────┘
             │ dialogue SRT + same video
             ▼
┌──────────────────────────┐
│ 2 · video-scene-script   │  scene-aware + dialogue-aware frame sampling
│                          │  → per-minute visual script SRT
│                          │  >15 min → sub-agent part folders
└────────────┬─────────────┘
             │ audio SRT + scene SRT
             ▼
┌──────────────────────────┐
│ 3 · story-vo-srt         │  merge → storyteller LLM → TTS-ready VO SRT
└──────────────────────────┘
```

Every skill is self-contained (`SKILL.md`, scripts, references, and its own
run book). They can also run independently:

| Skill | Input | Output | Needs |
|---|---|---|---|
| `skills/audio-srt` | video/audio URL or local file | `<Name>.srt` — spoken subtitles, original language and timestamps | ffmpeg, yt-dlp, AssemblyAI key |
| `skills/video-scene-script` | video URL or local file, optionally audio SRT | `<Name>.srt` — per-minute visual script, original language | ffmpeg, ffprobe, yt-dlp |
| `skills/story-vo-srt` | audio SRT + visual scene SRT | `<Name> VO.srt` — Burmese TTS-ready storyteller narration (20–24 Unicode chars/sec) | OpenAI-compatible LLM key |

## Recommended flow

1. Run `audio-srt` first on the movie when an AssemblyAI key is available.
   Keep the downloaded/original video and the resulting SRT.
2. Run `video-scene-script` on the same video with
   `--audio-srt <dialogue.srt>`. It reads the SRT for plot context, writes
   per-part `dialogue.txt`, detects long dialogue-free gaps, adds
   `gap-uniform`/`gap-scene` frames, detects hard cuts, and deduplicates
   near-identical thumbnails. Videos over 15 minutes are automatically split
   into part folders for delegation.
3. Run `story-vo-srt` on both SRTs. It rewrites them as natural Burmese
   narrator speech: every dialogue beat is covered by paraphrase/attribution,
   while ordinary scene-only beats stay brief or may be omitted. Burmese TTS
   timing is calculated at 20–24 Unicode characters per second, with a 21.6
   CPS default target.

If AssemblyAI is unavailable or there is no key, skip step 1: run the visual
skill without `--audio-srt` for a pure-visual scene script. The story skill
can still be used with whatever inputs are available.

## Install

```bash
git clone <this-repo> movie-skill-suite
cd movie-skill-suite
./install.sh                 # installs to ~/.claude/skills by default
./install.sh --to /some/dir  # or anywhere your agent reads skills from
```

Each installed skill contains its own `SKILL.md`; no suite-level runtime is
required.

## Configuration

| What | Where | Format |
|---|---|---|
| AssemblyAI key | `~/.assemblyai_env` | `ASSEMBLYAI_API_KEY=***` |
| LLM API | `~/.llm_env` | `LLM_API_BASE=https://openrouter.ai/api/v1`, `LLM_API_KEY=***`, `LLM_MODEL=...` |

Keys stay in the home directory and are never committed. Each skill's
`check_deps.py` reports missing configuration and tells the agent what to
request. ffmpeg/ffprobe and yt-dlp are repaired automatically where the skill
supports it.

## Frame-sampling contract

`video-scene-script/scripts/make_frames.py` is Python-stdlib-only. Scene mode
uses one ffmpeg `select/showinfo` pass and records `uniform`, `scene`,
`gap-uniform`, and `gap-scene` reasons in each manifest. With an audio SRT,
`dialogue.txt` is written before the visual pass and dialogue-free windows
of at least 45 seconds receive denser sampling by default. 16x16 grayscale
thumbnail deduplication keeps every minute represented. The final stdout line
is a machine-readable `PLAN: {...}` matching `parts.json`.

For long videos, read `parts.json` first and use
`skills/video-scene-script/references/subagent-brief.md`: one worker per part,
then `merge_srt.py` after every part has the expected segment count.

## Output and cleanup

All skills use `.work` for temporary media and frames. The run books require
removing it before delivery. A local input video is never deleted. Keep final
SRTs under distinct names when audio and visual outputs share a directory
(for example, `Movie audio.srt` and `Movie scene.srt`).

## Notes

- `audio-srt` uses AssemblyAI and preserves spoken language/timestamps; it
  does not rewrite or translate.
- `video-scene-script` is visual evidence, not audio transcription. Read
  `dialogue.txt` for context, but do not copy the full audio SRT into visual
  entries.
- `story-vo-srt` uses an OpenAI-compatible chat API (OpenRouter, OpenAI,
  DeepSeek, Gemini-compatible, local Ollama, and similar providers) and
  calculates Burmese voice-over timing from Python Unicode-character counts.
- Public RedNote/Xiaohongshu links are handled by the built-in fetchers;
  login-protected sources need a Netscape-format cookies file.
