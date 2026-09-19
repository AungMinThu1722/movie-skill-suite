#!/usr/bin/env python3
"""
story_srt.py — turn the merged timeline into a TTS-ready voice-over story
script (SRT) using LLM API calls. Everything in this script is automatic;
the agent only runs it.

Phases:
  0  config check (LLM base/key/model from env, ~/.llm_env, or flags) + ping
  1  chunk pass — one LLM call per 10-minute chunk: the model rewrites the
     chunk's events as narrator lines, each line tagged with the source
     EVENT ID it covers, plus a short story-state note. Missing dialogue
     coverage is auto-filled with the original line (fallback).
  2  consolidation — one LLM call over all chunk outputs: unifies character
     naming / phrasing, smooths chunk transitions, and writes the HOOK
     (0:00-0:10) that replaces the film's first seconds.
  3  mechanical assembly — event IDs are mapped back to the ORIGINAL
     timestamps (the LLM never typed a timestamp), entries are ordered,
     deduped, TTS-cleaned, and written to the output SRT.
  4  verification report (coverage, hook, duration) as JSON on stdout.

Output: "<Title> VO.srt" by default (override with --out).

Usage:
  python3 story_srt.py --title "Movie Name"
  python3 story_srt.py --work .work --out "Movie Name VO.srt" --hook-seconds 10
  python3 story_srt.py --title "X" --model gpt-4o-mini --force
"""

import argparse
import concurrent.futures as cf
import json
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
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip("'\"")
    for k, v in os.environ.items():
        if k in cfg and v.strip():
            cfg[k] = v.strip()
    for k, v in (cli or {}).items():
        if v:
            cfg[k] = v
    cfg.setdefault("LLM_API_BASE", "https://openrouter.ai/api/v1")
    return cfg


def llm_call(cfg: dict, system: str, user: str, max_tokens: int,
             temperature: float = 0.7) -> str:
    """One chat completion with retries (429 backoff for free tiers)."""
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
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {cfg['LLM_API_KEY']}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local/story-vo-srt",
                "X-Title": "story-vo-srt",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read().decode("utf-8"))
            if "choices" in d:
                return d["choices"][0]["message"]["content"] or ""
            last = f"unexpected response: {str(d)[:150]}"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:250]
            if e.code in (401, 402, 403):
                raise RuntimeError(f"LLM auth/billing error HTTP {e.code}: {body}")
            last = f"HTTP {e.code}: {body}"
            time.sleep(30 if e.code == 429 else 10)
            continue
        except Exception as e:  # timeout / connection
            last = f"{type(e).__name__}: {str(e)[:150]}"
            time.sleep(10)
        if attempt == 5:
            raise RuntimeError(f"LLM call failed after retries: {last}")
    raise RuntimeError(f"LLM call failed: {last}")


def ping(cfg: dict) -> bool:
    try:
        llm_call(cfg, "You reply with exactly: ok", "ping", max_tokens=8,
                 temperature=0)
        return True
    except Exception as e:
        print(f"WARNING: LLM ping failed: {e}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# response parsing / validation
# --------------------------------------------------------------------------- #

SECTION_RE = re.compile(r"^\s*(NARRATION|STATE|HOOK)\s*:?\s*$", re.I)
LINE_RE = re.compile(r"^\s*\[(E\d{3,6})\]\s*(.*)$")


def parse_response(content: str) -> dict:
    out = {"narration": [], "state": "", "hook": ""}
    section = None
    buf = []
    for line in content.splitlines():
        m = SECTION_RE.match(line)
        if m:
            if section:
                flush(out, section, buf)
            section = m.group(1).upper()
            buf = []
            continue
        if section:
            buf.append(line)
    if section:
        flush(out, section, buf)
    return out


def flush(out: dict, section: str, buf: list) -> None:
    text = "\n".join(buf).strip("\n")
    if section == "STATE":
        out["state"] = text.strip()
    elif section == "HOOK":
        out["hook"] = " ".join(text.split())
    elif section == "NARRATION":
        current = None
        for ln in buf:
            m = LINE_RE.match(ln)
            if m:
                current = {"id": m.group(1), "text": m.group(2).strip()}
                out["narration"].append(current)
            elif ln.strip() and current is not None:
                # wrapped continuation of the previous line
                current["text"] += " " + ln.strip()
            elif ln.strip():
                # stray line with no id: attach to the previous line if any
                if current is not None:
                    current["text"] += " " + ln.strip()


def build_events_block(events: list) -> str:
    lines = []
    for e in events:
        lines.append(f"[{e['id']}] (t={ts(e['t'])}) [{e['type']}] {e['text']}")
    return "\n".join(lines)


def validate_narration(narration: list, allowed_ids: set,
                       must_cover: list, events_by_id: dict) -> list:
    """Drops unknown IDs, sorts by event time, fills uncovered dialogue
    events with fallback lines. Returns narration lines (+fallback flags)."""
    kept = []
    for n in narration:
        if n["id"] in allowed_ids:
            kept.append(dict(n, fallback=False))
        else:
            kept.append(dict(n, fallback=False, drop=True))
    kept = [n for n in kept if not n.pop("drop", False)]

    def t_of(n):
        e = events_by_id.get(n["id"])
        return e["t"] if e else float("inf")

    kept.sort(key=lambda n: t_of(n))

    covered = {n["id"] for n in kept}
    for req in must_cover:
        if req["id"] not in covered:
            kept.append({"id": req["id"], "text": req["text"], "fallback": True})
            covered.add(req["id"])
    kept.sort(key=lambda n: t_of(n))
    return kept


# --------------------------------------------------------------------------- #
# phases
# --------------------------------------------------------------------------- #

def chunk_prompt(system_base: str, chunk: dict, state: str,
                 hook_seconds: float) -> str:
    tail = ""
    if chunk.get("prev_tail"):
        tail = ("\nEvents from the END of the previous chunk (continuity "
                "context — do NOT re-narrate them):\n"
                + build_events_block(chunk["prev_tail"]) + "\n\n")
    st = state or "(no prior state — this is the opening chunk)"
    return (
        f"Movie (working title): the story so far is in STATE below.\n\n"
        f"{tail}"
        f"EVENTS TO NARRATE (time-ordered; [dialogue] = spoken words, "
        f"[scene] = what is visible):\n"
        f"{build_events_block(chunk['events'])}\n\n"
        f"STORY STATE:\n{st}\n\n"
        f"Rules reminder: cover every [dialogue] event in this chunk; "
        f"tag each narration line with the event ID it covers; write in the "
        f"story's own language; TTS-safe text only; then update STATE.\n"
        f"OUTPUT FORMAT (exactly):\n"
        f"NARRATION:\n[E0001] ...\n[E0004] ...\n"
        f"STATE:\ncharacters: ...\nplot: ...\ntone: ..."
    )


def consolidate_prompt(system_base: str, parts: list, movie: dict,
                       hook_seconds: float) -> str:
    blocks = []
    for p in parts:
        lines = "\n".join(f"[{n['id']}] {n['text']}" for n in p["narration"])
        blocks.append(f"--- chunk {p['index']} ({ts(p['range'][0])} - "
                      f"{ts(p['range'][1])}) ---\n{lines}\n"
                      f"state: {p['state']}".rstrip())
    return (
        f"Movie: {movie['title']}  |  language: {movie['language']}  |  "
        f"duration: {ts(movie['duration_seconds'])}\n\n"
        f"All chunk narrations are below (event IDs + text). Your job:\n"
        f"1. Re-output the COMPLETE narration for the whole movie: every "
        f"event ID from every chunk must appear exactly once, in time "
        f"order, tagged [Eid] at the line start.\n"
        f"2. While doing so: unify character names and phrasing across "
        f"chunks, smooth the transitions between chunks, fix any "
        f"continuity slips, keep TTS-safe style and the story's language.\n"
        f"3. Write the HOOK: 2-3 sentences of gripping opening voice-over "
        f"that teases the whole story (no ending spoilers). It will "
        f"REPLACE the film's first {int(hook_seconds)} seconds, so do not "
        f"also narrate events that start within those first "
        f"{int(hook_seconds)} seconds.\n\n"
        + "\n\n".join(blocks) + "\n\n"
        "OUTPUT FORMAT (exactly):\n"
        "NARRATION:\n[E0001] ...\n[E0002] ...\n"
        "HOOK:\n2-3 sentences..."
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=".work", help="work dir (default .work)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--out", default=None, help='default "<title> VO.srt"')
    ap.add_argument("--hook-seconds", type=float, default=10.0,
                    help="hook length replacing the opening (default 10)")
    ap.add_argument("--max-tokens-chunk", type=int, default=20000,
                    help="max output tokens per chunk call (reasoning "
                         "models spend part of this on thinking)")
    ap.add_argument("--max-tokens-consolidate", type=int, default=32000,
                    help="max output tokens for the consolidation call")
    ap.add_argument("--parallel", type=int, default=1,
                    help="parallel chunk calls (keep 1 on free-tier keys)")
    ap.add_argument("--force", action="store_true",
                    help="redo chunks even if part files exist")
    ap.add_argument("--no-ping", action="store_true")
    ap.add_argument("--no-consolidate", action="store_true",
                    help="skip the consolidation pass (single-chunk films)")
    ap.add_argument("--base", default=None)
    ap.add_argument("--key", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    work = Path(args.work).expanduser().resolve()
    story_dir = work / "story"
    movie_f = story_dir / "movie.json"
    if not movie_f.is_file():
        print("ERROR: no movie.json — run merge_timeline.py first "
              f"(expected {movie_f})", file=sys.stderr)
        return 2
    movie = json.loads(movie_f.read_text(encoding="utf-8"))
    title = args.title or movie["title"]

    cfg = load_config({"LLM_API_BASE": args.base, "LLM_API_KEY": args.key,
                       "LLM_MODEL": args.model})
    if not cfg["LLM_API_KEY"] or not cfg["LLM_MODEL"]:
        print("ERROR: LLM key/model not configured (env, ~/.llm_env, or "
              "--base/--key/--model)", file=sys.stderr)
        return 2
    if not args.no_ping and not ping(cfg):
        print("ERROR: LLM ping failed — check ~/.llm_env / key / model",
              file=sys.stderr)
        return 2

    system_base = PROMPT_FILE.read_text(encoding="utf-8")
    events_all = json.loads(
        (story_dir / "timeline.json").read_text(encoding="utf-8"))["events"]
    events_by_id = {e["id"]: e for e in events_all}
    hook_seconds = args.hook_seconds

    # ---------------- phase 1: chunks ----------------
    chunks = sorted(story_dir.glob("chunk_*.json"))

    def do_chunk(path: Path) -> dict:
        chunk = json.loads(path.read_text(encoding="utf-8"))
        part_f = story_dir / f"part_{chunk['index']:02d}.json"
        if part_f.is_file() and not args.force:
            print(f"chunk {chunk['index']}: resuming saved part", file=sys.stderr)
            return json.loads(part_f.read_text(encoding="utf-8"))
        idx = chunk["index"]
        # state = concatenation of previous chunks' states (in order)
        states = []
        for i in range(1, idx):
            pf = story_dir / f"part_{i:02d}.json"
            if pf.is_file():
                states.append(json.loads(pf.read_text(encoding="utf-8"))
                              .get("state", ""))
        state = "\n".join(s for s in states if s)[-1500:]

        print(f"chunk {idx}: {len(chunk['events'])} events -> LLM ...",
              file=sys.stderr)
        content = llm_call(
            cfg, system_base,
            chunk_prompt(system_base, chunk, state, hook_seconds),
            max_tokens=args.max_tokens_chunk)
        parsed = parse_response(content)

        allowed = {e["id"] for e in chunk["events"]}
        allowed |= {e["id"] for e in chunk.get("prev_tail", [])}
        must_cover = [e for e in chunk["events"]
                      if e["type"] == "dialogue"
                      and not (idx == 1 and e["t"] < hook_seconds)]
        narration = validate_narration(parsed["narration"], allowed,
                                       must_cover, events_by_id)
        fallbacks = [n["id"] for n in narration if n.get("fallback")]
        part = {
            "index": idx,
            "range": chunk["range"],
            "narration": narration,
            "state": (parsed["state"] or "")[:1500],
            "fallbacks": fallbacks,
        }
        part_f.write_text(json.dumps(part, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print(f"chunk {idx}: done ({len(narration)} lines, "
              f"{len(fallbacks)} fallbacks)", file=sys.stderr)
        return part

    if args.parallel > 1:
        with cf.ThreadPoolExecutor(max_workers=args.parallel) as ex:
            parts = list(ex.map(do_chunk, chunks))
    else:
        parts = [do_chunk(p) for p in chunks]
    parts.sort(key=lambda p: p["index"])

    # ---------------- phase 2: consolidation ----------------
    final_part_f = story_dir / "part_final.json"
    if args.no_consolidate or len(parts) == 1:
        final_narration = [n for p in parts for n in p["narration"]]
        hook = ""
        consolidated = False
        # small single-chunk films still get a hook: one extra call
        if not args.no_consolidate:
            print("hook pass (single-chunk film) ...", file=sys.stderr)
            try:
                content = llm_call(
                    cfg, system_base,
                    consolidate_prompt(system_base, parts, movie,
                                       hook_seconds),
                    max_tokens=args.max_tokens_consolidate)
                parsed = parse_response(content)
                if parsed["narration"] and parsed["hook"]:
                    allowed = set(events_by_id)
                    must = [e for e in events_all
                            if e["type"] == "dialogue"
                            and e["t"] >= hook_seconds]
                    final_narration = validate_narration(
                        parsed["narration"], allowed, must, events_by_id)
                    hook = parsed["hook"]
                    consolidated = True
            except RuntimeError as e:
                print(f"WARNING: hook pass failed ({e}) — continuing "
                      f"without hook", file=sys.stderr)
    else:
        print("consolidation pass ...", file=sys.stderr)
        content = llm_call(
            cfg, system_base,
            consolidate_prompt(system_base, parts, movie, hook_seconds),
            max_tokens=args.max_tokens_consolidate)
        parsed = parse_response(content)
        allowed = set(events_by_id)
        must = [e for e in events_all
                if e["type"] == "dialogue" and e["t"] >= hook_seconds]
        final_narration = validate_narration(
            parsed["narration"], allowed, must, events_by_id)
        hook = parsed["hook"]
        consolidated = True
        final_part_f.write_text(
            json.dumps({"narration": final_narration, "hook": hook},
                       ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- phase 3: mechanical assembly ----------------
    entries = []
    if hook:
        entries.append((0.0, tts_clean(hook)))
    for n in final_narration:
        e = events_by_id.get(n["id"])
        if not e:
            continue
        if e["t"] < hook_seconds and entries and entries[0][0] == 0.0:
            continue  # replaced by the hook
        text = tts_clean(n["text"])
        if text:
            entries.append((e["t"], text))
    entries.sort(key=lambda x: x[0])
    # dedupe identical start times
    deduped = []
    for t, text in entries:
        if deduped and abs(deduped[-1][0] - t) < 0.2:
            continue
        deduped.append((t, text))
    entries = deduped

    if not entries:
        print("ERROR: assembly produced no entries", file=sys.stderr)
        return 1

    out = (Path(args.out).expanduser().resolve()
           if args.out else Path.cwd() / f"{title} VO.srt")
    write_srt(entries, out)

    # ---------------- phase 4: verification ----------------
    dialogue_all = [e for e in events_all if e["type"] == "dialogue"]
    covered = {n["id"] for n in final_narration}
    dialogue_covered = len([e for e in dialogue_all if e["id"] in covered])
    fallback_lines = sum(1 for n in final_narration if n.get("fallback"))
    duration = max(e["t_end"] for e in events_all)
    report = {
        "ok": True,
        "srt": str(out),
        "title": title,
        "language": movie["language"],
        "entries": len(entries),
        "hook": bool(hook),
        "consolidated": consolidated,
        "dialogue_total": len(dialogue_all),
        "dialogue_covered": dialogue_covered,
        "fallback_lines": fallback_lines,
        "duration_seconds": round(duration, 1),
        "llm_model": cfg["LLM_MODEL"],
        "chunks": len(parts),
    }
    (story_dir / "verify.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
