#!/usr/bin/env python3
"""
make_srt.py — merge per-minute script text into a properly formatted .srt.

Usage:
  python3 make_srt.py <manifest.json> <script.txt> --out "Movie Name.srt"
  python3 make_srt.py manifest.json script.txt --out out.srt --bom

Input format (script.txt):
  - ONE LINE PER SEGMENT (minute), in manifest (time) order. Each line is
    one phrase entry for one segment (short phrases — keep it to one line).
  - Blank lines and lines starting with '#' are ignored — use them for
    metadata such as '# language: ja' (the movie's original language the
    text is written in).
  - The LLM writes ONLY the entry text. All SRT numbering and
    timestamps are generated here from manifest.json, so timestamps can
    never be hand-typed or wrong.

Manifest: the manifest.json written by make_frames.py (its "segments"
list carries each segment's exact start/end seconds; a legacy "grids"
key is still accepted).

Output: a UTF-8 .srt file with one entry per segment
(00:00:00,000 --> 00:01:00,000 style).
"""

import argparse
import json
import sys
from pathlib import Path


def ts(t: float) -> str:
    """seconds -> SRT timestamp HH:MM:SS,mmm"""
    ms = max(0, int(round(float(t) * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def read_paragraphs(path: Path) -> list:
    """One non-empty, non-comment line = one segment entry."""
    paras = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        paras.append(" ".join(ln.split()))
    return paras


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", help="manifest.json from make_frames.py")
    ap.add_argument("script_text", help="script.txt with one paragraph per segment")
    ap.add_argument("--out", required=True, help='output .srt path (e.g. "Movie Name.srt")')
    ap.add_argument("--bom", action="store_true",
                    help="write a UTF-8 BOM (helps some players with CJK/other scripts)")
    args = ap.parse_args()

    man = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    segs = man.get("segments") or man.get("grids") or []
    if not segs:
        print("ERROR: manifest has no segments", file=sys.stderr)
        return 1

    paras = read_paragraphs(Path(args.script_text))
    n = len(segs)
    if len(paras) != n:
        print(f"WARNING: {len(paras)} text paragraph(s) but {n} segments — "
              f"missing entries will be left empty.", file=sys.stderr)

    entries = []
    for i, s in enumerate(segs):
        text = paras[i] if i < len(paras) else "(no script text provided)"
        entries.append(
            f"{i + 1}\n{ts(s['start_seconds'])} --> {ts(s['end_seconds'])}\n{text}\n")
    data = "\n".join(entries)
    if args.bom:
        data = "\ufeff" + data
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(data, encoding="utf-8")
    print(f"wrote {out} — {n} entries, "
          f"cover {ts(segs[0]['start_seconds'])} to {ts(segs[-1]['end_seconds'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
