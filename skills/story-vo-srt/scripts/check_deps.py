#!/usr/bin/env python3
"""
check_deps.py — auto-check every dependency of this skill.

MUST be run BEFORE any other step (session starts wipe tools/state).
Idempotent and fast when everything is present.

This skill needs NO system tools (no ffmpeg — it works on SRT text only)
and NO pip packages (stdlib urllib calls the LLM API). It checks:
  1. Python version (3.8+)
  2. LLM API config — base url + key + model resolvable from
     env vars or ~/.llm_env (LLM_API_BASE / LLM_API_KEY / LLM_MODEL)
  3. optional: --ping does a tiny real API call to verify key/model
     (consumes a few free-tier tokens)

Prints ONE JSON object:
  {"ok": true, "python": "3.13", "llm_base": "...", "llm_model": "...",
   "llm_key_set": true, "ping": "ok"|"skipped"|"failed: ...",
   "config_source": "env"|"~/.llm_env"}
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


def load_config(cli_overrides: dict = None) -> dict:
    cfg = {"LLM_API_BASE": "", "LLM_API_KEY": "", "LLM_MODEL": ""}
    source = None
    env_file = Path.home() / ".llm_env"
    if env_file.is_file():
        source = "~/.llm_env"
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip("'\"")
    for k, v in os.environ.items():
        if k in cfg and v.strip():
            cfg[k] = v.strip()
            source = "env"
    for k, v in (cli_overrides or {}).items():
        if v:
            cfg[k] = v
            source = "cli"
    cfg.setdefault("LLM_API_BASE", "https://openrouter.ai/api/v1")
    return cfg, (source or "default-base")


def ping(cfg: dict) -> str:
    try:
        req = urllib.request.Request(
            cfg["LLM_API_BASE"].rstrip("/") + "/chat/completions",
            data=json.dumps({
                "model": cfg["LLM_MODEL"],
                "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
                "max_tokens": 8,
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {cfg['LLM_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8"))
        if "choices" in d:
            return "ok"
        return f"failed: unexpected response {str(d)[:120]}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        return f"failed: HTTP {e.code} {body}"
    except Exception as e:
        return f"failed: {type(e).__name__}: {str(e)[:150]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ping", action="store_true",
                    help="do a tiny real API call to verify key+model")
    ap.add_argument("--base", default=None)
    ap.add_argument("--key", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    if sys.version_info < (3, 8):
        print(json.dumps({"ok": False, "error": "Python 3.8+ required"}))
        return 1

    cfg, source = load_config({
        "LLM_API_BASE": args.base, "LLM_API_KEY": args.key,
        "LLM_MODEL": args.model,
    })
    ping_result = "skipped"
    if args.ping:
        ping_result = ping(cfg)

    key_set = bool(cfg["LLM_API_KEY"]) and bool(cfg["LLM_MODEL"])
    result = {
        "ok": key_set and (not args.ping or ping_result == "ok"),
        "python": ".".join(map(str, sys.version_info[:3])),
        "llm_base": cfg["LLM_API_BASE"],
        "llm_model": cfg["LLM_MODEL"],
        "llm_key_set": key_set,
        "config_source": source,
        "ping": ping_result,
    }
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
