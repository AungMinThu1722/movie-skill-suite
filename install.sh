#!/usr/bin/env bash
# install.sh — install the Movie Skill Suite into an agent skills directory.
#
# Usage:
#   ./install.sh                    # installs to ~/.claude/skills
#   ./install.sh --to /path/dir     # installs to a custom skills dir
#
# Each skill folder contains its own SKILL.md, so any SKILL.md-aware agent
# discovers them automatically after installation.
set -euo pipefail

TO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --to) TO="${2:?--to needs a directory}"; shift 2 ;;
    -h|--help) grep '^# ' "$0" | sed 's/^# //'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
TO="${TO:-$HOME/.claude/skills}"

SRC="$(cd "$(dirname "$0")/skills" && pwd)"
mkdir -p "$TO"

installed=0
for d in "$SRC"/*/; do
  name="$(basename "$d")"
  if [[ ! -f "$d/SKILL.md" ]]; then
    echo "skip $name (no SKILL.md)"; continue
  fi
  rm -rf "$TO/$name"
  cp -r "$d" "$TO/$name"
  find "$TO/$name" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
  echo "installed: $name -> $TO/$name"
  installed=$((installed+1))
done

echo ""
echo "$installed skill(s) installed into $TO"
echo "Next (one-time, if not already set):"
echo "  - AssemblyAI key  -> ~/.assemblyai_env   (ASSEMBLYAI_API_KEY=***"
echo "  - LLM API config  -> ~/.llm_env          (LLM_API_BASE / LLM_API_KEY / LLM_MODEL)"
echo "  - ffmpeg          -> auto-installed by the skills on first run"
