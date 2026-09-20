#!/usr/bin/env python3
"""
make_frames.py — scene-aware, dialogue-aware frame sampling for
video-scene-script.

The script makes one ffmpeg scene-detection pass, samples a uniform frame in
normal minutes, densifies long dialogue-free minutes, removes near-identical
thumbnails, and extracts the kept frames as individual JPEGs. Videos longer
than --part-minutes are split into self-contained part folders.

The last stdout line is always:
    PLAN: {<the exact JSON object written to parts.json>}

Dependencies: ffmpeg + ffprobe on PATH. Python is otherwise stdlib-only.
"""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path


SEGMENT_SECONDS = 60.0
THUMB_SIZE = 16 * 16
TIMESTAMP_RE = re.compile(
    r"(?P<h>\d+):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)
PTS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


# --------------------------------------------------------------------------- #
# generic helpers
# --------------------------------------------------------------------------- #


def fmt_time(seconds: float) -> str:
    """Return film time as M:SS (minutes are not wrapped at one hour)."""
    seconds = max(0.0, float(seconds))
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}:{secs:02d}"


def frame_tag(seconds: float) -> str:
    """Return the filename-safe MMmSSs time tag."""
    seconds = max(0.0, float(seconds))
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes:02d}m{secs:02d}s"


def run_text(cmd):
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def round_time(value: float) -> float:
    return round(float(value), 2)


def json_write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def error(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


# --------------------------------------------------------------------------- #
# video metadata and scene detection
# --------------------------------------------------------------------------- #


def parse_rate(value) -> float:
    if not value or value in ("N/A", "0/0"):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    if "/" in text:
        num, den = text.split("/", 1)
        try:
            denominator = float(den)
            return float(num) / denominator if denominator else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe_video(video: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(video),
    ]
    result = run_text(cmd)
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown ffprobe error"
        raise RuntimeError(f"ffprobe failed: {detail}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON: {exc}")

    video_stream = next(
        (stream for stream in data.get("streams", [])
         if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise RuntimeError("no video stream found in this file")

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or 0.0)
    if duration <= 0:
        duration = float(video_stream.get("duration") or 0.0)
    if duration <= 0:
        raise RuntimeError("could not determine video duration")

    fps = parse_rate(video_stream.get("avg_frame_rate"))
    if fps <= 0:
        fps = parse_rate(video_stream.get("r_frame_rate"))

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise RuntimeError("could not determine source video dimensions")

    try:
        size_bytes = int(fmt.get("size") or 0)
    except (TypeError, ValueError):
        size_bytes = 0

    return {
        "path": str(video),
        "container": fmt.get("format_name"),
        "duration_seconds": round(duration, 3),
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "video_codec": video_stream.get("codec_name"),
        "size_bytes": size_bytes,
    }


def detect_scenes(video: Path, threshold: float, duration: float) -> list:
    """Run the requested one-pass select/showinfo scene detector."""
    filter_expr = f"select='gt(scene,{threshold:g})',showinfo"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-nostdin",
        "-i", str(video), "-vf", filter_expr, "-an", "-f", "null", "-",
    ]
    result = run_text(cmd)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown ffmpeg error"
        raise RuntimeError(f"scene detection failed: {detail}")

    times = set()
    for match in PTS_RE.finditer(result.stderr):
        value = round_time(float(match.group(1)))
        if 0.0 <= value < duration:
            times.add(value)
        if len(times) >= 4000:
            break
    return sorted(times)[:4000]


def build_segments(duration: float) -> list:
    """Return 60-second segments, merging a final stub shorter than 2 s."""
    segments = []
    start = 0.0
    while start < duration:
        segments.append((start, min(start + SEGMENT_SECONDS, duration)))
        start += SEGMENT_SECONDS

    if (len(segments) > 1 and
            segments[-1][1] - segments[-1][0] < 2.0):
        previous_start = segments[-2][0]
        segments[-2] = (previous_start, segments[-1][1])
        segments.pop()
    return segments


def segment_for_time(segments: list, seconds: float):
    """Return a zero-based segment index for a time, or None at the end."""
    for index, (start, end) in enumerate(segments):
        if start <= seconds < end:
            return index
    return None


# --------------------------------------------------------------------------- #
# dialogue SRT and gap windows
# --------------------------------------------------------------------------- #


def srt_seconds(match: re.Match) -> float:
    groups = match.groupdict()
    return (
        int(groups["h"]) * 3600
        + int(groups["m"]) * 60
        + int(groups["s"])
        + int(groups["ms"]) / 1000.0
    )


def parse_srt(path: Path) -> list:
    """Return [(start, end, text), ...] from a normal SRT file."""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"cannot decode dialogue SRT as UTF-8: {exc}")

    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", raw.strip()):
        lines = block.splitlines()
        timing_index = next(
            (i for i, line in enumerate(lines) if "-->" in line), None
        )
        if timing_index is None:
            continue
        timing = lines[timing_index].split("-->", 1)
        if len(timing) != 2:
            continue
        start_match = TIMESTAMP_RE.search(timing[0])
        end_match = TIMESTAMP_RE.search(timing[1])
        if not start_match or not end_match:
            continue
        start = srt_seconds(start_match)
        end = srt_seconds(end_match)
        if end <= start:
            continue
        text = " ".join(lines[timing_index + 1:])
        text = re.sub(r"<[^>]*>", "", text)
        text = " ".join(text.split())
        cues.append((start, end, text))
    return sorted(cues, key=lambda cue: (cue[0], cue[1]))


def merged_dialogue_spans(cues: list, duration: float) -> list:
    spans = []
    for start, end, _text in cues:
        start = max(0.0, min(duration, start))
        end = max(0.0, min(duration, end))
        if end > start:
            spans.append((start, end))
    spans.sort()

    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def dialogue_gaps(cues: list, duration: float, minimum: float) -> list:
    """Find dialogue-free intervals of at least minimum seconds."""
    merged = merged_dialogue_spans(cues, duration)
    gaps = []
    cursor = 0.0
    for start, end in merged:
        if start > cursor and start - cursor >= minimum:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if duration > cursor and duration - cursor >= minimum:
        gaps.append((cursor, duration))
    return gaps


def overlaps(start: float, end: float, other_start: float, other_end: float) -> bool:
    return start < other_end and end > other_start


def clip_intervals(intervals: list, start: float, end: float) -> list:
    clipped = []
    for a, b in intervals:
        left, right = max(a, start), min(b, end)
        if right > left:
            clipped.append([round_time(left), round_time(right)])
    return clipped


def write_dialogue_file(path: Path, cues: list, range_start: float,
                        range_end: float) -> int:
    lines = []
    for start, end, text in cues:
        if not overlaps(start, end, range_start, range_end):
            continue
        left, right = max(start, range_start), min(end, range_end)
        lines.append(f"[{fmt_time(left)}-{fmt_time(right)}] {text}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""),
                    encoding="utf-8")
    return len(lines)


def is_gap_minute(start: float, end: float, gaps: list) -> bool:
    midpoint = start + (end - start) / 2.0
    return any(gap_start <= midpoint < gap_end
               for gap_start, gap_end in gaps)


# --------------------------------------------------------------------------- #
# sampling candidates
# --------------------------------------------------------------------------- #


def evenly_spaced(values: list, count: int) -> list:
    """Pick count values spanning a sorted list as evenly as possible."""
    if count <= 0:
        return []
    if len(values) <= count:
        return list(values)
    if count == 1:
        return [values[len(values) // 2]]
    indices = []
    for i in range(count):
        index = int(round(i * (len(values) - 1) / (count - 1)))
        if index not in indices:
            indices.append(index)
    return [values[index] for index in indices]


def candidate(seconds: float, segment_index: int, reason: str) -> dict:
    return {
        "seconds": round_time(seconds),
        "segment_index": segment_index,
        "reason": reason,
        "uniform": reason.endswith("uniform"),
    }


def make_uniforms(start: float, end: float, count: int,
                  scene_mode: bool) -> list:
    if scene_mode:
        return [start + (end - start) / 2.0]
    # Preserve v1's no-scene fallback: the first frame is at the segment
    # start, then one every 60/fpm seconds, capped by the segment end.
    step = SEGMENT_SECONDS / float(count)
    return [start + i * step for i in range(count)
            if start + i * step < end]


def make_gap_uniforms(start: float, end: float, count: int) -> list:
    # Centers of equal slots: four slots in a 60-second minute are 7.5,
    # 22.5, 37.5, and 52.5 seconds into that minute.
    return [start + (i + 0.5) * (end - start) / count
            for i in range(count)]


def select_candidates(segments: list, scene_times: list, gaps: list,
                      scene_mode: bool, uniform_per_minute: int,
                      scene_per_minute: int, gap_uniform: int,
                      gap_max_per_minute: int) -> list:
    scene_by_minute = {index: [] for index in range(len(segments))}
    if scene_mode:
        for seconds in scene_times:
            index = segment_for_time(segments, seconds)
            if index is not None:
                scene_by_minute[index].append(seconds)
        for index, cuts in list(scene_by_minute.items()):
            cuts = sorted(set(cuts))
            # Important: write the trimmed list back into the dictionary.
            scene_by_minute[index] = evenly_spaced(cuts, scene_per_minute)

    candidates = []
    for index, (start, end) in enumerate(segments):
        gap = is_gap_minute(start, end, gaps)
        if gap:
            uniforms = [candidate(t, index, "gap-uniform")
                        for t in make_gap_uniforms(start, end, gap_uniform)]
            cuts = [candidate(t, index, "gap-scene")
                    for t in scene_by_minute.get(index, [])]
            # The gap cap is a hard cap. Normally only uniforms need trimming
            # (gap-max defaults to 6 and scene-per defaults to 2), but also
            # trim cuts defensively for unusual flag combinations.
            if len(uniforms) + len(cuts) > gap_max_per_minute:
                cuts = cuts[:max(0, gap_max_per_minute - 1)]
                scene_by_minute[index] = [c["seconds"] for c in cuts]
                keep_uniforms = max(1, gap_max_per_minute - len(cuts))
                uniforms = evenly_spaced(uniforms, keep_uniforms)
                if len(uniforms) > gap_max_per_minute - len(cuts):
                    uniforms = uniforms[:gap_max_per_minute - len(cuts)]
            candidates.extend(uniforms)
            candidates.extend(cuts)
        else:
            uniforms = [candidate(t, index, "uniform")
                        for t in make_uniforms(
                            start, end, uniform_per_minute, scene_mode)]
            cuts = [candidate(t, index, "scene")
                    for t in scene_by_minute.get(index, [])]
            candidates.extend(uniforms)
            candidates.extend(cuts)

    candidates.sort(key=lambda item: (
        item["seconds"], 0 if item["uniform"] else 1
    ))

    # Remove exact timestamp duplicates within a minute, retaining a uniform
    # candidate over a scene candidate because of the sort order above.
    unique = []
    seen = set()
    for item in candidates:
        key = (item["segment_index"], item["seconds"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


# --------------------------------------------------------------------------- #
# thumbnail deduplication and extraction
# --------------------------------------------------------------------------- #


def thumbnail(video: Path, seconds: float) -> bytes:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{seconds:.3f}", "-i", str(video),
        "-frames:v", "1", "-vf", "scale=16:16", "-pix_fmt", "gray",
        "-f", "rawvideo", "-",
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode != 0 or len(result.stdout) < THUMB_SIZE:
        return b""
    return result.stdout[:THUMB_SIZE]


def mean_abs_difference(first: bytes, second: bytes) -> float:
    if not first or not second or len(first) != len(second):
        return float("inf")
    return sum(abs(a - b) for a, b in zip(first, second)) / len(first)


def deduplicate(video: Path, candidates: list, segment_count: int,
                keep_duplicates: bool) -> tuple:
    """Return (kept candidates, image-drop count, forced-minute count)."""
    if keep_duplicates:
        return candidates, 0, 0

    by_segment = {index: [] for index in range(segment_count)}
    for item in candidates:
        by_segment.setdefault(item["segment_index"], []).append(item)

    kept = []
    dropped = 0
    forced = 0
    last_thumb = None

    for segment_index in range(segment_count):
        group = by_segment.get(segment_index, [])
        group_kept = []
        for original in group:
            item = dict(original)
            item["_thumb"] = thumbnail(video, item["seconds"])
            thumb = item["_thumb"]
            if last_thumb is None:
                # The first readable or unreadable frame is retained; an
                # unreadable first thumb cannot become a comparison baseline.
                group_kept.append(item)
                if thumb:
                    last_thumb = thumb
                continue
            if not thumb:
                dropped += 1
                continue
            if mean_abs_difference(last_thumb, thumb) <= 2.0:
                dropped += 1
                continue
            group_kept.append(item)
            last_thumb = thumb

        if not group_kept and group:
            # A minute must never disappear. Prefer its first uniform frame,
            # then its first candidate, and keep it regardless of thumbnail.
            forced_source = next(
                (item for item in group if item["uniform"]), group[0]
            )
            forced_item = dict(forced_source)
            forced_item["_forced"] = True
            if "_thumb" not in forced_item:
                forced_item["_thumb"] = thumbnail(
                    video, forced_item["seconds"])
            group_kept.append(forced_item)
            forced += 1
            if forced_item["_thumb"]:
                last_thumb = forced_item["_thumb"]

        kept.extend(group_kept)

    kept.sort(key=lambda item: (
        item["seconds"], 0 if item["uniform"] else 1
    ))
    return kept, dropped, forced


def frame_size(info: dict, requested_long_edge: int) -> tuple:
    source_width, source_height = info["width"], info["height"]
    long_edge = min(requested_long_edge, max(source_width, source_height))

    def even_floor(value: float) -> int:
        value = int(math.floor(value))
        return value - (value % 2)

    if source_width >= source_height:
        width = even_floor(long_edge)
        height = even_floor(width * source_height / source_width)
    else:
        height = even_floor(long_edge)
        width = even_floor(height * source_width / source_height)

    if width < 2 or height < 2:
        raise RuntimeError("source video is too small for an even-sized frame")
    return width, height


def extract_frame(video: Path, seconds: float, width: int, height: int,
                  quality: int, output: Path) -> bool:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", f"{seconds:.3f}", "-i", str(video),
        "-vf", f"scale={width}:{height}", "-frames:v", "1",
        "-q:v", str(quality), str(output),
    ]
    result = run_text(cmd)
    return (result.returncode == 0 and output.is_file()
            and output.stat().st_size > 0)


def public_frame(item: dict, filename: str) -> dict:
    return {
        "file": filename,
        "seconds": item["seconds"],
        "time": fmt_time(item["seconds"]),
        "reason": item["reason"],
    }


# --------------------------------------------------------------------------- #
# command-line validation and pipeline
# --------------------------------------------------------------------------- #


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("video", help="path to the video file")
    ap.add_argument("--out-dir", default=None,
                    help="default: <video folder>/frames")
    ap.add_argument("--audio-srt", default=None,
                    help="dialogue SRT from the audio-srt skill")
    ap.add_argument("--part-minutes", type=int, default=15)
    ap.add_argument("--frame-width", type=int, default=960,
                    help="long-edge target; never upscales (default: 960)")
    ap.add_argument("--uniform-per-minute", type=int, default=1,
                    help="normal-minute uniform frames in scene mode (default: 1)")
    ap.add_argument("--scene-per-minute", type=int, default=2,
                    help="maximum detected cut frames per minute (default: 2)")
    ap.add_argument("--scene-threshold", type=float, default=0.20,
                    help="ffmpeg scene threshold (default: 0.20)")
    ap.add_argument("--no-scene", action="store_true",
                    help="disable scene detection and use uniform sampling")
    ap.add_argument("--frames-per-minute", type=int, default=None,
                    help="no-scene fallback frames/minute, 1..6 (default: 2)")
    ap.add_argument("--gap-min-seconds", type=float, default=45.0,
                    help="minimum dialogue-free gap length (default: 45)")
    ap.add_argument("--gap-uniform", type=int, default=4,
                    help="uniform frames per gap minute (default: 4)")
    ap.add_argument("--gap-max-per-minute", type=int, default=6,
                    help="hard maximum frames per gap minute (default: 6)")
    ap.add_argument("--jpeg-quality", type=int, default=2,
                    help="ffmpeg JPEG quality, 1..31 (default: 2)")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="disable 16x16 thumbnail deduplication")
    return ap


def validate_args(args) -> None:
    if args.part_minutes <= 0:
        raise ValueError("--part-minutes must be positive")
    if args.frame_width <= 0:
        raise ValueError("--frame-width must be positive")
    if args.uniform_per_minute <= 0:
        raise ValueError("--uniform-per-minute must be positive")
    if args.scene_per_minute < 0:
        raise ValueError("--scene-per-minute must be zero or greater")
    if not 0.0 <= args.scene_threshold <= 1.0:
        raise ValueError("--scene-threshold must be between 0 and 1")
    if args.frames_per_minute is not None and not args.no_scene:
        raise ValueError("--frames-per-minute is only valid with --no-scene")
    if args.frames_per_minute is not None and not 1 <= args.frames_per_minute <= 6:
        raise ValueError("--frames-per-minute must be 1..6")
    if args.gap_min_seconds < 0:
        raise ValueError("--gap-min-seconds must be zero or greater")
    if args.gap_uniform <= 0:
        raise ValueError("--gap-uniform must be positive")
    if args.gap_max_per_minute <= 0:
        raise ValueError("--gap-max-per-minute must be positive")
    if not 1 <= args.jpeg_quality <= 31:
        raise ValueError("--jpeg-quality must be 1..31")


def check_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(
                f"'{tool}' not found on PATH; install ffmpeg/ffprobe first"
            )


def clean_generated_frames(folder: Path) -> None:
    """Remove only files this script owns when reusing an output folder."""
    for path in folder.glob("frame_*.jpg"):
        if path.is_file():
            path.unlink()
    for name in ("manifest.json", "dialogue.txt"):
        path = folder / name
        if path.is_file():
            path.unlink()


def run_pipeline(args) -> dict:
    validate_args(args)
    check_tools()

    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        raise RuntimeError(f"video file not found: {video}")

    audio_srt = (Path(args.audio_srt).expanduser().resolve()
                 if args.audio_srt else None)
    if audio_srt is not None and not audio_srt.is_file():
        raise RuntimeError(f"dialogue SRT not found: {audio_srt}")

    info = probe_video(video)
    duration = info["duration_seconds"]
    segments = build_segments(duration)
    if not segments:
        raise RuntimeError("video contains no usable 60-second segment")

    cues = parse_srt(audio_srt) if audio_srt is not None else []
    gaps = (dialogue_gaps(cues, duration, args.gap_min_seconds)
            if audio_srt is not None else [])

    scene_mode = not args.no_scene
    scene_times = (detect_scenes(video, args.scene_threshold, duration)
                   if scene_mode else [])
    uniform_per_minute = (1 if scene_mode
                          else (args.frames_per_minute
                                if args.frames_per_minute is not None else 2))
    candidates = select_candidates(
        segments=segments,
        scene_times=scene_times,
        gaps=gaps,
        scene_mode=scene_mode,
        uniform_per_minute=uniform_per_minute,
        scene_per_minute=args.scene_per_minute,
        gap_uniform=args.gap_uniform,
        gap_max_per_minute=args.gap_max_per_minute,
    )
    kept, dedup_dropped, forced_minutes = deduplicate(
        video, candidates, len(segments), args.keep_duplicates
    )

    output = (Path(args.out_dir).expanduser().resolve()
              if args.out_dir else video.parent / "frames")
    output.mkdir(parents=True, exist_ok=True)
    json_write(output / "video_info.json", info)

    width, height = frame_size(info, args.frame_width)
    segs_per_part = args.part_minutes
    parts_mode = duration > args.part_minutes * SEGMENT_SECONDS
    total_parts = (math.ceil(len(segments) / segs_per_part)
                   if parts_mode else 1)

    print(f"Video: {video.name} ({fmt_time(duration)}, {info['width']}x{info['height']}, "
          f"{info['fps']} fps, {info['video_codec']})")
    print(f"Sampling: {'scene-aware' if scene_mode else 'uniform-only'}, "
          f"{len(scene_times)} detected cut(s), {len(segments)} segment(s)")
    if audio_srt is None:
        print("Dialogue: none (pure visual mode; no gap windows)")
    else:
        print(f"Dialogue: {len(cues)} SRT cue(s), {len(gaps)} gap window(s) >= "
              f"{args.gap_min_seconds:g}s")
    print(f"Candidates: {len(candidates)}")
    print(f"Dedup: kept {len(kept)} ({forced_minutes} forced for empty minute(s)), "
          f"dropped {dedup_dropped} near-duplicate(s)")
    print(f"Frame size: {width}x{height}; output: {output}")
    if parts_mode:
        print(f"Duration > {args.part_minutes} min -> PARTS mode: "
              f"{total_parts} part folder(s)")
    else:
        print("Duration <= part limit -> SINGLE mode")

    # Remove stale files in the root single-mode output. In parts mode only
    # the folders that are about to be written are cleaned.
    if not parts_mode:
        clean_generated_frames(output)
    kept_by_segment = {}
    for item in kept:
        kept_by_segment.setdefault(item["segment_index"], []).append(item)

    global_frame = 0
    plan_parts = []
    for part in range(1, total_parts + 1):
        first_segment = (part - 1) * segs_per_part
        last_segment = min(part * segs_per_part, len(segments)) - 1
        folder = output if not parts_mode else output / f"part{part}"
        folder.mkdir(parents=True, exist_ok=True)
        if parts_mode:
            clean_generated_frames(folder)

        range_start = segments[first_segment][0]
        range_end = segments[last_segment][1]
        gaps_inside = clip_intervals(gaps, range_start, range_end)
        dialogue_lines = sum(
            1 for start, end, _text in cues
            if overlaps(start, end, range_start, range_end)
        )
        dialogue_file = None
        if audio_srt is not None:
            dialogue_file = "dialogue.txt"
            write_dialogue_file(folder / dialogue_file, cues,
                                range_start, range_end)

        manifest_segments = []
        part_frame_count = 0
        for segment_index in range(first_segment, last_segment + 1):
            start, end = segments[segment_index]
            frame_records = []
            for item in kept_by_segment.get(segment_index, []):
                global_frame += 1
                filename = f"frame_{global_frame:04d}_{frame_tag(item['seconds'])}.jpg"
                output_path = folder / filename
                if extract_frame(video, item["seconds"], width, height,
                                 args.jpeg_quality, output_path):
                    frame_records.append(public_frame(item, filename))
                    part_frame_count += 1
                else:
                    global_frame -= 1
                    print(f"  WARNING: no frame at {fmt_time(item['seconds'])} "
                          f"(segment {segment_index + 1})")

            manifest_segments.append({
                "segment_index": segment_index + 1,
                "start_seconds": round_time(start),
                "end_seconds": round_time(end),
                "gap": is_gap_minute(start, end, gaps),
                "dialogue_lines": sum(
                    1 for cue_start, cue_end, _text in cues
                    if overlaps(cue_start, cue_end, start, end)
                ),
                "frames": frame_records,
            })
            print(f"  part {part} seg {segment_index + 1:02d} "
                  f"{fmt_time(start)}-{fmt_time(end)}: "
                  f"{len(frame_records)} frame(s)"
                  + (" [gap]" if manifest_segments[-1]["gap"] else ""))

        manifest = {
            "video": str(video),
            "video_info": info,
            "mode": "parts" if parts_mode else "single",
            "part": part,
            "total_parts": total_parts,
            "sampling": {
                "scene_aware": scene_mode,
                "scene_threshold": args.scene_threshold,
                "dedup": not args.keep_duplicates,
                "uniform_per_minute": uniform_per_minute,
                "scene_per_minute": args.scene_per_minute,
                "gap_uniform": args.gap_uniform,
                "gap_max_per_minute": args.gap_max_per_minute,
            },
            "dialogue": {
                "source": str(audio_srt) if audio_srt is not None else None,
                "file": dialogue_file,
                "gap_min_seconds": args.gap_min_seconds,
            },
            "segment_seconds": SEGMENT_SECONDS,
            "total_segments": len(segments),
            "range": [first_segment + 1, last_segment + 1],
            "segments": manifest_segments,
        }
        json_write(folder / "manifest.json", manifest)
        plan_parts.append({
            "part": part,
            "folder": str(folder),
            "segments": [first_segment + 1, last_segment + 1],
            "frames": part_frame_count,
            "dialogue_lines": dialogue_lines,
            "gaps_inside": gaps_inside,
        })
        print(f"  -> {folder}: {part_frame_count} extracted frame(s), "
              "manifest.json written")

    frames_total = sum(part["frames"] for part in plan_parts)
    plan = {
        "video": str(video),
        "mode": "parts" if parts_mode else "single",
        "out_dir": str(output),
        "duration_seconds": duration,
        "total_segments": len(segments),
        "total_parts": total_parts,
        "frames_total": frames_total,
        "dedup_dropped": dedup_dropped,
        "scene_aware": scene_mode,
        "dialogue_source": str(audio_srt) if audio_srt is not None else None,
        "gaps": [[round_time(start), round_time(end)]
                 for start, end in gaps],
        "parts": plan_parts,
    }
    json_write(output / "parts.json", plan)

    print(f"Done: {frames_total} frame(s), {len(segments)} segment(s), "
          f"{total_parts} part folder(s); PLAN written to {output / 'parts.json'}")
    print("PLAN: " + json.dumps(plan, ensure_ascii=False))
    return plan


def main() -> int:
    ap = parser()
    args = ap.parse_args()
    try:
        run_pipeline(args)
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        return error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
