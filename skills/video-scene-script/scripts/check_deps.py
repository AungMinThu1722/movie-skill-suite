#!/usr/bin/env python3
"""
check_deps.py — auto-check and (re)install every pipeline dependency.

Run this as the FIRST step of the pipeline (or right after a new session
starts, when tools may have been wiped). It is idempotent and fast when
everything is already present.

Checks / repairs:
  1. ffmpeg + ffprobe : if missing, downloads a static build into
     ~/.local/ffmpeg-static and symlinks it into ~/.local/bin
  2. yt-dlp           : pip install if missing
  3. Pillow           : pip install if missing (needed for labeled grids;
                        the pipeline degrades to unlabeled grids without it)

Prints ONE JSON object on stdout:
  {"ok": true, "ffmpeg": "7.0.2", "ffprobe": "7.0.2", "yt_dlp": "2026.x",
   "pillow": "12.x", "path_add": ["/home/user/.local/bin"], "installed": []}

`installed` lists what was fetched this run; `path_add` are directories the
caller should prepend to PATH before running the other pipeline scripts.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

STATIC_BUILD_URLS = {
    "x86_64": "https://johnvansickle.com/ffmpeg/releases/"
              "ffmpeg-release-amd64-static.tar.xz",
    "aarch64": "https://johnvansickle.com/ffmpeg/releases/"
               "ffmpeg-release-arm64-static.tar.xz",
}

installed = []


def run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def version_of(binary: str) -> str:
    try:
        r = run([binary, "-version"])
    except (FileNotFoundError, OSError):
        return "missing"
    if r.returncode != 0:
        return "missing"
    m = re.search(r"(\d+(?:\.\d+)+)", r.stdout)
    return m.group(1) if m else "present"


def _link(bin_dir: Path, name: str, target: Path) -> None:
    link = bin_dir / name
    try:
        if not link.exists():
            link.symlink_to(target)
    except FileExistsError:
        link.unlink()
        link.symlink_to(target)


def ensure_ffmpeg(bin_dir: Path):
    """Returns (ffmpeg_path, ffprobe_path); installs a static build when the
    pair is not fully usable."""
    ff_sys, fp_sys = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ff_sys and fp_sys:
        return ff_sys, fp_sys

    static_dir = bin_dir.parent / "ffmpeg-static"
    if (static_dir / "ffmpeg").is_file() and (static_dir / "ffprobe").is_file():
        # exists from a previous session — refresh the symlinks
        for name in ("ffmpeg", "ffprobe"):
            target = static_dir / name
            os.chmod(target, 0o755)
            _link(bin_dir, name, target)
        return str(static_dir / "ffmpeg"), str(static_dir / "ffprobe")

    machine = platform.machine()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine)
    url = STATIC_BUILD_URLS.get(machine)
    if url is None or arch is None:
        raise RuntimeError(
            f"no static ffmpeg build known for architecture '{machine}'; "
            "install ffmpeg via your package manager")

    print(f"NOTE: ffmpeg missing — downloading static build ({arch}) ...",
          file=sys.stderr)
    tmp = Path("/tmp/ffmpeg_static_dl.tar.xz")
    urllib.request.urlretrieve(url, tmp)
    extract_root = Path("/tmp")
    with tarfile.open(tmp, "r:xz") as tf:
        try:
            tf.extractall(extract_root, filter="data")
        except TypeError:  # Python < 3.12
            tf.extractall(extract_root)
    tmp.unlink(missing_ok=True)

    static_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    src_dir = next((d for d in extract_root.glob(f"ffmpeg-*-{arch}-static")), None)
    if src_dir is None:
        raise RuntimeError("static build extracted but folder not found")
    for name in ("ffmpeg", "ffprobe"):
        shutil.copy2(src_dir / name, static_dir / name)
        os.chmod(static_dir / name, 0o755)
        _link(bin_dir, name, static_dir / name)
    shutil.rmtree(src_dir, ignore_errors=True)
    installed.append(f"ffmpeg-static ({version_of(str(static_dir / 'ffmpeg'))})")
    return str(static_dir / "ffmpeg"), str(static_dir / "ffprobe")


def ensure_ytdlp() -> str:
    if shutil.which("yt-dlp"):
        return "yt-dlp"
    if run([sys.executable, "-c", "import yt_dlp"]).returncode == 0:
        return f"{sys.executable} -m yt_dlp"
    print("NOTE: yt-dlp missing — pip installing ...", file=sys.stderr)
    r = run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"])
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp install failed: {r.stderr.strip()[-300:]}")
    installed.append("yt-dlp")
    if shutil.which("yt-dlp"):
        return "yt-dlp"
    return f"{sys.executable} -m yt_dlp"


def ensure_pillow() -> str:
    r = run([sys.executable, "-c", "import PIL; print(PIL.__version__)"])
    if r.returncode == 0:
        return r.stdout.strip()
    print("NOTE: Pillow missing — pip installing (labeled grids need it) ...",
          file=sys.stderr)
    r = run([sys.executable, "-m", "pip", "install", "-q", "Pillow"])
    if r.returncode != 0:
        raise RuntimeError(f"Pillow install failed: {r.stderr.strip()[-300:]}")
    installed.append("Pillow")
    r = run([sys.executable, "-c", "import PIL; print(PIL.__version__)"])
    return r.stdout.strip()


def main() -> int:
    home = Path.home()
    bin_dir = home / ".local" / "bin"
    try:
        ff, fp = ensure_ffmpeg(bin_dir)
        ff_ver, fp_ver = version_of(ff), version_of(fp)
        ytdlp = ensure_ytdlp()
        pillow = ensure_pillow()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1

    path_add = [str(bin_dir)] if str(bin_dir) not in os.environ.get("PATH", "") else []
    result = {
        "ok": True,
        "ffmpeg": ff_ver,
        "ffprobe": fp_ver,
        "yt_dlp": ytdlp,
        "pillow": pillow,
        "path_add": path_add,
        "installed": installed,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
