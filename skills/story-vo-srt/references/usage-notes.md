# Story VO SRT — Design and LLM Usage Notes

## What this skill does

The skill consumes two SRTs from any session:

- **video scene script:** visual evidence and important scene beats;
- **audio dialogue SRT:** word-timed spoken events.

It produces a **Burmese TTS-ready storyteller SRT**. It does not copy the
source SRTs as a transcript. Every dialogue event is required in the story
pass, but adjacent dialogue may be paraphrased and grouped. Scene-only events
are optional, concise context because the editor may remove those stretches.

## Burmese TTS calibration

The reference AMTrecap local skill calibrates Burmese narration at:

- minimum: **20 Unicode codepoints/second**;
- maximum: **24 Unicode codepoints/second**;
- default duration target: **21.6 codepoints/second**.

The implementation uses Python `len(text)` after TTS cleanup. It never uses
UTF-8 byte counts. The model receives each dialogue event's available VO
window and character range, and `story_srt.py` calculates explicit SRT end
times from the final text length and target CPS.

Useful overrides:

```bash
python3 scripts/story_srt.py \
    --cps-min 20 --cps-max 24 --cps-target 21.6
```

The defaults are calibrated for Burmese. Use different CPS values only when
the selected TTS voice is not Burmese.

## LLM API

Config resolution: environment variables → `~/.llm_env` → CLI flags:

- `LLM_API_BASE` (default `https://openrouter.ai/api/v1`)
- `LLM_API_KEY`
- `LLM_MODEL`

Calls use `POST {base}/chat/completions` with an OpenAI-compatible payload.
Free-tier models run sequentially by default and retry transient 429/network
errors; 401/402/403 errors fail fast.

## Why the pipeline has two LLM passes

- **Chunk pass:** each 10-minute chunk sees source dialogue/scene IDs, Burmese
  character budgets, and continuity state. It must cover every dialogue ID,
  while ordinary scene-only beats may be omitted.
- **Consolidation pass:** character names and phrasing are unified across
  chunks. It retains all required dialogue IDs, keeps only useful scene beats,
  and writes the Burmese hook.
- **Mechanical assembly:** IDs map back to original source anchors. The LLM
  never types timestamps. SRT durations are calculated from `len(text)` and
  the CPS target, overlapping dialogue beats are grouped, and optional scene
  beats that collide with required dialogue are dropped.

## Fallbacks and verification

If the model misses a dialogue ID, the script makes a small repair call. If
that repair also fails, the original source line is inserted as a marked raw
fallback so a spoken beat is never silently lost. The final `verify.json` and
stdout JSON report:

- dialogue total and coverage percentage;
- raw fallback count;
- Burmese output language;
- narration characters and estimated speech seconds;
- effective CPS and timing violations;
- optional scene lines kept/skipped;
- hook length and whether it fits its opening window.

A non-zero exit indicates missing dialogue coverage, an unrepaired raw
fallback, a timing violation, or a hook that does not fit its opening window;
the SRT/report are still left in place for inspection.

## Standalone contract

Inputs are explicit paths or auto-discovered by `resolve_inputs.py`; the input
format remains this suite's scene SRT + audio SRT, not the AMTrecap local
skill's visual-timeline format. Keep the two sibling SRTs under distinct names
when they share a folder. Temporary `.work` data is removed after delivery.
