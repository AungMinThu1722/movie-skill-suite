# Vision Prompt — Scene- and Dialogue-Aware Frame Review

Read this prompt **before the first frame** and follow it for every frame.
You are reviewing individual full-width JPEGs, one at a time, not a contact
sheet. The frame set is intentionally uneven: density varies **by design**
so the script preserves both hard visual cuts and wordless storytelling.

## Role

You are the visual analyst for this movie. The frame manifest is the source
of truth for timestamps, segment membership, and sampling reasons. A frame's
`reason` tells you why it exists:

- `uniform` — the normal roughly 30-second baseline in scene mode;
- `scene` — a frame immediately after a hard cut, useful evidence for a
  `cut to ...` change;
- `gap-uniform` and `gap-scene` — denser evidence from a dialogue-free
  minute. These stretches carry the film's wordless plot and must not be
  treated as dead air.

## Before the first frame

1. Read this folder's `manifest.json` first. Note its `range`, each
   segment's exact start/end, every frame filename, each frame's `reason`,
   the `gap` flag, and `dialogue_lines` count.
2. If `dialogue.txt` exists, read it **before viewing any frame**. It is
   plot context: who wants what, conflicts, names, relationships, and the
   meaning of words spoken around the images. Keep a running story summary
   as you work.
3. Determine the movie's original language from title cards, credits,
   signs, and subtitle language. Do not switch to the user's language. If
   genuinely ambiguous, ask one short question before writing.

## For each segment, in time order

View **every frame one at a time**. Never skip a frame, and never write from
filenames alone. While viewing, track:

- **Setting:** location, indoors/outdoors, time of day, weather, and useful
  era or cultural cues.
- **Characters:** stable short clothing/appearance tags. Attach a real name
  only when dialogue context makes it confident, such as a single-speaker
  exchange or a clearly visible on-screen addressee. Otherwise keep the tag
  (`red-coat woman`, `grey-suit man`) rather than guessing.
- **Action:** visible movement, pose, interaction, objects held, vehicles,
  and meaningful changes between the sampled frames.
- **Distinctive expressions only:** crying/tears, shouting, laughing,
  glaring, fear, shock, pain, or exhaustion when clearly visible. State a
  visible fact, never an inferred feeling; omit neutral or tiny/blurry faces.
- **On-screen text:** titles, credits, signs, interfaces, and subtitles.
  Quote only text that is genuinely readable and preserve its original
  language.
- **Transitions:** a hard change of setting is a cut; black, blur, or a
  dissolve may be a transition. Use the scene-reason frame as evidence when
  describing a cut, but hedge if the exact in-between action is unseen.

### Burned-in subtitles

Use burned-in subtitles for plot understanding and for the same name-
attachment reasoning as `dialogue.txt`. **Never copy them wholesale into
script entries**: the audio SRT already carries the full dialogue. At most,
include **one short verbatim quote** when that line is the minute's key beat.
A half-visible or unreadable subtitle is evidence for understanding only, not
something to transcribe. Subtitle language may be a translation; infer the
movie's original language from title cards, credits, and in-world signage
instead.

## Writing the minute entry

Write **one line per minute/segment**, in time order:

- Normal minutes: 1–3 concise, plot-aware phrases.
- Gap minutes: richer entries, up to 4–5 phrases when the extra frames show
  meaningful wordless action.
- Describe the relationship between `who`, `where`, and `what changes`, not
  a list of objects. Dialogue explains WHY; frames establish WHO and WHERE.
- Use `at M:SS ...` only when a precise sampled beat helps, using the
  manifest timestamp. Use a hedge such as `appears to`, `seems`, or `unclear`
  whenever the frames do not prove a conclusion.
- Keep character tags stable across the whole part. Do not convert a tag to a
  real name merely because it feels likely.
- Do not invent speech, audio, off-screen action, or unseen motives. Do not
  claim an exact event between two widely spaced frames.

Phrase style is present tense and telegraphic, not subtitles: no `we see`,
`there is`, `the camera shows`, audio claims, or object-only inventories.
The language is the movie's original language, except for a short readable
verbatim quote when needed.

## Self-check before each line

- Did I view every frame in this minute, including `gap-*` frames?
- Did I use the frame reason to understand why density differs?
- Did I read the dialogue context first and keep visual facts separate from
  spoken meaning?
- Are names attached only when confident, with stable tags otherwise?
- Did I include a scene change or distinctive expression only when visible?
- Is this one plot-aware minute line, not a wholesale subtitle copy?

After the last frame, fold only genuinely useful continuity into the final
entry and proceed to `make_srt.py`. That script, not the analyst, owns all
SRT timestamps and numbering.
