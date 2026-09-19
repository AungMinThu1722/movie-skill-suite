#!/usr/bin/env python3
"""
resolve_inputs.py — locate and classify the two input SRT files.

The skill is STANDALONE: it accepts files from any session/source.
  - explicit:  --scene <path> --audio <path>
  - auto:      --title "<Movie Name>"  -> scans the current folder for
    *.srt candidates and classifies each by structure:
      * scene-script-like: few entries, long duration (~1 entry/minute,
        mean duration >= 20s)
      * audio-like:        many entries, short duration (mean <= 15s,
        >= 15 entries)

Prints ONE JSON object:
  {"scene_srt": "...", "audio_srt": "...", "title": "...",
   "scene_entries": 4, "audio_entries": 39, "audio_duration_s": 146.0,
   "language": "zh (Chinese)"}

Exits 1 with a human-readable reason when the pair cannot be resolved
(e.g. only one suitable file found).
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from srtutil import parse_srt, guess_lang  # noqa: E402


def classify(entries: list) -> str:
    if not entries:
        return "empty"
    mean = sum(e["end"] - e["start"] for e in entries) / len(entries)
    if len(entries) >= 15 and mean <= 15:
        return "audio"
    if mean >= 20:
        return "scene"
    if len(entries) >= 15:
        return "audio"   # many short-ish entries -> treat as audio
    return "scene"       # few long entries -> treat as scene


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default=None, help="path to the scene-script .srt")
    ap.add_argument("--audio", default=None, help="path to the audio (dialogue) .srt")
    ap.add_argument("--title", default=None, help="movie title (auto mode / naming)")
    ap.add_argument("--cwd", default=".", help="folder to scan in auto mode")
    args = ap.parse_args()

    cwd = Path(args.cwd).expanduser().resolve()
    scene = Path(args.scene).expanduser().resolve() if args.scene else None
    audio = Path(args.audio).expanduser().resolve() if args.audio else None

    if scene and audio:
        ok = all(p.is_file() for p in (scene, audio))
        if not ok:
            print("ERROR: explicit input path(s) missing on disk", file=sys.stderr)
            return 1
    else:
        cands = sorted(p for p in cwd.glob("*.srt")
                       if " VO." not in p.name and p.name.lower() != "readme")
        if not cands:
            print(f"ERROR: no .srt files found in {cwd} — pass --scene/--audio",
                  file=sys.stderr)
            return 1
        scored = []
        for p in cands:
            try:
                entries = parse_srt(p)
            except Exception as e:
                print(f"NOTE: skipping unparseable {p.name}: {e}", file=sys.stderr)
                continue
            scored.append((p, entries, classify(entries)))
        # title match boosts ranking
        if args.title:
            t = args.title.strip()
            def rank(item):
                p, _, kind = item
                return (0 if t in p.stem else 1, p.name)
            scored.sort(key=rank)

        found = {}
        for p, entries, kind in scored:
            if kind in ("audio", "scene") and kind not in found:
                found[kind] = (p, entries)
            if "audio" in found and "scene" in found:
                break

        if "scene" not in found or "audio" not in found:
            desc = "; ".join(f"{p.name} ({k}, {len(e)} entries)"
                             for p, e, k in scored) or "none"
            print(f"ERROR: could not find BOTH a scene-script SRT and an "
                  f"audio SRT in {cwd}. Candidates: {desc}\n"
                  f"Pass them explicitly: --scene <path> --audio <path>",
                  file=sys.stderr)
            return 1
        scene, scene_e = found["scene"]
        audio, audio_e = found["audio"]

    scene_e = parse_srt(scene) if scene_e is None else scene_e
    audio_e = parse_srt(audio) if audio_e is None else audio_e
    if not scene_e or not audio_e:
        print("ERROR: one of the input SRTs has no usable entries", file=sys.stderr)
        return 1

    title = args.title or audio.stem
    sample = " ".join(e["text"] for e in audio_e[:40])
    result = {
        "scene_srt": str(scene),
        "audio_srt": str(audio),
        "title": title,
        "scene_entries": len(scene_e),
        "audio_entries": len(audio_e),
        "audio_duration_s": round(max(e["end"] for e in audio_e), 1),
        "language": guess_lang(sample),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
