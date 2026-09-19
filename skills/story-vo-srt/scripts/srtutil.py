"""srtutil.py — shared SRT parsing / formatting helpers (stdlib only)."""

import re
from pathlib import Path

TS_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})$")


def ts(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(path) -> list:
    """Returns [{start, end, text}, ...] sorted by start time."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    entries = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        m = TS_RE.match(lines[1].strip())
        if not m:
            continue
        g = list(map(int, m.groups()))
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = " ".join(" ".join(lines[2:]).split())
        if text:
            entries.append({"start": start, "end": end, "text": text})
    entries.sort(key=lambda e: (e["start"], e["end"]))
    return entries


def write_srt(entries, out_path) -> None:
    """entries: [(start, text), ...] — duration = gap to next entry start."""
    blocks = []
    for i, (start, text) in enumerate(entries, 1):
        end = entries[i][0] if i < len(entries) else start + 5.0
        if end <= start:
            end = start + 1.0
        blocks.append(f"{i}\n{ts(start)} --> {ts(end)}\n{text}\n")
    Path(out_path).write_text("".join(blocks), encoding="utf-8")


def guess_lang(text: str) -> str:
    """Rough script detection over a sample of text."""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    mym = sum(1 for c in text if "\u1000" <= c <= "\u109f")
    total = max(1, len(text))
    if cjk / total > 0.08:
        return "zh (Chinese)"
    if mym / total > 0.08:
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
    """Backstop cleanup for TTS-ready lines."""
    t = re.sub(r"\[(E\d{3,6})\]", "", text)          # event ids
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27bf]", "", t)  # emoji
    t = re.sub(r"\{[^}]*\}", "", t)                   # stage braces
    t = t.replace("…", " ").replace("——", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t
