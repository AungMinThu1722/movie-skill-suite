#!/usr/bin/env python3
"""
make_frames.py — sample evenly spaced frames from a video (default: 2 per
minute = one frame every 30 s) and write them as individual, full-width
JPEG images for ONE-BY-ONE visual review by an agent.

Videos LONGER than --part-minutes (default 15) are split automatically:
every part gets its own folder with its own frames + manifest, so each part
is a self-contained work package that can be handed to a sub-agent as-is.

Layout
  ≤ part-minutes (single run):
    <out-dir>/video_info.json
    <out-dir>/manifest.json
    <out-dir>/frame_0001_00m00s.jpg ...

  > part-minutes (parts mode):
    <out-dir>/video_info.json
    <out-dir>/parts.json                <- the plan: read this to dispatch
    <out-dir>/part1/manifest.json         one sub-agent per part folder
    <out-dir>/part1/frame_*.jpg
    <out-dir>/part2/...

The script prints a single PLAN JSON line as its last stdout line — parse
that to decide single vs sub-agent delegation:

  PLAN: {"mode": "parts", "out_dir": "...", "total_segments": 60,
         "total_parts": 4, "frames_per_minute": 2,
         "parts": [{"part": 1, "folder": "...", "segments": [1, 15],
                    "frames": 30}, ...]}

manifest.json holds, per 60 s segment: exact start/end seconds and the
frame files belonging to it with their exact timestamps. make_srt.py takes
its timestamps from the manifest — no timestamp is ever hand-written.

Dependencies: ffmpeg + ffprobe on PATH (system package or static build).
No Python dependencies.

Usage:
  python3 make_frames.py /path/to/video.mp4
  python3 make_frames.py video.mp4 --out-dir .work/frames \
      --frames-per-minute 2 --frame-width 960 --part-minutes 15
"""

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def fmt_time(t: float) -> str:
    """Seconds -> 'M:SS' (minutes may exceed 60)."""
    t = max(0.0, float(t))
    m, s = divmod(int(round(t)), 60)
    return f"{m}:{s:02d}"


def frame_tag(t: float) -> str:
    """Seconds -> filename-safe time tag, e.g. 3:30 -> '03m30s'."""
    t = max(0.0, float(t))
    m, s = divmod(int(round(t)), 60)
    return f"{m:02d}m{s:02d}s"


def run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe_video(video: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(video),
    ]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()}")
    data = json.loads(r.stdout)

    vstream = next((s for s in data.get("streams", [])
                    if s.get("codec_type") == "video"), None)
    if vstream is None:
        raise RuntimeError("No video stream found in this file.")

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or 0.0)
    if duration <= 0:
        duration = float(vstream.get("duration") or 0.0)

    num, _, den = (vstream.get("avg_frame_rate") or "0/1").partition("/")
    try:
        fps = (float(num) / float(den)) if den else 0.0
    except ValueError:
        fps = 0.0

    return {
        "path": str(video),
        "container": fmt.get("format_name"),
        "duration_seconds": round(duration, 3),
        "width": int(vstream.get("width") or 0),
        "height": int(vstream.get("height") or 0),
        "fps": round(fps, 3),
        "video_codec": vstream.get("codec_name"),
        "size_bytes": int(fmt.get("size") or 0),
    }


def build_segments(duration: float, seg_seconds: float) -> list:
    """Segments as (start, end). A trailing stub under 2 s is merged into the
    previous segment so short videos don't get a 1-frame segment."""
    segs = []
    t = 0.0
    while t < duration - 0.25:
        segs.append((t, min(t + seg_seconds, duration)))
        t += seg_seconds
    if len(segs) > 1 and (segs[-1][1] - segs[-1][0]) < 2.0:
        prev = segs[-2]
        segs[-2] = (prev[0], segs[-1][1])
        segs.pop()
    return segs


# --------------------------------------------------------------------------- #
# frame extraction
# --------------------------------------------------------------------------- #

def extract_frame(video: Path, t: float, width: int, height: int,
                  quality: int, out_path: Path) -> bool:
    """Extract ONE frame at second t (fast seek) as a JPEG. Returns True if
    a frame file was produced."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{t:.3f}", "-i", str(video),
        "-vf", f"scale={width}:{height}",
        "-frames:v", "1", "-q:v", str(quality), str(out_path),
    ]
    r = run(cmd)
    return r.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="path to the video file")
    ap.add_argument("--out-dir", default=None,
                    help="output directory (default: <video folder>/frames)")
    ap.add_argument("--frames-per-minute", type=int, default=2,
                    help="frames sampled per 60 s segment (default: 2 = "
                         "one frame every 30 s)")
    ap.add_argument("--frame-width", type=int, default=960,
                    help="target width of the long edge of a frame "
                         "(default: 960)")
    ap.add_argument("--part-minutes", type=int, default=15,
                    help="videos longer than this many minutes are split "
                         "into per-part folders (default: 15)")
    ap.add_argument("--jpeg-quality", type=int, default=2,
                    help="ffmpeg -q:v value, 2 = high, 5 = lower "
                         "(default: 2)")
    args = ap.parse_args()

    if not 1 <= args.frames_per_minute <= 6:
        print("ERROR: --frames-per-minute must be 1..6", file=sys.stderr)
        return 2

    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        print(f"ERROR: video file not found: {video}", file=sys.stderr)
        return 2

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"ERROR: '{tool}' not found on PATH. Install ffmpeg first.",
                  file=sys.stderr)
            return 2

    info = probe_video(video)
    duration = info["duration_seconds"]
    if duration <= 0:
        print("ERROR: could not determine video duration.", file=sys.stderr)
        return 2

    # frame size: keep the long edge at --frame-width, never upscale
    vw, vh = info["width"], info["height"]
    if vw >= vh:
        fw = min(args.frame_width, vw) or args.frame_width
        fh = max(64, round(fw * vh / vw))
    else:
        fh = min(args.frame_width, vh) or args.frame_width
        fw = max(64, round(fh * vw / vh))
    fw -= fw % 2  # even dimensions (yuv420-friendly)
    fh -= fh % 2

    out_dir = (Path(args.out_dir).expanduser().resolve()
               if args.out_dir else video.parent / "frames")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "video_info.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8")

    fpm = args.frames_per_minute
    step = 60.0 / fpm
    seg_seconds = 60.0
    segments = build_segments(duration, seg_seconds)
    total_segments = len(segments)

    # ---- parts plan -------------------------------------------------------
    segs_per_part = max(1, args.part_minutes)   # segments are 60 s each
    parts_mode = duration > segs_per_part * seg_seconds
    total_parts = (math.ceil(total_segments / segs_per_part)
                   if parts_mode else 1)

    print(f"Video: {video.name}  ({fmt_time(duration)}, "
          f"{vw}x{vh}, {info['fps']} fps, {info['video_codec']})")
    print(f"Sampling: {fpm} frame(s)/min (every {step:.0f} s), "
          f"{total_segments} minute-segment(s) total")
    if parts_mode:
        print(f"Duration > {args.part_minutes} min -> PARTS mode: "
              f"{total_parts} part folder(s) of ≤ {args.part_minutes} min "
              f"(one sub-agent per part)")
    else:
        print("Duration ≤ 15 min -> SINGLE mode (one folder, no delegation "
              "needed)")
    print(f"Output:  {out_dir}\n")

    plan_parts = []
    gframe = 0  # global frame counter (1-based)

    for part in range(1, total_parts + 1):
        a = (part - 1) * segs_per_part + 1
        b = min(part * segs_per_part, total_segments)
        folder = out_dir if not parts_mode else out_dir / f"part{part}"
        folder.mkdir(parents=True, exist_ok=True)

        seg_records = []
        part_frames = 0

        for idx in range(a - 1, b):
            start, end = segments[idx]
            dur = end - start
            frames = []
            for i in range(fpm):
                t = start + i * step
                if t >= duration - 0.05:
                    break
                gframe += 1
                fname = f"frame_{gframe:04d}_{frame_tag(t)}.jpg"
                fpath = folder / fname
                if extract_frame(video, t, fw, fh, args.jpeg_quality, fpath):
                    frames.append({
                        "file": fname,
                        "seconds": round(t, 2),
                        "time": fmt_time(t),
                    })
                    part_frames += 1
                else:
                    print(f"  WARNING: no frame at {fmt_time(t)} "
                          f"(segment {idx + 1})")

            seg_records.append({
                "segment_index": idx + 1,
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "frames": frames,
            })
            n_f = len(frames)
            note = "" if n_f == fpm else f"  ({n_f}/{fpm} frames)"
            print(f"  seg {idx + 1:02d}  {fmt_time(start)}-"
                  f"{fmt_time(end)}  {n_f} frame(s)  "
                  f"[{folder.name}]{note}")

        manifest = {
            "video": str(video),
            "video_info": info,
            "mode": "parts" if parts_mode else "single",
            "part": part,
            "total_parts": total_parts,
            "frames_per_minute": fpm,
            "frame_interval_seconds": round(step, 2),
            "segment_seconds": seg_seconds,
            "total_segments": total_segments,
            "range": [a, b],
            "segments": seg_records,
        }
        (folder / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")

        plan_parts.append({
            "part": part,
            "folder": str(folder),
            "segments": [a, b],
            "frames": part_frames,
        })
        print(f"\n  -> {folder.name}: segments {a}-{b}, "
              f"{part_frames} frame(s), manifest.json written\n")

    plan = {
        "video": str(video),
        "mode": "parts" if parts_mode else "single",
        "out_dir": str(out_dir),
        "duration_seconds": info["duration_seconds"],
        "total_segments": total_segments,
        "total_parts": total_parts,
        "frames_per_minute": fpm,
        "part_minutes": args.part_minutes if parts_mode else None,
        "parts": plan_parts,
    }
    (out_dir / "parts.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8")

    total_frames = sum(p["frames"] for p in plan_parts)
    print(f"Done. {total_segments} segment(s), {total_frames} frame(s) "
          f"in {total_parts} folder(s) under {out_dir}")
    print("Plan file: parts.json")
    print("PLAN: " + json.dumps(plan))
    print("\nNext steps:")
    if parts_mode:
        print("  - Read references/subagent-brief.md and dispatch ONE "
              "sub-agent per part folder (parallel or sequential, as your "
              "environment allows).")
        print("  - Each part N -> .work/parts/partN.srt; merge all with "
              "merge_srt.py when every part exists.")
    else:
        print("  - Single run: follow SKILL.md steps 3-5 yourself "
              "(view frames one by one per references/vision-prompt.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
