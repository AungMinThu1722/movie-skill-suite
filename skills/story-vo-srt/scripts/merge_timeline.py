#!/usr/bin/env python3
"""
merge_timeline.py — merge the scene-script SRT and the audio SRT into one
ID-tagged event timeline, chunked for the LLM story pass.

Every event gets a stable ID (E0001, E0002, ...) in time order. Timestamps
live ONLY here — the LLM never writes timestamps; it references IDs.

Outputs (default in .work/story/):
  movie.json       title, language, duration, chunk plan
  chunk_01.json …  {index, range, prev_tail (last 20s of previous chunk),
                    events: [{id, t, t_end, type, text}]}

Usage:
  python3 merge_timeline.py --scene scene.srt --audio audio.srt --title "X"
  (or point at the .work/story/inputs.json produced by resolve_inputs.py
   with --inputs)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from srtutil import parse_srt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default=None)
    ap.add_argument("--audio", default=None)
    ap.add_argument("--inputs", default=None,
                    help="resolve_inputs.py JSON file (used if --scene/--audio "
                         "not given)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--language", default=None,
                    help="language label to pass to the LLM (default: auto)")
    ap.add_argument("--chunk-seconds", type=float, default=600.0,
                    help="story chunk length (default 600 = 10 min)")
    ap.add_argument("--tail-seconds", type=float, default=20.0,
                    help="overlap tail from the previous chunk (default 20)")
    ap.add_argument("--out-dir", default=".work/story")
    args = ap.parse_args()

    title = args.title
    scene_path = args.scene
    audio_path = args.audio
    language = args.language

    if not (scene_path and audio_path):
        if not args.inputs:
            print("ERROR: provide --scene/--audio or --inputs", file=sys.stderr)
            return 2
        d = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
        scene_path, audio_path = d["scene_srt"], d["audio_srt"]
        title = title or d.get("title")
        language = language or d.get("language")

    scene_e = parse_srt(scene_path)
    audio_e = parse_srt(audio_path)
    if not scene_e or not audio_e:
        print("ERROR: empty input SRT", file=sys.stderr)
        return 1

    events = []
    for e in audio_e:
        events.append({"t": e["start"], "t_end": e["end"],
                       "type": "dialogue", "text": e["text"]})
    for e in scene_e:
        events.append({"t": e["start"], "t_end": e["end"],
                       "type": "scene", "text": e["text"]})
    events.sort(key=lambda e: (e["t"], 0 if e["type"] == "dialogue" else 1))
    for i, e in enumerate(events, 1):
        e["id"] = f"E{i:04d}"

    duration = max(e["t_end"] for e in events)
    n_chunks = max(1, int(-(-int(duration) // int(args.chunk_seconds))))

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    prev_tail = []
    chunks_meta = []
    for c in range(1, n_chunks + 1):
        cs = (c - 1) * args.chunk_seconds
        ce = min(c * args.chunk_seconds, duration)
        chunk_events = [e for e in events if cs <= e["t"] < ce]
        chunk = {
            "index": c,
            "range": [round(cs, 1), round(ce, 1)],
            "prev_tail": prev_tail,
            "events": [{k: e[k] for k in ("id", "t", "t_end", "type", "text")}
                       for e in chunk_events],
        }
        p = out_dir / f"chunk_{c:02d}.json"
        p.write_text(json.dumps(chunk, ensure_ascii=False, indent=1),
                     encoding="utf-8")
        chunks_meta.append({"file": p.name, "range": chunk["range"],
                            "events": len(chunk_events)})
        prev_tail = [{"id": e["id"], "t": round(e["t"], 1), "type": e["type"],
                      "text": e["text"]} for e in chunk_events
                     if e["t"] >= ce - args.tail_seconds]

    movie = {
        "title": title or "movie",
        "language": language or "unknown (detect from text)",
        "duration_seconds": round(duration, 1),
        "chunk_seconds": args.chunk_seconds,
        "chunks": n_chunks,
        "scene_entries": len(scene_e),
        "audio_entries": len(audio_e),
        "scene_srt": str(Path(scene_path).resolve()),
        "audio_srt": str(Path(audio_path).resolve()),
    }
    (out_dir / "movie.json").write_text(
        json.dumps(movie, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "timeline.json").write_text(
        json.dumps({"events": [{k: e[k]
                                for k in ("id", "t", "t_end", "type", "text")}
                               for e in events]},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "out_dir": str(out_dir),
        "title": movie["title"],
        "language": movie["language"],
        "duration_seconds": movie["duration_seconds"],
        "events": len(events),
        "dialogue_events": len(audio_e),
        "scene_events": len(scene_e),
        "chunks": chunks_meta,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
