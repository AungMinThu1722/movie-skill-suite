# Vision Prompt — Per-Grid Analysis

Read this prompt BEFORE looking at any grid, and follow it strictly for
EVERY grid. It is the complete instruction set for the vision pass.

---

## Role

You are the visual analyst for this movie. You see 9 frames per minute,
sampled ~6.7 s apart, in chronological order (left → right, top → bottom).
Your job: produce one terse **phrase entry** per minute describing what
happened — not subtitles, not full sentences.

## For each grid, in order

1. **Read the title bar** — note the segment range (e.g. `04:00 - 05:00`).
2. **Scan cell 1 → cell 9**, tracking:
   - **Setting:** where are we? A cell that changes location = new scene —
     note it ("cut to kitchen").
   - **Characters:** who is on screen? Keep a running cast list with a
     stable short tag (e.g. `grey-suit man`, `red-coat woman`). New face →
     add to cast list with one identifying detail (clothing, hair, age).
   - **Action:** what is visibly happening? Poses, gestures, movement
     between cells, objects in hand, vehicles.
   - **Facial expressions — ONLY distinctive ones.** Skip neutral/standard
     faces entirely. Note an expression only when it stands out:
     crying/tears, shouting/open-mouth yell, laughing, glaring/anger,
     fear, shock/wide eyes, pain, exhaustion. State it as visible fact
     (`woman's face contorted, sobbing`) — never as inferred emotion
     (`she is sad`).
     - If the face is too small/blurry to judge, write nothing about it.
   - **On-screen text:** titles, credits, signs, subtitles, UI — quote
     exactly, verbatim, in its original language.
   - **Transitions:** black/fade cells or hard cuts between cells.
3. **Self-check before writing the entry** (answer silently):
   - Did I name every NEW character with a stable tag?
   - Any distinctive facial expression this minute? (most minutes: none)
   - Any on-screen text to quote?
   - Any scene change (new setting) inside this minute?
4. **Write the phrase entry** (see Output format).

## Output format (per minute = ONE LINE in the text file)

- **One line per minute** in `script.txt` / `script_partN.txt` (blank lines
  and `#` comment lines are ignored by the SRT builder).
- **Phrases, not sentences.** Telegraphic style, present tense, separated
  by `;` or `,`. No "we see", "there is", "the camera shows".
- 1–3 short phrases per minute. A static minute = one short phrase.
- Order: setting/scene → who → what happens → (notable expression) →
  (quoted on-screen text).
- One beat may carry a rough in-minute time: `at 4:36 ...`
- **No audio, no music, no exact speech.** Mouth open = "shouting face",
  not a quote of words.
- **No invention.** If cells are ambiguous, use one hedge phrase
  (`unclear` / equivalent in the movie's language) instead of guessing.

## Language

Write every entry in **the movie's original language** (determined once
before the first grid from title cards/credits/on-screen text — if
ambiguous, ask the user). Phrase style in that language; keep cast tags
consistent across all minutes.

## Examples

English movie:
```
rainy bus stop, night; red-coat woman checks watch, then starts walking
market street, wide; grey-suit man walks against crowd, stops at shuttered shop
grey-suit man: open-mouth shouting face, points at shop sign; sign reads "CLOSED"
kitchen cut; red-coat woman pours tea, face neutral
```

Chinese movie (same style, Chinese phrases):
```
雨夜公交站；红大衣女子看表，开始走动
集市大街，远景；灰西装男子逆行，停在关门的店前
灰西装男子：张口大喊的表情，指向店招牌；招牌写着"CLOSED"
切到厨房；红大衣女子倒茶，表情平静
```

---

After the last grid: fold anything notable about the cast/expressions into
the final entries if it matters, and move on to step 4 of the pipeline
(write script.txt / script_partN.txt).
