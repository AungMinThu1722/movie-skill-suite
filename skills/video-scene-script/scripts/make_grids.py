#!/usr/bin/env python3
"""
make_grids.py — Split a video into time segments, sample evenly spaced frames
from each segment, and compose labeled frame grids (default: 3x3 per minute)
for visual review by an agent.

Outputs (in --out-dir, default: <video's folder>/scene_report):
  video_info.json   video metadata (duration, resolution, fps, codec)
  grid_01.png ...   one grid per segment; cells are chronological
                    (left -> right, top -> bottom), each labeled with its
                    approximate timestamp
  overview_01.png   one representative frame per segment, paged as 3x3 grids
  manifest.json     machine-readable index: files, segment ranges, label times

Dependencies:
  - ffmpeg + ffprobe on PATH (system package `ffmpeg`)
  - Python 3.8+, Pillow (optional — without it, grids are composed via
    ffmpeg hstack/vstack and carry no text labels)

Usage:
  python3 make_grids.py /path/to/video.mp4
  python3 make_grids.py video.mp4 --out-dir ./scene_report \
      --segment-seconds 60 --grid-cols 3 --grid-rows 3 --cell-width 480

Chunked runs (long videos): grid filenames always use the GLOBAL segment
number, so parts written into the same out-dir never collide.
  python3 make_grids.py video.mp4 --out-dir .work/grids \
      --from-segment 11 --to-segment 20 --part 2
  -> grids grid_11.png .. grid_20.png, manifest_part2.json,
     overview_part2_01.png, ...
"""

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def fmt_time(t: float) -> str:
    """Seconds -> 'M:SS' (minutes may exceed 60)."""
    t = max(0.0, float(t))
    m, s = divmod(int(round(t)), 60)
    return f"{m}:{s:02d}"


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
        # fall back to stream duration
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

def extract_segment_frames(video: Path, start: float, dur: float, n: int,
                           width: int, height: int, tmpdir: Path,
                           seg_idx: int) -> list:
    """Extract n evenly spaced frames from [start, start+dur)."""
    rate = n / max(dur, 1e-6)
    out = tmpdir / f"seg{seg_idx:03d}_%02d.png"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
        "-vf", f"fps={rate:.6f},scale={width}:-2",
        "-frames:v", str(n), str(out),
    ]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed for segment {seg_idx + 1} "
            f"({start:.1f}s-{start + dur:.1f}s): {r.stderr.strip()}")
    return sorted(tmpdir.glob(f"seg{seg_idx:03d}_*.png"))


# --------------------------------------------------------------------------- #
# grid composition
# --------------------------------------------------------------------------- #

def fit_image(img: Image.Image, cw: int, ch: int) -> Image.Image:
    """Resize to fit inside cw x ch, letterbox onto black."""
    img = img.convert("RGB")
    scale = min(cw / img.width, ch / img.height)
    nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (cw, ch), (0, 0, 0))
    canvas.paste(img, ((cw - nw) // 2, (ch - nh) // 2))
    return canvas


def get_font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def compose_grid_pil(frame_paths, labels, title, cell_w, cell_h,
                     cols, out_path: Path) -> bool:
    """Build the labeled grid with Pillow. Returns False if frames are missing
    and padding was needed (info only — grid is still written)."""
    n = len(frame_paths)
    rows = math.ceil(n / cols)
    title_h, label_h = 44, 30

    W = cols * cell_w
    H = title_h + rows * (cell_h + label_h)
    canvas = Image.new("RGB", (W, H), (15, 15, 15))
    draw = ImageDraw.Draw(canvas)
    f_title = get_font(22)
    f_label = get_font(16)

    # title bar
    draw.rectangle([0, 0, W, title_h], fill=(38, 38, 38))
    draw.text((14, (title_h - 22) / 2), title, fill=(240, 240, 240),
              font=f_title)

    padded = False
    for i in range(rows * cols):
        r, c = divmod(i, cols)
        x0 = c * cell_w
        y0 = title_h + r * (cell_h + label_h)

        if i < n:
            img = fit_image(Image.open(frame_paths[i]), cell_w, cell_h)
            canvas.paste(img, (x0, y0))
        else:
            padded = True
            ph = Image.new("RGB", (cell_w, cell_h), (24, 24, 24))
            dph = ImageDraw.Draw(ph)
            dph.text((14, cell_h // 2 - 10), "no frame",
                     fill=(110, 110, 110), font=f_label)
            canvas.paste(ph, (x0, y0))

        # label strip
        ly = y0 + cell_h
        draw.rectangle([x0, ly, x0 + cell_w, ly + label_h], fill=(0, 0, 0))
        text = fmt_time(labels[i]) if i < n else ""
        tw = draw.textlength(text, font=f_label)
        draw.text((x0 + (cell_w - tw) / 2, ly + 6), text,
                  fill=(255, 255, 255), font=f_label)

    canvas.save(out_path)
    return padded


def compose_grid_ffmpeg(frame_paths, cell_w, cell_h, cols, rows,
                        out_path: Path) -> None:
    """Fallback grid via ffmpeg hstack/vstack (no text labels).

    Missing cells are padded by duplicating the last real frame.
    """
    n = len(frame_paths)
    inputs = list(frame_paths)
    total = cols * rows
    # duplicate last frame for missing cells (harmless: appears only as pad)
    while len(inputs) < total:
        inputs.append(frame_paths[-1])

    parts = []
    for k in range(total):
        parts.append(
            f"[{k}:v]scale={cell_w}:{cell_h}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[v{k}]")
    row_parts = []
    for r in range(rows):
        ins = "".join(f"[v{r * cols + c}]" for c in range(cols))
        row_parts.append(f"{ins}hstack=inputs={cols}[r{r}]")
    parts += row_parts
    parts.append("".join(f"[r{r}]" for r in range(rows)) +
                 f"vstack=inputs={rows}[out]")

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for f in inputs:
        cmd += ["-i", str(f)]
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]",
            "-frames:v", "1", str(out_path)]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg grid compositing failed: {r.stderr.strip()}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="path to the video file")
    ap.add_argument("--out-dir", default=None,
                    help="output directory (default: <video folder>/scene_report)")
    ap.add_argument("--segment-seconds", type=float, default=60.0,
                    help="length of each segment, seconds (default: 60)")
    ap.add_argument("--grid-cols", type=int, default=3,
                    help="columns per grid (default: 3)")
    ap.add_argument("--grid-rows", type=int, default=3,
                    help="rows per grid (default: 3)")
    ap.add_argument("--cell-width", type=int, default=480,
                    help="target width of the long edge of a frame cell (default: 480)")
    ap.add_argument("--from-segment", type=int, default=None, metavar="N",
                    help="first segment to process, 1-based (chunked runs)")
    ap.add_argument("--to-segment", type=int, default=None, metavar="N",
                    help="last segment to process, 1-based, inclusive")
    ap.add_argument("--part", type=int, default=None, metavar="N",
                    help="part number for chunked runs — manifest is written "
                         "as manifest_partN.json, overview as overview_partN_*.png")
    ap.add_argument("--no-overview", action="store_true",
                    help="skip the overview grid")
    ap.add_argument("--no-pil", action="store_true",
                    help="force the ffmpeg-only grid path (test)")
    args = ap.parse_args()

    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        print(f"ERROR: video file not found: {video}", file=sys.stderr)
        return 2

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"ERROR: '{tool}' not found on PATH. Install ffmpeg first.",
                  file=sys.stderr)
            return 2

    use_pil = HAVE_PIL and not args.no_pil
    if not use_pil:
        print("NOTE: Pillow unavailable — grids will have no text labels.")

    n_frames = args.grid_cols * args.grid_rows
    info = probe_video(video)
    duration = info["duration_seconds"]
    if duration <= 0:
        print("ERROR: could not determine video duration.", file=sys.stderr)
        return 2

    # cell size: keep the long edge at --cell-width
    vw, vh = info["width"], info["height"]
    if vw >= vh:
        cell_w = args.cell_width
        cell_h = max(64, round(args.cell_width * vh / vw))
    else:
        cell_h = args.cell_width
        cell_w = max(64, round(args.cell_width * vw / vh))

    out_dir = (Path(args.out_dir).expanduser().resolve()
               if args.out_dir else video.parent / "scene_report")
    tmpdir = out_dir / "_tmp_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpdir.mkdir(parents=True, exist_ok=True)

    segments = build_segments(duration, args.segment_seconds)
    total_segments = len(segments)
    rows_needed = math.ceil(n_frames / args.grid_cols)

    # selected range (1-based, inclusive); grid files keep the GLOBAL index
    a = max(1, args.from_segment or 1)
    b = min(total_segments, args.to_segment or total_segments)
    if a > total_segments or a > b:
        print(f"ERROR: segment range {a}-{b} outside 1-{total_segments}",
              file=sys.stderr)
        return 2
    selected = [(idx, seg) for idx, seg in enumerate(segments)
                if a - 1 <= idx <= b - 1]

    (out_dir / "video_info.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8")

    grids = []
    overview_frames = []

    print(f"Video: {video.name}  ({fmt_time(duration)}, "
          f"{vw}x{vh}, {info['fps']} fps, {info['video_codec']})")
    print(f"Segments: {total_segments} total x {args.segment_seconds:.0f}s, "
          f"processing {a}-{b}"
          + (f"  [part {args.part}]" if args.part else "")
          + f", grid: {args.grid_cols}x{args.grid_rows} "
            f"({n_frames} frames/segment)")
    print(f"Output:  {out_dir}\n")

    for idx, (start, end) in selected:
        dur = end - start
        step = dur / n_frames
        frames = extract_segment_frames(
            video, start, dur, n_frames, cell_w, cell_h, tmpdir, idx)

        actual = len(frames)
        labels = [start + i * step for i in range(actual)]

        grid_path = out_dir / f"grid_{idx + 1:02d}.png"
        title = (f"Segment {idx + 1:02d}  |  {fmt_time(start)} - "
                 f"{fmt_time(end)}  |  {video.name}")

        if use_pil:
            compose_grid_pil(frames, labels, title, cell_w, cell_h,
                             args.grid_cols, grid_path)
        else:
            compose_grid_ffmpeg(frames, cell_w, cell_h,
                                   args.grid_cols, rows_needed, grid_path)

        grids.append({
            "file": grid_path.name,
            "segment_index": idx + 1,
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "frames": actual,
            "label_seconds": [round(t, 2) for t in labels],
        })

        # representative middle frame for the overview
        if actual > 0:
            overview_frames.append(frames[actual // 2])

        note = f" ({actual}/{n_frames} frames)" if actual < n_frames else ""
        print(f"  grid_{idx + 1:02d}.png   {fmt_time(start)} - "
              f"{fmt_time(end)}{note}")

    # ---- overview (one frame per segment, paged 3x3) ----
    prefix = f"part{args.part}_" if args.part else ""
    overview_files = []
    if not args.no_overview and overview_frames:
        per_page = args.grid_cols * args.grid_rows
        n_pages = math.ceil(len(overview_frames) / per_page)
        for page in range(n_pages):
            chunk = overview_frames[page * per_page:
                                    (page + 1) * per_page]
            chunk_grids = grids[page * per_page:(page + 1) * per_page]
            seg_labels = [g["start_seconds"] for g in chunk_grids]
            oname = f"overview_{prefix}{page + 1:02d}.png"
            opath = out_dir / oname
            otitle = (f"Overview page {page + 1}/{n_pages}  |  "
                      f"one frame per segment  |  {video.name}")
            if use_pil:
                compose_grid_pil(chunk, seg_labels, otitle, cell_w, cell_h,
                                 args.grid_cols, opath)
            else:
                compose_grid_ffmpeg(chunk, cell_w, cell_h,
                                    args.grid_cols,
                                    math.ceil(len(chunk) / args.grid_cols),
                                    opath)
            overview_files.append({
                "file": oname,
                "segments": [g["segment_index"] for g in chunk_grids],
            })
            print(f"  {oname}   segments "
                  f"{chunk_grids[0]['segment_index']}-"
                  f"{chunk_grids[-1]['segment_index']}")

    # ---- cleanup + manifest ----
    shutil.rmtree(tmpdir, ignore_errors=True)

    manifest = {
        "video": str(video),
        "video_info": info,
        "segment_seconds": args.segment_seconds,
        "grid": f"{args.grid_cols}x{args.grid_rows}",
        "labels": use_pil,
        "total_segments": total_segments,
        "range": [a, b],
        "part": args.part,
        "grids": grids,
        "overview": overview_files,
    }
    manifest_name = (f"manifest_part{args.part}.json"
                     if args.part else "manifest.json")
    (out_dir / manifest_name).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    first, last = grids[0]["segment_index"], grids[-1]["segment_index"]
    print(f"\nDone. {len(grids)} grid(s) (segments {first}-{last})"
          + (f", {len(overview_files)} overview page(s)" if overview_files else "")
          + f" written to {out_dir}")
    print(f"Manifest: {manifest_name}")
    print(f"Now read overview_{prefix}*.png, then grid_{first:02d}.png .. "
          f"grid_{last:02d}.png in order and write the per-minute script "
          f"text (one paragraph per segment, in the movie's original "
          f"language), then run make_srt.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
