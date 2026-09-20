"""srtutil.py — shared SRT parsing, formatting, and TTS helpers."""

import re
from pathlib import Path

TS_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})$"
)


def ts(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def parse_srt(path) -> list:
    """Return [{start, end, text}, ...] sorted by start time."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    entries = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        match = TS_RE.match(lines[1].strip())
        if not match:
            continue
        values = list(map(int, match.groups()))
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        text = " ".join(" ".join(lines[2:]).split())
        if text and end > start:
            entries.append({"start": start, "end": end, "text": text})
    entries.sort(key=lambda entry: (entry["start"], entry["end"]))
    return entries


def write_srt(entries, out_path) -> None:
    """Write explicit (start, end, text) entries as an SRT.

    The legacy two-tuple form (start, text) is still accepted for callers
    outside this skill; its end is the next entry's start or start+5 seconds.
    Story VO now uses explicit TTS-calculated ends.
    """
    normalized = []
    for index, entry in enumerate(entries):
        if len(entry) == 3:
            start, end, text = entry
        elif len(entry) == 2:
            start, text = entry
            end = entries[index + 1][0] if index + 1 < len(entries) else start + 5.0
        else:
            raise ValueError("SRT entry must be (start, text) or (start, end, text)")
        start = float(start)
        end = max(start + 0.001, float(end))
        normalized.append((start, end, str(text)))

    blocks = []
    for index, (start, end, text) in enumerate(normalized, 1):
        blocks.append(f"{index}\n{ts(start)} --> {ts(end)}\n{text}\n")
    Path(out_path).write_text("\n".join(blocks), encoding="utf-8")


def guess_lang(text: str) -> str:
    """Rough source-script detection over a sample of text."""
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    burmese = sum(1 for char in text if "\u1000" <= char <= "\u109f")
    total = max(1, len(text))
    if cjk / total > 0.08:
        return "zh (Chinese)"
    if burmese / total > 0.08:
        return "my (Burmese)"
    if re.search(r"[\u0e00-\u0e7f]", text):
        return "th (Thai)"
    if re.search(r"[\u0900-\u097f]", text):
        return "Devanagari (hi/bn/ne)"
    if re.search(r"[\u0400-\u04ff]", text):
        return "Cyrillic (ru/el-ru...)"
    if re.search(r"[\u0600-\u06ff]", text):
        return "ar (Arabic)"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko (Korean)"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja (Japanese)"
    return "latin script (en or other)"


def tts_clean(text: str) -> str:
    """Backstop cleanup for plain TTS-ready text."""
    cleaned = re.sub(r"\[(?:E\d{3,6})(?:\s*,\s*E\d{3,6})*\]", "", text)
    cleaned = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27bf]", "", cleaned)
    cleaned = re.sub(r"\{[^}]*\}", "", cleaned)
    cleaned = cleaned.replace("…", " ").replace("——", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def unicode_chars(text: str) -> int:
    """The AMTrecap calibration count: Python Unicode codepoints."""
    return len(text)
