# Per-Minute Script Text — Format & Style

`script.txt` (or `script_partN.txt` in parts mode) is the only text the
vision analyst writes. `make_srt.py` supplies all numbering and timestamps.
Do not hand-type SRT timestamps.

## Format

```text
# language: en
rainy bus stop at night; red-coat woman checks her watch, then walks away
market street; grey-suit man stops at a shuttered shop, a cut to the alley
red-coat woman crosses the empty yard; grey-suit man watches from a doorway
```

- The first line is `# language: <movie-original-language-code>`.
- Each non-empty, non-comment line is exactly one 60-second manifest segment,
  in order. The count must equal the manifest segment count/range.
- Keep each entry on one line. Use short present-tense phrases joined with
  semicolons or commas.

## Plot-aware style

Dialogue context gives the **WHY**; frames give the visible **WHO, WHERE, and
WHAT CHANGES**. Write a compact plot-aware beat, not an object list:

- Normal minutes: 1–3 phrases.
- Dialogue-free gap minutes: richer entries, up to 4–5 phrases when the
  denser `gap-uniform`/`gap-scene` frames show meaningful wordless action.
- Keep a stable clothing/appearance tag until dialogue makes a real name
  confident. Do not force a name onto an ambiguous face.
- A `scene` reason supports a visible `cut to ...`; it does not prove all
  unseen action between samples.
- A short verbatim quote is allowed only when a readable subtitle is the
  minute's key beat. The audio SRT already carries the full dialogue, so do
  not copy whole subtitle lines into visual entries.
- Hedge unclear or inferred material (`appears to`, `unclear`, or the
  equivalent in the movie's language).

## Hard rules

- Original movie language, never the user's language; readable on-screen text
  may remain verbatim in its original language.
- No `we see`, `there is`, `the camera shows`, audio/music claims, invented
  speech, unseen motives, or exact events that the frames cannot establish.
- Mention facial expressions only when distinctive and visibly factual:
  crying, shouting, laughing, glaring, fear, shock, pain, or exhaustion.
  Omit neutral or too-small faces.
- `dialogue.txt` is context, not a script to copy. Keep visual evidence and
  spoken/plot meaning distinct.

## Examples

```text
# language: en
rainy bus stop, night; red-coat woman checks her watch
cut to the market street; grey-suit man stops at a shuttered shop
red-coat woman crosses the yard with a bag; man watches from the doorway
empty road after dark; red-coat woman runs, face visibly fearful; unclear what she carries
```

For a static minute, one precise phrase is better than padding. For a gap
minute, use the extra density to connect visible actions into the film's
wordless story without inventing what is not shown.
