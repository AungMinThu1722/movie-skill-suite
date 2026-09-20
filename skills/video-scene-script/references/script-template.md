# Per-Minute Script Text (script.txt) — Format & Style

`script.txt` (or `script_partN.txt` for delegated part runs) is the ONLY
thing you write. `make_srt.py` turns it into SRT, so add no numbers or
timestamps.

## Format — ONE LINE PER SEGMENT (minute)

```
# language: zh
rainy bus stop at night; red-coat woman checks watch, then walks off
market street, wide; grey-suit man stops at shuttered shop
grey-suit man: open-mouth shouting face, points at sign; sign reads "CLOSED"
```

- **Each non-empty line = exactly one segment entry**, in time order.
  Keep each entry to a single line (short phrases).
- Line count must match the segment count in your `manifest.json`
  (`range` — the frames script prints it too).
- For delegated part runs: part N's file contains exactly the lines for
  its segment range — no more, no less.
- First line is a comment: `# language: <code>`. Blank lines and `#` lines
  are ignored (use them freely to separate parts while writing).

## Style (phrase-based — NOT subtitles)

- **Short phrases / sentence fragments, present tense**, joined by `;`/`,`.
  Telegraphic: `market street; grey-suit man stops at shuttered shop`.
- **1–3 phrases per minute.** Static content = one phrase; do not pad.
- No "we see / there is / the camera shows". No dialogue, no audio, no
  music, no invented words.
- **Facial expressions only when distinctive** (crying, shouting, laughing,
  glaring, fear, shock, pain) and only as visible fact:
  `woman's face contorted, sobbing` / `man: wide-eyed shock face`.
  Never inferred emotion. Neutral face → write nothing.
- **Characters:** stable short tags, first seen = one identifying detail:
  `red-coat woman`, `grey-suit man`, `old man with cane`.
- **Scene changes inside a minute:** `cut to kitchen` / `cut to street`.
- **On-screen text:** quote verbatim in its original language:
  `sign reads "CLOSED"`.
- **Unclear frames:** one hedge phrase (`unclear` / movie-language
  equivalent) — never guess.
- Full analysis rules (what to look for per frame): `vision-prompt.md`.

## Language

The movie's **original language** — never the user's language, never mixed
(except verbatim on-screen text). Ambiguous → ask the user once before
writing.

## Examples (English movie → English phrases, one line per minute)

```
# language: en
rainy bus stop, night; red-coat woman checks watch, then starts walking
market street, wide; grey-suit man walks against crowd, stops at shuttered shop
grey-suit man: open-mouth shouting face, points at shop sign; sign reads "CLOSED"
cut to kitchen; red-coat woman pours tea, face neutral
```

## Examples (Chinese movie → Chinese phrases, one line per minute)

```
# language: zh
雨夜公交站；红大衣女子看表，开始走动
集市大街，远景；灰西装男子逆行，停在关门的店前
灰西装男子：张口大喊的表情，指向店招牌；招牌写着"CLOSED"
切到厨房；红大衣女子倒茶，表情平静
```
