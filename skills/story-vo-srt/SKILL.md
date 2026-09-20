---
name: story-vo-srt
description: Combine a video-scene-script SRT and an audio dialogue SRT into a natural Burmese storyteller voice-over SRT. Dialogue beats are mandatory but paraphrased and attributed rather than copied as a transcript; ordinary scene-only beats are optional and concise. Uses Burmese TTS pacing of 20–24 Unicode characters per second, calculates explicit narration durations, consolidates character continuity, and generates a hook for the opening.
---

# Story VO SRT — Burmese TTS Narration

Combine the two suite inputs:

- **scene-script SRT** from `video-scene-script` — visual evidence and
  important scene beats, usually about one entry per minute;
- **audio SRT** from `audio-srt` — word-timed spoken dialogue.

The result is `<Title> VO.srt`: a natural **Burmese movie-recap narrator**
script ready for TTS. It is not a book-like transcript and it does not copy
the input SRTs line by line.

## Content policy

- Every dialogue event must be represented in the generated story. The model
  may paraphrase its meaning and say who said what; it does not need to repeat
  every spoken word.
- Adjacent dialogue events may be grouped into one narrator beat.
- Scene-only events are optional context. Keep only plot-changing visual
  beats, write them briefly, or omit ordinary silent scenery. The editor can
  remove optional scene-only VO without breaking dialogue coverage.
- The output language is Burmese by default, even when the input dialogue is
  Chinese or English. Use stable Burmese names/descriptors and do not invent
  plot facts.

## TTS pacing contract

This skill uses the Burmese calibration from the AMTrecap local reference:

- **20–24 Unicode codepoints per second**;
- default calculation target **21.6 codepoints/second**;
- count with Python `len()` after TTS cleanup, never UTF-8 bytes.

Each dialogue event is sent to the LLM with an available VO window and a
character budget. The final SRT uses explicit end times calculated from the
narration text length and the target CPS. Overlapping dialogue beats are
combined; an optional scene-only beat that collides with required dialogue is
dropped instead of causing timing drift.

## Agent role — run scripts only

Run the commands below, read each JSON result, and verify `ok`. The LLM story
writing happens inside `story_srt.py`; the agent does not hand-write the
narration or SRT timestamps. Ask the user only when an input, LLM key/model,
or access permission is genuinely missing.

## Pipeline

Temporary work directory: `.work`. Final output: `<Title> VO.srt`.

### 0. Dependency/config check (mandatory)

```bash
python3 scripts/check_deps.py --ping
```

This is stdlib-only and checks the OpenAI-compatible LLM configuration. If
`llm_key_set: false`, ask for the key/model and save them to `~/.llm_env`:

```text
LLM_API_BASE=https://openrouter.ai/api/v1
LLM_API_KEY=...
LLM_MODEL=...
```

Re-run the check until `ok: true`.

### 1. Resolve the two SRT inputs

```bash
mkdir -p .work
python3 scripts/resolve_inputs.py \
    --scene "<Movie scene.srt>" \
    --audio "<Movie audio.srt>" \
    --title "<Movie>" > .work/inputs.json
```

The files can come from any session. Auto-discovery is also supported:

```bash
python3 scripts/resolve_inputs.py --title "<Movie>" > .work/inputs.json
```

The JSON identifies the scene/audio files, source language, and entry counts.
If both sibling files were accidentally named `<Movie>.srt`, rename them or
pass explicit paths before continuing.

### 2. Merge to an ID-tagged timeline

```bash
python3 scripts/merge_timeline.py --inputs .work/inputs.json
```

This writes `.work/story/` with `movie.json`, `timeline.json`, and 10-minute
`chunk_NN.json` files. Every source event receives an ID. Timestamps remain in
the timeline; the LLM only returns IDs.

### 3. Generate Burmese storyteller narration

```bash
python3 scripts/story_srt.py \
    --title "<Movie>" \
    --out "<Movie> VO.srt"
```

The script performs:

1. Chunk pass: natural Burmese recap narration, mandatory dialogue coverage,
   concise/optional scene beats, and timing budgets.
2. Dialogue repair pass when a model misses a required dialogue ID.
3. Consolidation pass: consistent character names, smooth flow, selective
   scene beats, and a Burmese hook that replaces the first 10 seconds.
4. Mechanical assembly: source IDs map to source anchors; end times are
   calculated from Burmese text length at the configured TTS speed.
5. Verification: dialogue coverage, fallback count, scene-only counts,
   effective CPS, hook fit, and timing violations are printed as JSON and
   saved to `.work/story/verify.json`.

Default timing flags:

```bash
--cps-min 20 --cps-max 24 --cps-target 21.6 --hook-seconds 10
```

Use another CPS range only for a different TTS voice. `--language` or
`--output-language` can override the target label, but Burmese is the default.
Useful existing flags include `--model`, `--force`, `--parallel`,
`--max-tokens-chunk`, `--max-tokens-consolidate`, and `--no-consolidate`.

A successful final JSON has `ok: true`, full dialogue coverage, no raw
fallback lines, and no timing violations. If it returns non-zero, inspect
`verify.json`; the SRT is left in place so the model output and timing can be
reviewed before rerunning with `--force` or a stronger model.

### 4. Cleanup

```bash
rm -rf .work
ls
```

Delete only temporary work. Never modify the input SRTs. Keep the final VO SRT
and the source SRTs under distinct names.

### 5. Deliver

Present `<Title> VO.srt` and report:

- source and output language;
- entry count and estimated speech seconds;
- Burmese CPS range/target;
- dialogue coverage percentage and raw fallback count;
- hook fit and any scene-only lines skipped for timing.

## Troubleshooting

- **Missing Burmese dialogue coverage:** inspect `fallback_lines`; rerun with
  `--force` or a stronger model. Raw fallback lines are marked so no required
  spoken event disappears silently.
- **Timing violation / hook too long:** use the report's entry and character
  counts; rerun with a stronger model or adjust `--cps-target` only when the
  selected TTS voice truly differs. Do not pad optional scene lines.
- **LLM 401/402/403:** fix `~/.llm_env` key/billing; do not repeatedly retry.
- **429/rate limits:** keep `--parallel 1`, wait, and rerun; saved chunks
  resume automatically unless `--force` is used.
- **Only one input found:** pass both `--scene` and `--audio` explicitly.
- **Wrong source language:** pass `--language` to `merge_timeline.py`; this
  changes source context, while final narration remains Burmese by default.
- **`hook: false`:** rerun without `--no-consolidate`; the hook is generated
  during consolidation.

## Run book

| Step | Command | Produces |
|---|---|---|
| 0 deps | `python3 scripts/check_deps.py --ping` | LLM config JSON |
| 1 inputs | `python3 scripts/resolve_inputs.py ... > .work/inputs.json` | input JSON |
| 2 timeline | `python3 scripts/merge_timeline.py --inputs .work/inputs.json` | event IDs + chunks |
| 3 story | `python3 scripts/story_srt.py --title ... --out ...` | Burmese VO SRT + verify JSON |
| 4 cleanup | `rm -rf .work && ls` | clean deliverable area |
| 5 deliver | present the VO SRT | — |

## Files

- `scripts/check_deps.py` — dependency/config check and API ping
- `scripts/resolve_inputs.py` — locate/classify scene and audio SRTs
- `scripts/merge_timeline.py` — assign event IDs and make chunks
- `scripts/story_srt.py` — Burmese LLM pass, dialogue repair, consolidation,
  TTS timing, assembly, and verification
- `scripts/srtutil.py` — SRT helpers, TTS cleanup, Unicode counting
- `references/story-prompt.md` — exact Burmese narrator prompt
- `references/usage-notes.md` — CPS calibration, architecture, and limits
