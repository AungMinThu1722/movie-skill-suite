#!/usr/bin/env python3
"""
transcribe_srt.py — media file (or pre-extracted mp3) -> SRT via AssemblyAI.

Pipeline (all automatic):
  1. if input is a video file: extract audio to a 16 kHz mono mp3 (ffmpeg)
  2. upload + transcribe with the AssemblyAI Python SDK (one blocking call)
  3. export SRT — ORIGINAL spoken language, ORIGINAL timestamps (no
     translation, no re-timing, no LLM rewriting)
  4. delete the remote transcript (unless --keep-transcript)

Prints ONE JSON object on stdout:
  {"ok": true, "srt": "/abs/Movie Name.srt", "transcript_id": "...",
   "language_code": "zh", "language_auto_detected": true,
   "duration_seconds": 145.6, "entries": 87, "transcript_deleted": true}

API key resolution order:
  1. --api-key argument
  2. ASSEMBLYAI_API_KEY environment variable
  3. ~/.assemblyai_env  (line: ASSEMBLYAI_API_KEY=...)

Usage:
  python3 transcribe_srt.py /path/video.mp4 --title "Movie Name"
  python3 transcribe_srt.py /path/audio.mp3 --out "Movie Name.srt" --lang zh
  python3 transcribe_srt.py video.mp4 --title "Movie Name" --chars-per-caption 42
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac",
              ".webm", ".wma"}


def run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def load_api_key(cli_key: str = None) -> str:
    if cli_key:
        return cli_key.strip()
    env = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
    if env:
        return env
    env_file = Path.home() / ".assemblyai_env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ASSEMBLYAI_API_KEY="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    return val
    return ""


def extract_audio(media: Path, work: Path) -> Path:
    """Video (or any container) -> 16 kHz mono mp3 (STT-friendly)."""
    audio = work / "audio.mp3"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(media),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
        str(audio),
    ]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: "
                           f"{r.stderr.strip()[-400:]}")
    if not audio.is_file() or audio.stat().st_size < 1_000:
        raise RuntimeError("audio extraction produced no/empty output "
                           "(does the file have an audio stream?)")
    return audio


def transcribe(audio: Path, api_key: str, lang: str = None):
    """One blocking SDK call: upload + submit + poll. Returns (transcript,
    auto_detected: bool). Falls back to universal-2 when a manual language
    is unavailable on universal-3-5-pro."""
    from assemblyai.prerecorded.v2 import Transcriber, TranscriptionConfig

    models = ["universal-3-5-pro", "universal-2"]

    def attempt(models_to_use, **cfg):
        config = TranscriptionConfig(speech_models=models_to_use, **cfg)
        t = Transcriber(api_key=api_key, config=config).transcribe(str(audio))
        if t.status == "error":
            raise RuntimeError(f"Transcription failed: {t.error}")
        return t

    if lang:
        try:
            return attempt(models, language_code=lang), False
        except RuntimeError as e:
            if "not available" in str(e).lower():
                return attempt(["universal-2"], language_code=lang), False
            raise
    return attempt(models, language_detection=True), True


def count_entries(srt: str) -> int:
    return len(re.findall(r"\n\d+\n\d{2}:", "\n" + srt)) or \
        (1 if re.match(r"^1\n\d{2}:", srt.strip()) else 0)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", help="video file (audio is extracted) or audio file")
    ap.add_argument("--title", default=None,
                    help="movie title; output defaults to '<title>.srt'")
    ap.add_argument("--out", default=None,
                    help="output .srt path (default: <title or media stem>.srt)")
    ap.add_argument("--lang", default=None,
                    help="force a language code (e.g. zh, en, my). "
                         "Omit to auto-detect (default)")
    ap.add_argument("--chars-per-caption", type=int, default=32,
                    help="max chars per SRT caption line (default: 32)")
    ap.add_argument("--api-key", default=None,
                    help="AssemblyAI API key (default: env var / "
                         "~/.assemblyai_env)")
    ap.add_argument("--work-dir", default=None,
                    help="temp dir for the extracted mp3 (default: "
                         "<media folder>/.work_audio)")
    ap.add_argument("--bom", action="store_true",
                    help="write a UTF-8 BOM (helps some players with CJK etc.)")
    ap.add_argument("--keep-transcript", action="store_true",
                    help="keep the transcript on AssemblyAI servers "
                         "(default: delete it after export)")
    args = ap.parse_args()

    media = Path(args.media).expanduser().resolve()
    if not media.is_file():
        print(f"ERROR: media file not found: {media}", file=sys.stderr)
        return 2

    api_key = load_api_key(args.api_key)
    if not api_key:
        print("ERROR: no AssemblyAI API key found (set ASSEMBLYAI_API_KEY, "
              "~/.assemblyai_env, or --api-key)", file=sys.stderr)
        return 2

    # The SDK's default client (used by e.g. Transcript.delete_by_id) reads
    # the global settings — set the key there too.
    import assemblyai as aai
    aai.settings.api_key = api_key

    work = (Path(args.work_dir).expanduser().resolve()
            if args.work_dir else media.parent / ".work_audio")
    work.mkdir(parents=True, exist_ok=True)

    extracted = None
    try:
        if media.suffix.lower() in AUDIO_EXTS:
            audio = media
        else:
            print(f"Extracting audio from {media.name} ...", file=sys.stderr)
            audio = extract_audio(media, work)
            extracted = audio

        print(f"Transcribing {audio.name} "
              f"({args.lang or 'auto-detect language'}) via AssemblyAI ...",
              file=sys.stderr)
        transcript, auto = transcribe(audio, api_key, lang=args.lang)

        srt = transcript.export_subtitles_srt(
            chars_per_caption=args.chars_per_caption)
        if not srt.strip():
            raise RuntimeError("transcription produced an empty SRT "
                               "(no speech detected?)")

        title = args.title or media.stem
        out = (Path(args.out).expanduser().resolve()
               if args.out else Path.cwd() / f"{title}.srt")
        out.parent.mkdir(parents=True, exist_ok=True)
        if args.bom:
            srt = "\ufeff" + srt
        out.write_text(srt, encoding="utf-8")

        deleted = True
        if args.keep_transcript:
            deleted = False
        else:
            for attempt in range(2):
                try:
                    transcript.delete_by_id(transcript.id)
                    break
                except Exception:
                    if attempt == 0:
                        time.sleep(3)
                    deleted = False

        jr = getattr(transcript, "json_response", None) or {}
        lang_code = getattr(transcript, "language_code", None) or \
            jr.get("language_code")
        duration = jr.get("audio_duration") or jr.get("duration")
        result = {
            "ok": True,
            "srt": str(out),
            "transcript_id": getattr(transcript, "id", None),
            "language_code": lang_code,
            "language_auto_detected": auto,
            "duration_seconds": duration,
            "entries": count_entries(srt),
            "transcript_deleted": deleted,
            "audio_used": str(audio),
        }
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        if extracted is not None:
            extracted.unlink(missing_ok=True)
        # remove the temp work dir if it is empty now
        try:
            if not any(work.iterdir()):
                work.rmdir()
        except OSError:
            pass

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
