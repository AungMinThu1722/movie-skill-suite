#!/usr/bin/env python3
"""
story_srt.py — turn a merged scene/dialogue timeline into a Burmese,
TTS-paced voice-over story SRT using OpenAI-compatible LLM calls.

The LLM rewrites the sources as a narrator, rather than transcribing them:
all dialogue events must be represented (paraphrase/attribution is enough),
while scene-only events are optional context and may be kept short or omitted.
The default Burmese TTS calibration is 20–24 Unicode characters/second, with
21.6 characters/second used to calculate output SRT durations.

Phases:
  0  config check + optional ping
  1  chunk pass — Burmese narrator lines tagged with source event IDs
  2  consolidation — unified character names/flow plus a Burmese hook
  3  mechanical assembly — IDs -> source anchors, calculated TTS durations,
     non-overlapping SRT entries, and dialogue/pace verification

Timestamps are never written by the LLM. Output defaults to
"<Title> VO.srt"; override with --out.
"""

import argparse
import concurrent.futures as cf
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from srtutil import ts, tts_clean, write_srt  # noqa: E402

PROMPT_FILE = Path(__file__).parent.parent / "references" / "story-prompt.md"
DEFAULT_CPS_MIN = 20.0
DEFAULT_CPS_MAX = 24.0
DEFAULT_CPS_TARGET = 21.6
DEFAULT_OUTPUT_LANGUAGE = "မြန်မာ (Burmese)"


# --------------------------------------------------------------------------- #
# LLM plumbing
# --------------------------------------------------------------------------- #


def load_config(cli: dict = None) -> dict:
    cfg = {"LLM_API_BASE": "", "LLM_API_KEY": "", "LLM_MODEL": ""}
    env_file = Path.home() / ".llm_env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                cfg[key.strip()] = value.strip().strip("'\"")
    for key, value in os.environ.items():
        if key in cfg and value.strip():
            cfg[key] = value.strip()
    for key, value in (cli or {}).items():
        if value:
            cfg[key] = value
    if not cfg["LLM_API_BASE"]:
        cfg["LLM_API_BASE"] = "https://openrouter.ai/api/v1"
    return cfg


def llm_call(cfg: dict, system: str, user: str, max_tokens: int,
             temperature: float = 0.7) -> str:
    """One chat completion with retries for transient/free-tier failures."""
    url = cfg["LLM_API_BASE"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["LLM_MODEL"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    last = None
    for attempt in range(6):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {cfg['LLM_API_KEY']}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local/story-vo-srt",
                "X-Title": "story-vo-srt",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("choices"):
                return data["choices"][0]["message"].get("content", "") or ""
            last = f"unexpected response: {str(data)[:180]}"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:280]
            if exc.code in (401, 402, 403):
                raise RuntimeError(
                    f"LLM auth/billing error HTTP {exc.code}: {body}"
                )
            last = f"HTTP {exc.code}: {body}"
            time.sleep(30 if exc.code == 429 else 10)
            continue
        except Exception as exc:  # timeout / connection reset
            last = f"{type(exc).__name__}: {str(exc)[:180]}"
            time.sleep(10)
        if attempt == 5:
            raise RuntimeError(f"LLM call failed after retries: {last}")
    raise RuntimeError(f"LLM call failed: {last}")


def ping(cfg: dict) -> bool:
    try:
        llm_call(cfg, "Reply with exactly: ok", "ping", max_tokens=8,
                 temperature=0)
        return True
    except Exception as exc:
        print(f"WARNING: LLM ping failed: {exc}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# response parsing and event coverage
# --------------------------------------------------------------------------- #

SECTION_RE = re.compile(r"^\s*(NARRATION|STATE|HOOK)\s*:?\s*$", re.I)
# A line may cover adjacent dialogue events in one narrator beat:
# [E0007,E0008] ...  A single [E0007] remains fully supported.
LINE_RE = re.compile(
    r"^\s*\[((?:E\d{3,6})(?:\s*,\s*E\d{3,6})*)\]\s*(.*)$"
)
ID_RE = re.compile(r"E\d{3,6}")


def narration_ids(line: dict) -> list:
    ids = line.get("ids")
    if ids:
        return list(dict.fromkeys(ids))
    if line.get("id"):
        return [line["id"]]
    return []


def parse_response(content: str) -> dict:
    result = {"narration": [], "state": "", "hook": ""}
    section = None
    buffer = []
    for line in content.splitlines():
        match = SECTION_RE.match(line)
        if match:
            if section:
                flush_section(result, section, buffer)
            section = match.group(1).upper()
            buffer = []
            continue
        if section:
            buffer.append(line)
    if section:
        flush_section(result, section, buffer)
    return result


def flush_section(result: dict, section: str, lines: list) -> None:
    text = "\n".join(lines).strip("\n")
    if section == "STATE":
        result["state"] = text.strip()
    elif section == "HOOK":
        result["hook"] = " ".join(text.split())
    elif section == "NARRATION":
        current = None
        for line in lines:
            match = LINE_RE.match(line)
            if match:
                ids = [item.strip() for item in match.group(1).split(",")]
                current = {"ids": ids, "id": ids[0],
                           "text": match.group(2).strip()}
                result["narration"].append(current)
            elif line.strip() and current is not None:
                current["text"] += " " + line.strip()


def event_time(line: dict, events_by_id: dict) -> float:
    times = [events_by_id[item]["t"] for item in narration_ids(line)
             if item in events_by_id]
    return min(times) if times else float("inf")


def missing_dialogue(narration: list, required: list) -> list:
    covered = set()
    for line in narration:
        covered.update(narration_ids(line))
    return [event for event in required if event["id"] not in covered]


def validate_narration(narration: list, allowed_ids: set,
                       required_dialogue: list, events_by_id: dict) -> list:
    """Drop unknown IDs and add raw fallbacks only as a last resort.

    The normal path repairs missing dialogue with another Burmese LLM call
    before reaching this function. The raw source fallback is deliberately
    marked, so the verification report exposes any model failure instead of
    silently losing a spoken beat.
    """
    kept = []
    for original in narration:
        ids = [item for item in narration_ids(original) if item in allowed_ids]
        text = str(original.get("text", "")).strip()
        if not ids or not text:
            continue
        kept.append({
            "ids": list(dict.fromkeys(ids)),
            "id": ids[0],
            "text": text,
            "fallback": bool(original.get("fallback", False)),
        })

    kept.sort(key=lambda line: event_time(line, events_by_id))
    covered = set()
    for line in kept:
        covered.update(narration_ids(line))
    for event in required_dialogue:
        if event["id"] not in covered:
            kept.append({
                "ids": [event["id"]],
                "id": event["id"],
                "text": event["text"],
                "fallback": True,
            })
            covered.add(event["id"])
    kept.sort(key=lambda line: event_time(line, events_by_id))
    return kept


def build_events_block(events: list, timing: dict = None) -> str:
    lines = []
    for event in events:
        end = event.get("t_end", event.get("t", 0.0))
        line = (f"[{event['id']}] (t={ts(event['t'])}-{ts(end)}) "
                f"[{event['type']}] {event['text']}")
        if timing and event["id"] in timing:
            info = timing[event["id"]]
            if event["type"] == "dialogue":
                line += (
                    f" | REQUIRED Burmese VO window {info['available_seconds']:.2f}s; "
                    f"aim {info['min_chars']}-{info['max_chars']} Unicode chars "
                    f"at {info['cps_min']:.1f}-{info['cps_max']:.1f} CPS"
                )
            else:
                line += " | OPTIONAL scene beat: one short line or omit"
        lines.append(line)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# timing and prompts
# --------------------------------------------------------------------------- #


def build_timing_table(events: list, cps_min: float, cps_max: float,
                       cps_target: float) -> dict:
    """Calculate a narration budget for every source event.

    Dialogue gets the interval up to the next dialogue cue, because every
    spoken beat is required. Scene-only events are deliberately marked
    optional and receive a small suggested beat rather than a full-minute
    fill budget.
    """
    ordered = sorted(events, key=lambda event: (event["t"], event["t_end"]))
    dialogue = [event for event in ordered if event["type"] == "dialogue"]
    next_dialogue = {}
    for index, event in enumerate(dialogue):
        next_dialogue[event["id"]] = (
            dialogue[index + 1]["t"] if index + 1 < len(dialogue) else None
        )

    result = {}
    for event in ordered:
        start = float(event["t"])
        if event["type"] == "dialogue":
            next_start = next_dialogue.get(event["id"])
            if next_start is None:
                available = max(1.0, float(event["t_end"]) - start)
            else:
                available = max(0.75, float(next_start) - start)
            required = True
        else:
            following = [other["t"] for other in ordered
                         if other["t"] > start]
            gap = min(following) - start if following else 5.0
            # Scene-only narration is intentionally a short optional beat.
            available = max(1.0, min(5.0, gap))
            required = False
        result[event["id"]] = {
            "available_seconds": round(available, 2),
            "min_chars": max(1, int(math.floor(available * cps_min))),
            "max_chars": max(1, int(math.ceil(available * cps_max))),
            "target_chars": max(1, int(round(available * cps_target))),
            "cps_min": cps_min,
            "cps_max": cps_max,
            "cps_target": cps_target,
            "required": required,
        }
    return result


def chunk_prompt(chunk: dict, state: str, timing: dict,
                 hook_seconds: float, output_language: str,
                 cps_min: float, cps_max: float, cps_target: float) -> str:
    tail = ""
    if chunk.get("prev_tail"):
        tail = (
            "\nPrevious-chunk tail is continuity context only; do not repeat it "
            "unless a required dialogue beat belongs to this chunk:\n"
            + build_events_block(chunk["prev_tail"], timing) + "\n\n"
        )
    story_state = state or "(no prior state — opening chunk)"
    return (
        f"Target output language: {output_language}.\n"
        f"Burmese TTS calibration: {cps_min:.1f}-{cps_max:.1f} Unicode "
        f"characters/second; aim for {cps_target:.1f}. Python len() counts "
        f"characters, including spaces and punctuation.\n\n"
        f"{tail}"
        "SOURCE EVENTS (time ordered; dialogue is required, scene is optional):\n"
        + build_events_block(chunk["events"], timing)
        + "\n\nSTORY STATE:\n"
        + story_state
        + "\n\nINSTRUCTIONS:\n"
        f"- Rewrite as a natural {output_language} movie-recap narrator, not a transcript, "
        "book report, or line-by-line translation.\n"
        "- Every [dialogue] event in this chunk MUST be represented. Preserve "
        "its meaning, but paraphrase naturally; it is enough to say who says "
        "what. Do not reproduce every spoken word.\n"
        "- Adjacent dialogue events may share one line: start it with all IDs, "
        "for example [E0007,E0008].\n"
        "- [scene] events are optional. Keep only plot-changing visual beats, "
        "using a short line; omit ordinary silent scenery.\n"
        "- Respect each dialogue event's displayed VO window and character "
        "budget. Do not pad a scene-only line to fill a minute.\n"
        f"- The first {hook_seconds:g} seconds may later be replaced by a hook, "
        "but still cover opening dialogue in the chunk output.\n"
        "- No invented names, motives, events, or dialogue. No timestamps in "
        "your output. TTS-safe Burmese prose only.\n\n"
        "OUTPUT FORMAT (exact):\n"
        "NARRATION:\n[E0001] မြန်မာ narrator line\n"
        "[E0002,E0003] adjacent dialogue beat\n"
        "STATE:\ncharacters: ...\nplot: ...\ntone: ..."
    )


def consolidate_prompt(parts: list, movie: dict, events_all: list,
                       timing: dict, hook_seconds: float,
                       output_language: str, cps_min: float, cps_max: float,
                       cps_target: float) -> str:
    blocks = []
    for part in parts:
        lines = "\n".join(
            f"[{','.join(narration_ids(line))}] {line['text']}"
            for line in part["narration"]
        )
        blocks.append(
            f"--- chunk {part['index']} ({ts(part['range'][0])} - "
            f"{ts(part['range'][1])}) ---\n{lines}\n"
            f"state: {part.get('state', '')}".rstrip()
        )
    required = [event for event in events_all if event["type"] == "dialogue"]
    required_ids = ", ".join(event["id"] for event in required)
    opening = ", ".join(
        event["id"] for event in required if event["t"] < hook_seconds
    ) or "none"
    return (
        f"Target output language: {output_language}.\n"
        f"Burmese TTS calibration: {cps_min:.1f}-{cps_max:.1f} Unicode "
        f"characters/second; aim for {cps_target:.1f}.\n"
        f"Movie: {movie['title']} | source language: {movie['language']} | "
        f"duration: {ts(movie['duration_seconds'])}\n\n"
        "The chunk drafts below are narrator drafts, not a transcript.\n"
        f"REQUIRED DIALOGUE IDS (all must remain covered, once or grouped): "
        f"{required_ids}\n"
        f"OPENING DIALOGUE IDS that the hook should absorb: {opening}\n\n"
        f"Rewrite and return the COMPLETE {output_language} narration in time order. "
        "Every required dialogue ID must appear in at least one narration line; "
        "adjacent IDs may be grouped. Scene IDs are optional: keep only the "
        "few visual beats that help the story, and omit ordinary silent scenes. "
        "Paraphrase dialogue and use natural attribution such as who says what; "
        "do not copy every source subtitle or write a book-like transcript. "
        "Keep lines concise enough for the displayed dialogue timing budgets.\n\n"
        + "\n\n".join(blocks)
        + "\n\nOUTPUT FORMAT (exactly):\n"
        "NARRATION:\n[E0001] မြန်မာ narrator line\n"
        "[E0002,E0003] grouped beat\n"
        "HOOK:\nမြန်မာ teaser of 2–3 sentences\n"
        f"The hook replaces the first {hook_seconds:g} seconds, must contain no "
        "ending spoiler, and should itself fit roughly "
        f"{hook_seconds * cps_min:.0f}-{hook_seconds * cps_max:.0f} Unicode "
        "characters."
    )


def repair_prompt(missing: list, timing: dict, output_language: str,
                   cps_min: float, cps_max: float, cps_target: float) -> str:
    return (
        f"Write one concise narrator line per missing dialogue event in "
        f"{output_language}. This is a repair pass.\n"
        f"Use natural {output_language} recap narration, not a transcript. Paraphrase "
        f"the meaning and attribute who says what; do not copy the whole "
        f"source subtitle. Each line must begin with its exact event ID.\n"
        f"TTS speed is {cps_min:.1f}-{cps_max:.1f} Unicode characters/second "
        f"(target {cps_target:.1f}); respect the supplied character window.\n\n"
        + "\n".join(
            f"[{event['id']}] ({timing[event['id']]['min_chars']}-"
            f"{timing[event['id']]['max_chars']} chars) source dialogue: "
            f"{event['text']}"
            for event in missing
        )
        + "\n\nOUTPUT:\nNARRATION:\n[E0001] ..."
    )


def repair_missing_dialogue(cfg: dict, missing: list, timing: dict,
                            output_language: str, cps_min: float,
                            cps_max: float, cps_target: float,
                            max_tokens: int) -> list:
    if not missing:
        return []
    try:
        content = llm_call(
            cfg,
            "You repair missing dialogue coverage in a Burmese movie recap. "
            "Output only the requested NARRATION section.",
            repair_prompt(missing, timing, output_language, cps_min, cps_max,
                          cps_target),
            max_tokens=max(1200, min(max_tokens, 6000)),
            temperature=0.35,
        )
        return parse_response(content)["narration"]
    except RuntimeError as exc:
        print(f"WARNING: dialogue repair failed: {exc}", file=sys.stderr)
        return []


# --------------------------------------------------------------------------- #
# mechanical timing / assembly
# --------------------------------------------------------------------------- #


def speech_seconds(text: str, cps_target: float) -> float:
    return max(0.25, len(text) / cps_target)


def unit_from_line(line: dict, events_by_id: dict, hook_seconds: float,
                   has_hook: bool) -> dict:
    ids = [item for item in narration_ids(line) if item in events_by_id]
    events = [events_by_id[item] for item in ids]
    if not events:
        return None
    text = tts_clean(line.get("text", ""))
    if not text:
        return None
    start = min(event["t"] for event in events)
    if has_hook and start < hook_seconds:
        # The hook will cover this opening beat. If a grouped line also has a
        # later event, retain it at the hook boundary instead of losing it.
        later = [event for event in events if event["t"] >= hook_seconds]
        if not later:
            return None
        start = min(event["t"] for event in later)
        ids = [event["id"] for event in later]
        events = later
    return {
        "start": float(start),
        "anchor": float(start),
        "text": text,
        "ids": ids,
        "dialogue": any(event["type"] == "dialogue" for event in events),
        "scene_only": all(event["type"] == "scene" for event in events),
        "fallback": bool(line.get("fallback", False)),
    }


def merge_units(units: list, cps_target: float) -> tuple:
    """Make non-overlapping TTS entries while protecting dialogue coverage.

    Adjacent/overlapping dialogue beats are combined into one narrator entry.
    An optional scene-only beat that collides with required dialogue is
    dropped, which is preferable to making the dialogue drift in the editor.
    """
    units = sorted(units, key=lambda unit: (
        unit["start"], 0 if unit["dialogue"] else 1
    ))
    output = []
    skipped_scene = 0
    shifted = 0.0
    for unit in units:
        duration = speech_seconds(unit["text"], cps_target)
        unit["end"] = unit["start"] + duration
        if not output:
            output.append(unit)
            continue
        previous = output[-1]
        if unit["start"] >= previous["end"] - 1e-6:
            output.append(unit)
            continue
        if unit["scene_only"] and not unit["dialogue"]:
            skipped_scene += 1
            continue
        if previous["scene_only"] and not previous["dialogue"]:
            output.pop()
            output.append(unit)
            continue

        # Both beats matter, or this is a dialogue beat following an
        # optional visual beat. Merge so the SRT never has overlapping blocks.
        previous["text"] = (previous["text"].rstrip() + " "
                            + unit["text"].lstrip()).strip()
        previous["ids"] = list(dict.fromkeys(previous["ids"] + unit["ids"]))
        previous["dialogue"] = previous["dialogue"] or unit["dialogue"]
        previous["scene_only"] = previous["scene_only"] and unit["scene_only"]
        previous["fallback"] = previous["fallback"] or unit["fallback"]
        previous["end"] = previous["start"] + speech_seconds(
            previous["text"], cps_target
        )
        if previous["end"] > unit["start"]:
            shifted = max(shifted, previous["end"] - unit["start"])
    return output, skipped_scene, shifted


def timing_report(entries: list, cps_min: float, cps_max: float,
                  cps_target: float) -> dict:
    violations = []
    cps_values = []
    total_chars = 0
    total_seconds = 0.0
    for index, entry in enumerate(entries, 1):
        start, end, text = entry
        duration = max(0.001, end - start)
        chars = len(text)
        cps = chars / duration
        cps_values.append(cps)
        total_chars += chars
        total_seconds += duration
        if cps < cps_min - 0.15 or cps > cps_max + 0.15:
            violations.append({
                "entry": index, "chars": chars,
                "duration_seconds": round(duration, 3),
                "cps": round(cps, 3),
            })
    return {
        "cps_min": cps_min,
        "cps_max": cps_max,
        "cps_target": cps_target,
        "narration_chars": total_chars,
        "estimated_speech_seconds": round(total_seconds, 2),
        "effective_cps": round(total_chars / total_seconds, 3)
        if total_seconds else 0.0,
        "timing_violations": violations,
    }


# --------------------------------------------------------------------------- #
# main pipeline
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--work", default=".work", help="work dir (default .work)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--out", default=None, help='default "<title> VO.srt"')
    ap.add_argument("--output-language", "--language",
                    dest="output_language", default=DEFAULT_OUTPUT_LANGUAGE,
                    help="narration language (default: Burmese)")
    ap.add_argument("--cps-min", type=float, default=DEFAULT_CPS_MIN,
                    help="minimum TTS characters/second (default 20)")
    ap.add_argument("--cps-max", type=float, default=DEFAULT_CPS_MAX,
                    help="maximum TTS characters/second (default 24)")
    ap.add_argument("--cps-target", type=float, default=DEFAULT_CPS_TARGET,
                    help="duration-calculation target (default 21.6)")
    ap.add_argument("--hook-seconds", type=float, default=10.0,
                    help="hook length replacing the opening (default 10)")
    ap.add_argument("--max-tokens-chunk", type=int, default=20000,
                    help="max output tokens per chunk call")
    ap.add_argument("--max-tokens-consolidate", type=int, default=32000,
                    help="max output tokens for consolidation")
    ap.add_argument("--parallel", type=int, default=1,
                    help="parallel chunk calls; keep 1 on free-tier keys")
    ap.add_argument("--force", action="store_true",
                    help="redo chunks even if part files exist")
    ap.add_argument("--no-ping", action="store_true")
    ap.add_argument("--no-consolidate", action="store_true",
                    help="skip consolidation; useful for one-chunk debugging")
    ap.add_argument("--base", default=None)
    ap.add_argument("--key", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    if args.cps_min <= 0 or args.cps_max < args.cps_min:
        print("ERROR: require 0 < --cps-min <= --cps-max", file=sys.stderr)
        return 2
    if not args.cps_min <= args.cps_target <= args.cps_max:
        print("ERROR: --cps-target must be between --cps-min and --cps-max",
              file=sys.stderr)
        return 2
    if args.hook_seconds < 0:
        print("ERROR: --hook-seconds must be zero or greater", file=sys.stderr)
        return 2

    work = Path(args.work).expanduser().resolve()
    story_dir = work / "story"
    movie_file = story_dir / "movie.json"
    timeline_file = story_dir / "timeline.json"
    if not movie_file.is_file() or not timeline_file.is_file():
        print("ERROR: missing movie.json/timeline.json — run "
              f"merge_timeline.py first in {story_dir}", file=sys.stderr)
        return 2

    movie = json.loads(movie_file.read_text(encoding="utf-8"))
    title = args.title or movie["title"]
    config = load_config({
        "LLM_API_BASE": args.base,
        "LLM_API_KEY": args.key,
        "LLM_MODEL": args.model,
    })
    if not config["LLM_API_KEY"] or not config["LLM_MODEL"]:
        print("ERROR: LLM key/model not configured (env, ~/.llm_env, or "
              "--base/--key/--model)", file=sys.stderr)
        return 2
    if not args.no_ping and not ping(config):
        print("ERROR: LLM ping failed — check ~/.llm_env / key / model",
              file=sys.stderr)
        return 2

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    events_all = json.loads(timeline_file.read_text(encoding="utf-8"))["events"]
    events_by_id = {event["id"]: event for event in events_all}
    timing = build_timing_table(events_all, args.cps_min, args.cps_max,
                                args.cps_target)
    hook_seconds = args.hook_seconds

    # ---------------- phase 1: chunk pass ----------------
    chunks = sorted(story_dir.glob("chunk_*.json"))
    if not chunks:
        print("ERROR: no chunk_*.json files in story directory", file=sys.stderr)
        return 2

    def do_chunk(path: Path) -> dict:
        chunk = json.loads(path.read_text(encoding="utf-8"))
        part_file = story_dir / f"part_{chunk['index']:02d}.json"
        if part_file.is_file() and not args.force:
            print(f"chunk {chunk['index']}: resuming saved part", file=sys.stderr)
            return json.loads(part_file.read_text(encoding="utf-8"))
        index = chunk["index"]
        states = []
        for previous_index in range(1, index):
            previous_file = story_dir / f"part_{previous_index:02d}.json"
            if previous_file.is_file():
                states.append(json.loads(previous_file.read_text(
                    encoding="utf-8")).get("state", ""))
        state = "\n".join(item for item in states if item)[-1500:]

        print(f"chunk {index}: {len(chunk['events'])} events -> Burmese LLM ...",
              file=sys.stderr)
        content = llm_call(
            config, system_prompt,
            chunk_prompt(chunk, state, timing, hook_seconds,
                         args.output_language, args.cps_min, args.cps_max,
                         args.cps_target),
            max_tokens=args.max_tokens_chunk,
        )
        parsed = parse_response(content)
        allowed = {event["id"] for event in chunk["events"]}
        allowed.update(event["id"] for event in chunk.get("prev_tail", []))
        required = [event for event in chunk["events"]
                    if event["type"] == "dialogue"]
        repaired = repair_missing_dialogue(
            config,
            missing_dialogue(parsed["narration"], required),
            timing,
            args.output_language,
            args.cps_min,
            args.cps_max,
            args.cps_target,
            args.max_tokens_chunk,
        )
        narration = validate_narration(
            parsed["narration"] + repaired, allowed, required, events_by_id
        )
        fallbacks = [line["id"] for line in narration
                     if line.get("fallback")]
        part = {
            "index": index,
            "range": chunk["range"],
            "narration": narration,
            "state": (parsed.get("state") or "")[:1500],
            "fallbacks": fallbacks,
            "output_language": args.output_language,
            "cps": {
                "min": args.cps_min, "max": args.cps_max,
                "target": args.cps_target,
            },
        }
        part_file.write_text(json.dumps(part, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        print(f"chunk {index}: done ({len(narration)} lines, "
              f"{len(fallbacks)} raw fallback(s))", file=sys.stderr)
        return part

    if args.parallel > 1:
        with cf.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            parts = list(executor.map(do_chunk, chunks))
    else:
        parts = [do_chunk(path) for path in chunks]
    parts.sort(key=lambda part: part["index"])

    # ---------------- phase 2: consolidation ----------------
    final_file = story_dir / "part_final.json"
    if args.no_consolidate:
        final_narration = [line for part in parts
                           for line in part["narration"]]
        hook = ""
        consolidated = False
    else:
        print("Burmese consolidation pass ...", file=sys.stderr)
        content = llm_call(
            config,
            system_prompt,
            consolidate_prompt(parts, movie, events_all, timing,
                               hook_seconds, args.output_language,
                               args.cps_min, args.cps_max, args.cps_target),
            max_tokens=args.max_tokens_consolidate,
        )
        parsed = parse_response(content)
        required = [event for event in events_all
                    if event["type"] == "dialogue"]
        repaired = repair_missing_dialogue(
            config,
            missing_dialogue(parsed["narration"], required),
            timing,
            args.output_language,
            args.cps_min,
            args.cps_max,
            args.cps_target,
            args.max_tokens_consolidate,
        )
        final_narration = validate_narration(
            parsed["narration"] + repaired,
            set(events_by_id),
            required,
            events_by_id,
        )
        hook = parsed.get("hook", "")
        consolidated = True
        final_file.write_text(
            json.dumps({
                "narration": final_narration,
                "hook": hook,
                "output_language": args.output_language,
                "cps": {"min": args.cps_min, "max": args.cps_max,
                        "target": args.cps_target},
            }, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    # ---------------- phase 3: mechanical assembly ----------------
    units = []
    for line in final_narration:
        unit = unit_from_line(line, events_by_id, hook_seconds, bool(hook))
        if unit is not None:
            units.append(unit)

    hook_text = tts_clean(hook) if hook else ""
    hook_unit = None
    if hook_text:
        hook_unit = {
            "start": 0.0,
            "anchor": 0.0,
            "end": speech_seconds(hook_text, args.cps_target),
            "text": hook_text,
            "ids": [],
            "dialogue": False,
            "scene_only": False,
            "fallback": False,
            "hook": True,
        }
        # Opening events before hook_seconds are represented by the hook; the
        # remaining units begin at/after the hook window.
        units = [unit for unit in units if unit["start"] >= hook_seconds]

    hook_shift = 0.0
    if hook_unit is not None:
        for unit in units:
            if unit["start"] < hook_unit["end"]:
                hook_shift = max(hook_shift, hook_unit["end"] - unit["start"])
                unit["start"] = hook_unit["end"]
    # Move any post-hook dialogue before packing so merge_units is called once.
    packed, skipped_scene, merged_overlap = merge_units(units, args.cps_target)

    entries = []
    if hook_unit is not None:
        entries.append((hook_unit["start"], hook_unit["end"], hook_unit["text"]))
    entries.extend((unit["start"], unit["end"], unit["text"])
                   for unit in packed)
    entries.sort(key=lambda item: item[0])

    if not entries:
        print("ERROR: assembly produced no entries", file=sys.stderr)
        return 1

    output = (Path(args.out).expanduser().resolve()
              if args.out else Path.cwd() / f"{title} VO.srt")
    write_srt(entries, output)

    # ---------------- phase 4: verification ----------------
    dialogue_all = [event for event in events_all
                    if event["type"] == "dialogue"]
    covered = set()
    for line in final_narration:
        covered.update(narration_ids(line))
    # The hook replaces the opening; count opening dialogue as covered by the
    # hook instead of falsely reporting it as missing from the final entries.
    if hook:
        covered.update(event["id"] for event in dialogue_all
                       if event["t"] < hook_seconds)
    dialogue_covered = sum(1 for event in dialogue_all
                           if event["id"] in covered)
    fallback_lines = sum(1 for line in final_narration
                         if line.get("fallback"))
    scene_lines = sum(1 for unit in packed if any(
        events_by_id[item]["type"] == "scene"
        for item in unit["ids"] if item in events_by_id
    ))
    pace = timing_report(entries, args.cps_min, args.cps_max,
                          args.cps_target)
    hook_chars = len(hook_text)
    hook_seconds_est = (speech_seconds(hook_text, args.cps_target)
                        if hook_text else 0.0)
    hook_fits_window = (not hook_text or hook_seconds_est <= hook_seconds)
    report = {
        "ok": dialogue_covered == len(dialogue_all)
        and fallback_lines == 0
        and not pace["timing_violations"]
        and hook_fits_window,
        "srt": str(output),
        "title": title,
        "source_language": movie.get("language", "unknown"),
        "output_language": args.output_language,
        "entries": len(entries),
        "hook": bool(hook),
        "hook_chars": hook_chars,
        "hook_estimated_seconds": round(hook_seconds_est, 2),
        "hook_fits_window": hook_fits_window,
        "hook_following_shift_seconds": round(hook_shift, 3),
        "consolidated": consolidated,
        "dialogue_total": len(dialogue_all),
        "dialogue_covered": dialogue_covered,
        "dialogue_coverage_percent": round(
            dialogue_covered / len(dialogue_all) * 100, 1
        ) if dialogue_all else 100.0,
        "fallback_lines": fallback_lines,
        "scene_narration_lines": scene_lines,
        "scene_only_lines_skipped_for_timing": skipped_scene,
        "merged_overlapping_beats": round(merged_overlap, 3),
        "duration_seconds": round(
            max(event["t_end"] for event in events_all), 1
        ) if events_all else 0.0,
        "llm_model": config["LLM_MODEL"],
        "chunks": len(parts),
        **pace,
    }
    (story_dir / "verify.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
