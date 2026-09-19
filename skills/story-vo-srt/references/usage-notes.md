# Story VO SRT — Design & LLM Usage Notes (for the agent)

## What this skill is

Merges the two sibling skills' outputs — the **video scene script** SRT
(visual phrases, ~1/minute) and the **audio** SRT (AssemblyAI subtitles,
word-timed) — into a single **TTS-ready voice-over story script**
(`<Title> VO.srt`), in the movie's original language, storyteller style.
The first ~10 s are replaced by a generated HOOK (gripping story teaser).

## LLM API (OpenAI-compatible, e.g. OpenRouter)

Config resolution: env vars → `~/.llm_env` → `--base/--key/--model` flags:
- `LLM_API_BASE` (default `https://openrouter.ai/api/v1`)
- `LLM_API_KEY`
- `LLM_MODEL`

Call shape: `POST {base}/chat/completions`, `Authorization: Bearer <key>`,
optional OpenRouter headers `HTTP-Referer` / `X-Title` (set by the script).

Free-tier notes (OpenRouter `:free` models):
- ~20 req/min, daily request caps; the script retries 429 with 30 s backoff
  (up to 6 attempts) and runs chunks SEQUENTIALLY by default
  (`--parallel 1`). Don't raise `--parallel` on free keys.
- Free models can be slow: per-call timeout is 300 s — be patient, don't
  kill the run early.
- 401/402/403 fail fast (bad key / billing) — tell the user, don't retry.

Current model: `inclusionai/ling-3.0-flash-fin:free` (strong at Chinese;
adequate at English). If the user switches models, only `~/.llm_env`
changes.

## Why quality holds up (architecture)

- **Timestamps are never written by the LLM.** merge_timeline.py assigns
  event IDs with the original SRT timestamps; the LLM only references IDs;
  story_srt.py maps ID → original time mechanically. The verify report
  checks every dialogue event is covered (auto-fallback fills gaps with
  the original line, flagged in `fallback_lines`).
- **Chunk + consolidate.** 10-minute chunks keep each call focused; the
  final consolidation pass unifies naming/flow across the whole film and
  writes the HOOK only after the whole story is known.
- **Resumable.** Each chunk's output is saved as `.work/story/part_NN.json`;
  reruns skip finished chunks (`--force` redoes).
- **Retries + fallbacks** mean a flaky free-tier call degrades to the
  original line instead of breaking the run.

## Practical limits

- ~90 min films are comfortable for a single consolidation call; longer:
  run per half and concatenate with the sibling skills' merge tooling, or
  raise `--max-tokens-consolidate`.
- Very sparse scene-script input (e.g. only 2 entries) still works — scene
  events are context, dialogue carries the story.

## Standalone contract

- Accepts the two SRTs from ANY session: explicit paths or `--title`
  auto-discovery (structure-based classification: ~1 entry/minute = scene
  script; many 2-10 s entries = audio).
- Naming-collision note: both sibling skills default to `<Movie Name>.srt`
  in the same folder. If both ran in one workspace, one overwrote the
  other — keep distinct names (e.g. `<Name> scene.srt` / `<Name> audio.srt`)
  or pass explicit paths.
- Cleanup: after the run, `rm -rf .work`; only skill folders + output SRTs
  remain. Input files are never modified.
