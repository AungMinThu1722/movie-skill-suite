# AssemblyAI — Usage Notes (for the agent)

## API shape (verified 2026-09)

- Base URL: `https://api.assemblyai.com/v2` (EU: `api.eu.assemblyai.com`)
- Auth: `Authorization: <API key>` header (SDK handles it)
- Python SDK: `pip install assemblyai` (v1.5.x)
  - `from assemblyai.prerecorded.v2 import Transcriber, TranscriptionConfig`
  - `Transcriber(api_key=...).transcribe(path_or_url, config=...)` is ONE
    blocking call: uploads the local file (POST /v2/upload), submits the
    job (POST /v2/transcript), and polls until completed.
  - `TranscriptionConfig(speech_models=[...], language_code="zh" |
    language_detection=True, speaker_labels=...)`
  - `transcript.export_subtitles_srt(chars_per_caption=32)` /
    `export_subtitles_vtt()` — native SRT/VTT with original timestamps.
  - `transcript.words` (start/end/confidence), `transcript.get_sentences()`,
    `transcript.get_paragraphs()`, `transcript.language_code`,
    `transcript.duration`, `transcript.delete_by_id(transcript.id)`
- REST equivalents: POST `/v2/upload`, POST `/v2/transcript` (with
  `audio_url`), GET `/v2/transcript/{id}`, GET
  `/v2/transcript/{id}/srt?chars_per_caption=32`,
  GET `/v2/transcript/{id}/vtt`, DEL `/v2/transcript/{id}`.

## Models & languages

- `universal-3-5-pro` — best accuracy, 18 languages (incl. `zh` Mandarin,
  `en`, `ja`, `vi`, `hi`, ...). Supported codes: en, en_au, en_uk, en_us,
  es, fr, de, it, pt, ar, da, nl, fi, he, hi, ja, zh, no, sv, tr, vi.
- `universal-2` — 99 languages (incl. Burmese `my` — "fair accuracy" tier,
  WER >50%; Thai `th`, Khmer `km`, Lao `lo`, etc.).
- Pattern used by `transcribe_srt.py`: `speech_models=["universal-3-5-pro",
  "universal-2"]` — with `language_detection=True` the platform routes to
  the best model; with manual `language_code` the script falls back to
  `["universal-2"]` if the request is rejected with "not available in this
  language".
- Features not supported for a language: rejected up-front with manual
  `language_code`, silently omitted with auto-detection (e.g. speaker
  labels may be unavailable for `my`).

## Billing & key

- Pay-as-you-go per second of audio; failed transcriptions are free.
- New accounts get $50 free credit (pre-recorded STT).
- Key: dashboard → API keys; this skill reads it from
  `ASSEMBLYAI_API_KEY` env var or `~/.assemblyai_env`
  (`ASSEMBLYAI_API_KEY=...`). Never write the key into the work dir,
  the skill folder, or the .srt output.
- 401 → bad/expired key. Quota/balance errors → tell the user to top up.

## Practical limits & tips

- Max ~5 h / 2 GB per file — no chunking needed for movies.
- Any container with an audio stream works (mp4, mkv, webm...); the script
  pre-extracts 16 kHz mono mp3 for speed and smaller upload.
- Audio with no speech → empty SRT error (reported clearly).
- `chars_per_caption` controls caption line length (default 32).
- Always log `transcript_id` in the JSON output — it is what support asks
  for and the only way to re-export the same transcript later.

## This skill's contract

- Output: `<Movie Name>.srt` — original spoken language, original
  timestamps. No translation, no paraphrasing, no LLM editing.
- Only skill files + the .srt remain after the run (`.work` deleted).
- If the input was a local file, the user's original media file must still
  exist after cleanup.
