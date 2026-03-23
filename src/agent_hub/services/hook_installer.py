"""Auto-install Claude hooks for session and attention tracking.

Writes hook scripts that append events to
``~/.claude/agent-hub/sessions.jsonl``, and registers them in
``~/.claude/settings.json`` under the appropriate hook events.

Tracked events:
- ``SessionStart`` / ``SessionEnd`` — session lifecycle with PID
- ``PermissionRequest`` — tool permission prompts (attention needed)
- ``PreToolUse[AskUserQuestion]`` — interactive questions (attention needed)
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_HOOK_SCRIPT_NAME = "agent-hub-session.sh"
ATTENTION_HOOK_SCRIPT_NAME = "agent-hub-attention.sh"

# Session lifecycle hook — fires on SessionStart and SessionEnd.
# Walks the process tree to find the claude PID, then appends to sessions.jsonl.
SESSION_HOOK_SCRIPT = r"""#!/usr/bin/env bash
# Auto-installed by Agent Hub — tracks claude session lifecycle.
set -euo pipefail

OUTDIR="${HOME}/.claude/agent-hub"
mkdir -p "$OUTDIR"
OUTFILE="${OUTDIR}/sessions.jsonl"

INPUT="$(cat)"

# Walk up process tree to find the claude process PID.
SEARCH=$$
CLAUDE_PID=""
while [ "$SEARCH" -gt 1 ]; do
  COMM=$(cat /proc/$SEARCH/comm 2>/dev/null || true)
  if [ "$COMM" = "claude" ]; then
    CLAUDE_PID=$SEARCH
    break
  fi
  SEARCH=$(awk '/PPid/{print $2}' /proc/$SEARCH/status 2>/dev/null || echo 1)
done

echo "$INPUT" \
  | jq -c '. + {"pid": '"${CLAUDE_PID:-0}"', "ts": now}' \
  >> "$OUTFILE" 2>/dev/null || true
"""

# Attention hook — fires on PermissionRequest and PreToolUse (AskUserQuestion).
# Appends an attention event with session_id, tool info, and PID.
ATTENTION_HOOK_SCRIPT = r"""#!/usr/bin/env bash
# Auto-installed by Agent Hub — tracks attention-requiring events.
set -euo pipefail

OUTDIR="${HOME}/.claude/agent-hub"
mkdir -p "$OUTDIR"
OUTFILE="${OUTDIR}/sessions.jsonl"

INPUT="$(cat)"

# Walk up process tree to find the claude process PID.
SEARCH=$$
CLAUDE_PID=""
while [ "$SEARCH" -gt 1 ]; do
  COMM=$(cat /proc/$SEARCH/comm 2>/dev/null || true)
  if [ "$COMM" = "claude" ]; then
    CLAUDE_PID=$SEARCH
    break
  fi
  SEARCH=$(awk '/PPid/{print $2}' /proc/$SEARCH/status 2>/dev/null || echo 1)
done

echo "$INPUT" \
  | jq -c '. + {"event": "attention", "pid": '"${CLAUDE_PID:-0}"', "ts": now}' \
  >> "$OUTFILE" 2>/dev/null || true
"""

# Old hook artifacts to clean up.
_LEGACY_SCRIPT_NAME = "session-hook.sh"
_LEGACY_JSONL = "session-pids.jsonl"


def ensure_hooks_installed(claude_data_path: str = "~/.claude") -> None:
    """Ensure all Agent Hub hook scripts and settings.json entries exist.

    Idempotent: re-running is safe and will not duplicate entries.
    """
    claude_dir = Path(claude_data_path).expanduser()
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Ensure agent-hub data directory exists
    agent_hub_dir = claude_dir / "agent-hub"
    agent_hub_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write hook scripts
    for name, content in (
        (SESSION_HOOK_SCRIPT_NAME, SESSION_HOOK_SCRIPT),
        (ATTENTION_HOOK_SCRIPT_NAME, ATTENTION_HOOK_SCRIPT),
    ):
        script_path = hooks_dir / name
        script_path.write_text(content)
        script_path.chmod(
            script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        logger.debug("Hook script written to %s", script_path)

    # 2. Merge into settings.json
    settings_path = claude_dir / "settings.json"
    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not parse %s — will overwrite hooks key", settings_path)

    hooks = settings.setdefault("hooks", {})
    session_command = f"bash {hooks_dir / SESSION_HOOK_SCRIPT_NAME}"
    attention_command = f"bash {hooks_dir / ATTENTION_HOOK_SCRIPT_NAME}"

    # Hook registrations: (event_name, command, matcher_or_empty)
    # Claude Code hook format requires: {"matcher": "...", "hooks": [{"type": "command", "command": "..."}]}
    registrations: list[tuple[str, str, str]] = [
        ("SessionStart", session_command, ""),
        ("SessionEnd", session_command, ""),
        ("PermissionRequest", attention_command, ""),
        ("PreToolUse", attention_command, "AskUserQuestion"),
    ]

    changed = False
    for event, command, matcher in registrations:
        entries: list = hooks.setdefault(event, [])
        # Check if our command is already registered (in the nested hooks array)
        already = any(
            isinstance(e, dict)
            and e.get("matcher", "") == matcher
            and any(
                isinstance(h, dict) and h.get("command") == command
                for h in (e.get("hooks") or [])
            )
            for e in entries
        )
        if not already:
            entry: dict = {
                "matcher": matcher,
                "hooks": [{"type": "command", "command": command}],
            }
            entries.append(entry)
            changed = True
            logger.info("Registered hook for %s in settings.json", event)

    # 3. Clean up legacy hook entries (both flat format and nested format)
    legacy_command = f"bash {hooks_dir / _LEGACY_SCRIPT_NAME}"
    for event in list(hooks.keys()):
        entries = hooks.get(event, [])
        before = len(entries)
        entries[:] = [
            e for e in entries
            if not (
                isinstance(e, dict) and (
                    # Flat format (our old broken entries)
                    e.get("command") == legacy_command
                    # Also clean up our broken flat-format entries from this installer
                    or (
                        "hooks" not in e
                        and e.get("command", "").endswith(("agent-hub-session.sh", "agent-hub-attention.sh"))
                    )
                    # Nested format
                    or any(
                        isinstance(h, dict) and h.get("command") == legacy_command
                        for h in (e.get("hooks") or [])
                    )
                )
            )
        ]
        if len(entries) < before:
            changed = True
            logger.info("Removed legacy hook entries for %s", event)

    if changed:
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
        logger.info("Updated %s with Agent Hub hooks", settings_path)
    else:
        logger.debug("Hooks already registered in %s", settings_path)

    # 4. Remove legacy hook script
    legacy_script = hooks_dir / _LEGACY_SCRIPT_NAME
    if legacy_script.is_file():
        try:
            legacy_script.unlink()
            logger.info("Removed legacy hook script %s", legacy_script)
        except OSError:
            pass
