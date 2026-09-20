# Sub-Agent Brief — Delegating Part Runs (videos > 15 minutes)

When `make_frames.py` prints `PLAN: {"mode": "parts", ...}`, the video was
longer than 15 minutes and its frames were auto-split into part folders
(`part1/`, `part2/`, …, ≤ 15 min each). **The parent agent must NOT view
those frames itself** — delegate every part to its own sub-agent /
background task, using the brief below.

The briefs are fully independent: each part has its own folder, manifest,
script text, and output SRT. Run them **as your environment allows** —
in parallel, as background tasks, or sequentially, whichever works. The
parent only collects the results and merges.

---

## The brief (fill every `{{...}}`, then dispatch verbatim)

```
You are a visual-analysis worker for ONE part of a movie. Do exactly what
is written here — nothing more.

MOVIE TITLE : {{TITLE}}
YOUR PART   : part {{N}} of {{TOTAL_PARTS}}
FRAMES DIR  : {{FRAMES_DIR}}              (absolute path)
MANIFEST    : {{FRAMES_DIR}}/manifest.json
SEGMENTS    : {{A}}–{{B}} (minutes of the film; your manifest lists them)
LANGUAGE    : {{LANGUAGE_CODE or "determine it yourself per vision-prompt.md before writing"}}
YOUR OUTPUT : {{OUTPUT_SRT}}              (absolute path, e.g. .work/parts/part{{N}}.srt)
SKILL DIR   : {{SKILL_DIR}}               (absolute path to skills/video-scene-script)

Steps, in order:
1. Read {{SKILL_DIR}}/references/vision-prompt.md and follow it EXACTLY for
   every frame — it is the complete vision instruction set (per-frame
   viewing, cast list, facial-expression rule, phrase style).
2. Read {{FRAMES_DIR}}/manifest.json. Note your segment range ({{A}}–{{B}})
   and which frame files belong to each minute.
3. View EVERY frame image in your folder, one at a time, in time order.
   Never skip a frame and never write entries from filenames alone.
4. Write {{SCRIPT_TXT}}: first line `# language: <code>`, then EXACTLY
   {{B}}−{{A}}+1 phrase lines — one line per minute, in time order,
   following vision-prompt.md's output format. No extra lines.
5. Build your part SRT:
     python3 {{SKILL_DIR}}/scripts/make_srt.py \
         {{FRAMES_DIR}}/manifest.json {{SCRIPT_TXT}} --out {{OUTPUT_SRT}}
   Use --bom if the language is CJK or a script some players mishandle.
   If it warns about a line-count mismatch, fix the text file and rerun —
   never hand-edit the .srt.
6. Report back ONE JSON line:
   {"part": {{N}}, "srt": "{{OUTPUT_SRT}}", "entries": <count>,
    "language": "<code>", "ok": true}

Hard rules:
- Handle ONLY part {{N}}. Never touch other part folders, other part
  SRTs, or the merge step — the parent merges.
- Never delete or modify: the video file, other parts' files, .work
  scaffolding outside your own outputs, or the user's files.
- Your SRT must not be hand-typed — it comes out of make_srt.py only.
- No audio analysis; visual only. Nothing is invented.
```

`{{SCRIPT_TXT}}` is `.work/script_part{{N}}.txt` (absolute or relative to
the parent's working directory — give the sub-agent a path it can write).

---

## Parent checklist (after dispatching)

1. **Dispatch:** one brief per part; create `.work/parts/` first
   (`mkdir -p .work/parts`) so sub-agents can write their SRTs.
2. **Collect:** every part must report back. If a sub-agent fails or its
   `entries` ≠ its segment count, re-dispatch just that part with the same
   brief (optionally as a fresh task).
3. **Verify:** each `.work/parts/partN.srt` exists and is non-empty before
   merging (quick check: `wc -l .work/parts/*.srt` / read the JSON lines).
4. **Merge** (parent, once all parts exist):
   ```bash
   python3 scripts/merge_srt.py .work/parts/part1.srt .work/parts/part2.srt \
       ... --out "<Movie Name>.srt"
   ```
   It renumbers and warns about timeline gaps/overlaps — a warning means
   that part's range was wrong; re-run that part.
5. **Cleanup + deliver** per SKILL.md steps 6–7.
