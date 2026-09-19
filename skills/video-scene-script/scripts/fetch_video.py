#!/usr/bin/env python3
"""
fetch_video.py — resolve a pipeline input (local file path OR url) into a
local video file, and report its real title.

Usage:
  python3 fetch_video.py <url-or-local-file> --work-dir .work
  python3 fetch_video.py <xhs/youtube-url> --work-dir .work --cookies cookies.txt

Prints ONE JSON object on stdout (nothing else):
  {"source": "...", "video": "/abs/path/file.mp4",
   "title": "Movie Name", "slug": "movie-name", "downloaded": false}

Sources:
  - YouTube / generic URLs   -> yt-dlp (auto-installed via pip if missing)
  - RedNote / Xiaohongshu    -> built-in extractor: resolves xhslink.com
    short links, parses the note page's __INITIAL_STATE__ (mobile UA,
    works anonymously for public notes), downloads the stream CDN URL.
    Falls back to yt-dlp (with --cookies when given) if parsing fails.
  - local file               -> used in place. This script NEVER copies or
    deletes a local file; cleanup must not touch the user's source either.

--cookies: Netscape-format cookies.txt. For XHS, matching cookies are added
to the page request (helps when a note requires login); for other platforms
they are passed through to yt-dlp.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

XHS_HOSTS = ("xiaohongshu.com", "xhslink.com", "xhscdn.com", "xiaohongshu.cn")
XHS_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
          "Mobile/15E148 Safari/604.1")


def is_url(s: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s.strip()))


def is_xhs(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in XHS_HOSTS)


def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE).strip()
    s = re.sub(r"[\s_]+", "-", s)
    return s[:80].strip("-") or "video"


def run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def http_get(url: str, headers: dict, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------------------- #
# Xiaohongshu / RedNote (built-in extractor)
# --------------------------------------------------------------------------- #

def xhs_resolve_short(url: str) -> str:
    """Follow xhslink.com 302 to the canonical /discovery/item/ URL."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": XHS_UA})
    try:
        opener.open(req, timeout=30)
        return url  # no redirect observed
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        if loc:
            return loc
        raise RuntimeError(f"xhslink resolved without Location (HTTP {e.code})")


def cookie_header_for(cookies_file: str, host: str) -> str:
    """Build a Cookie header from Netscape cookies.txt entries for host."""
    pairs = []
    try:
        lines = Path(cookies_file).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise RuntimeError(f"cannot read cookies file: {e}")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        dom = parts[0].lstrip(".")
        if host == dom or host.endswith("." + dom):
            pairs.append(f"{parts[5]}={parts[6]}")
    return "; ".join(pairs)


def xhs_extract(url: str, cookie: str = None) -> dict:
    """Fetch the note page and pull title + video stream URL from
    __INITIAL_STATE__ (mobile UA; anonymous for public notes)."""
    headers = {"User-Agent": XHS_UA, "Accept-Language": "en"}
    if cookie:
        headers["Cookie"] = cookie
    html = http_get(url, headers).decode("utf-8", "replace")

    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>",
                  html, re.S)
    if not m:
        raise RuntimeError("note page has no __INITIAL_STATE__ "
                           "(login/captcha wall?)")
    state = json.loads(m.group(1).replace("undefined", "null"))

    # locate the note object (path varies between page versions)
    def find_key(obj, key, found):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == key and isinstance(v, dict) and "video" in v:
                    found.append(v)
                else:
                    find_key(v, key, found)
        elif isinstance(obj, list):
            for v in obj[:10]:
                find_key(v, key, found)

    notes = []
    find_key(state, "noteData", notes)
    if not notes:
        # fallback: any dict containing a video.media.stream block
        found_videos = []

        def find_stream(obj):
            if isinstance(obj, dict):
                if "media" in obj and isinstance(obj["media"], dict):
                    found_videos.append(obj)
                for v in obj.values():
                    find_stream(v)
            elif isinstance(obj, list):
                for v in obj[:10]:
                    find_stream(v)

        find_stream(state.get("noteData", state))
        notes = found_videos

    if not notes:
        raise RuntimeError("no note/video data found in page state")
    note = notes[0]

    title = (note.get("title") or note.get("desc") or "video").strip()
    title = re.sub(r"\.{4,}$", "...", title)[:120] or "video"
    nid = note.get("noteId") or note.get("id")
    if not nid:
        m2 = re.search(r"/(?:discovery/item|item)/([0-9a-f]+)", url)
        nid = m2.group(1) if m2 else slugify(title)

    video = note.get("video") or note
    stream = ((video.get("media") or {}).get("stream")
              or (video.get("stream") if isinstance(video.get("stream"), dict)
                  else None) or {})
    urls = []
    for codec in ("h264", "hevc"):
        arr = stream.get(codec) or []
        if arr:
            if arr[0].get("masterUrl"):
                urls.append(arr[0]["masterUrl"])
            urls.extend(u for u in (arr[0].get("backupUrls") or []) if u)
    if not urls:
        raise RuntimeError("no video stream URL in note state "
                           "(note may require login)")
    return {"title": title, "id": str(nid), "urls": urls}


def xhs_download(urls: list, dest: Path, referer: str) -> None:
    """Download the video trying each candidate URL (master, then backups),
    verifying the byte count against Content-Length and retrying transient
    truncation."""
    last_err = None
    part = dest.with_suffix(".part")
    for url in urls:
        for attempt in range(2):
            try:
                headers = {"User-Agent": XHS_UA, "Referer": referer}
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=120) as r:
                    expected = r.headers.get("Content-Length")
                    expected = int(expected) if expected else None
                    with open(part, "wb") as f:
                        shutil.copyfileobj(r, f, length=1 << 20)
                size = part.stat().st_size
                if expected is not None and size != expected:
                    raise IOError(f"truncated: got {size} of {expected} bytes")
                if size < 20_000:
                    raise IOError(f"file suspiciously small ({size} bytes)")
                part.rename(dest)
                return
            except (IOError, OSError, urllib.error.URLError) as e:
                last_err = e
                part.unlink(missing_ok=True)
    raise RuntimeError(f"XHS video download failed on all URLs: {last_err}")


def fetch_xhs(src: str, work: Path, cookies: str = None) -> dict:
    url = src
    if "xhslink.com" in url:
        url = xhs_resolve_short(url)
    cookie = None
    if cookies:
        host = urllib.parse.urlparse(url).netloc.lower()
        cookie = cookie_header_for(cookies, host) or None
    try:
        info = xhs_extract(url, cookie=cookie)
    except RuntimeError as e:
        print(f"NOTE: direct XHS extraction failed ({e}) — "
              "trying yt-dlp ...", file=sys.stderr)
        return fetch_ytdlp(url, work, cookies=cookies)
    dest = work / f"{info['id']}.mp4"
    xhs_download(info["urls"], dest, referer=url)
    return {"video": str(dest), "title": info["title"], "downloaded": True}


# --------------------------------------------------------------------------- #
# yt-dlp path (YouTube + generic URLs)
# --------------------------------------------------------------------------- #

def find_ytdlp() -> list:
    """Locate yt-dlp, installing it with pip when missing."""
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    if run([sys.executable, "-c", "import yt_dlp"]).returncode == 0:
        return [sys.executable, "-m", "yt_dlp"]
    print("NOTE: yt-dlp not found — installing via pip ...", file=sys.stderr)
    r = run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"])
    if r.returncode != 0:
        raise RuntimeError(f"could not install yt-dlp: {r.stderr.strip()[-400:]}")
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    if run([sys.executable, "-c", "import yt_dlp"]).returncode == 0:
        return [sys.executable, "-m", "yt_dlp"]
    raise RuntimeError("yt-dlp installed but not found on PATH")


def fetch_ytdlp(src: str, work: Path, cookies: str = None) -> dict:
    yt = find_ytdlp()
    cookie_args = ["--cookies", cookies] if cookies else []

    # 1) metadata (simulation, no download) for the real title + id
    title, vid = "video", None
    r = run(yt + ["--no-playlist", "-J", *cookie_args, src])
    if r.returncode == 0:
        try:
            d = json.loads(r.stdout)
            title = d.get("title") or "video"
            vid = d.get("id") or slugify(title)
        except (json.JSONDecodeError, AttributeError):
            pass
    if vid is None:
        vid = slugify(Path(src.split("?")[0]).stem or title)
        title = title if title != "video" else Path(src.split("?")[0]).stem or "video"

    # 2) download best mp4 into the work dir
    out_tpl = str(work / f"{vid}.%(ext)s")
    r = run(yt + [
        "--no-playlist",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", out_tpl,
        *cookie_args,
        src,
    ])
    if r.returncode != 0:
        raise RuntimeError(
            f"yt-dlp download failed: {r.stderr.strip()[-500:]}")

    # 3) locate the produced file (id + any extension, prefer mp4)
    candidates = [p for p in work.glob(f"{vid}.*") if p.is_file()]
    if not candidates:
        raise RuntimeError("download finished but no output file found")
    best = min(candidates, key=lambda p: (p.suffix != ".mp4",
                                          -p.stat().st_size))
    return {"video": str(best), "title": title, "downloaded": True}


def fetch_url(src: str, work: Path, cookies: str = None) -> dict:
    if is_xhs(src):
        return fetch_xhs(src, work, cookies=cookies)
    return fetch_ytdlp(src, work, cookies=cookies)


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="video URL or local file path")
    ap.add_argument("--work-dir", required=True,
                    help="directory for downloaded videos (e.g. .work)")
    ap.add_argument("--cookies", default=None,
                    help="Netscape-format cookies.txt for login-protected "
                         "sources (RedNote/Xiaohongshu, private YouTube)")
    args = ap.parse_args()

    src = args.input.strip().strip("'\"")
    work = Path(args.work_dir).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)

    try:
        if is_url(src):
            result = fetch_url(src, work, cookies=args.cookies)
        else:
            local = Path(src).expanduser().resolve()
            if not local.is_file():
                raise RuntimeError(f"local file not found: {local}")
            result = {"video": str(local), "title": local.stem,
                      "downloaded": False}
        result["source"] = src
        result["slug"] = slugify(result["title"])
    except (RuntimeError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
