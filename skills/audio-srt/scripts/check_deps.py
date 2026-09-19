#!/usr/bin/env python3
"""
check_deps.py — auto-check and (re)install every dependency of this skill.

MUST be run BEFORE any other step (session starts wipe tools). It is
idempotent and fast when everything is present.

Checks / repairs:
  1. ffmpeg + ffprobe : if missing, downloads a static build into
     ~/.local/ffmpeg-static and symlinks it into ~/.local/bin
  2. yt-dlp           : pip install if missing (YouTube / remote links)
  3. assemblyai       : pip install if missing (AssemblyAI Python SDK)

Prints ONE JSON object on stdout:
  {"ok": true, "ffmpeg": "7.0.2", "ffprobe": "7.0.2", "yt_dlp": "...",
   "assemblyai": "1.5.5", "api_key_set": true,
   "path_add": ["/home/user/.local/bin"], "installed": []}

`api_key_set` tells you whether ASSEMBLYAI_API_KEY is resolvable (env var or
~/.assemblyai_env). If false, ask the user for a key BEFORE transcribing.
`path_add` directories should be prepended to PATH for later commands.
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
    src_dir = next((d for d in extract_root.glob(f"ffmpeg-*-{arch}-static")),
                   None)
    if src_dir is None:
        raise RuntimeError("static build extracted but folder not found")
    for name in ("ffmpeg", "ffprobe"):
        shutil.copy2(src_dir / name, static_dir / name)
        os.chmod(static_dir / name, 0o755)
        _link(bin_dir, name, static_dir / name)
    shutil.rmtree(src_dir, ignore_errors=True)
    installed.append(f"ffmpeg-static ({version_of(str(static_dir / 'ffmpeg'))})")
    return str(static_dir / "ffmpeg"), str(static_dir / "ffprobe")


def _pip(pkg: str) -> None:
    print(f"NOTE: {pkg} missing — pip installing ...", file=sys.stderr)
    r = run([sys.executable, "-m", "pip", "install", "-q", pkg])
    if r.returncode != 0:
        raise RuntimeError(f"{pkg} install failed: {r.stderr.strip()[-300:]}")
    installed.append(pkg)


def ensure_ytdlp() -> str:
    if shutil.which("yt-dlp"):
        return "yt-dlp"
    if run([sys.executable, "-c", "import yt_dlp"]).returncode == 0:
        return f"{sys.executable} -m yt_dlp"
    _pip("yt-dlp")
    if shutil.which("yt-dlp"):
        return "yt-dlp"
    return f"{sys.executable} -m yt_dlp"


def ensure_assemblyai() -> str:
    r = run([sys.executable, "-c", "import assemblyai; "
           "import importlib.metadata as md; "
           "print(md.version('assemblyai'))"])
    if r.returncode == 0:
        return r.stdout.strip()
    _pip("assemblyai")
    r = run([sys.executable, "-c", "import importlib.metadata as md; "
           "print(md.version('assemblyai'))"])
    if r.returncode != 0:
        raise RuntimeError("assemblyai installed but not importable")
    return r.stdout.strip()


def api_key_set() -> bool:
    if os.environ.get("ASSEMBLYAI_API_KEY"):
        return True
    env_file = Path.home() / ".assemblyai_env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ASSEMBLYAI_API_KEY="):
                return bool(line.split("=", 1)[1].strip())
    return False


def main() -> int:
    home = Path.home()
    bin_dir = home / ".local" / "bin"
    try:
        ff, fp = ensure_ffmpeg(bin_dir)
        ff_ver, fp_ver = version_of(ff), version_of(fp)
        ytdlp = ensure_ytdlp()
        aai_ver = ensure_assemblyai()
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
        "assemblyai": aai_ver,
        "api_key_set": api_key_set(),
        "path_add": path_add,
        "installed": installed,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
