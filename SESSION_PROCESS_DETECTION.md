# Session-to-Process Mapping via Claude Hook

## Problem

AgentHub needs to know which OS process corresponds to which Claude session in order to:
- Detect if a session is currently active (has a running Claude process)
- Prevent spawning a second Claude against an already-running session
- Show accurate "running" status without relying solely on JSONL file activity

## Findings

### What doesn't work
- **Open file descriptors** (`/proc/{pid}/fd`): Claude does not keep the session JSONL open between writes. Only `~/.claude/history.jsonl` is held open (read-only). Useless for detection.
- **`/proc/{pid}/cwd`**: Reliable for matching project path, but multiple Claude sessions can share the same cwd.
- **`--resume` cmdline scanning**: Works for resumed sessions only. Fresh interactive sessions have no session ID in cmdline.

### What works: `SessionStart` hook

Claude Code supports global hooks via `~/.claude/settings.json`. The `SessionStart` event fires on every session start (fresh, resume, after `/clear`, after compaction) and provides:

```json
{
  "session_id": "7a071efd-339d-4503-9dd5-660cbb1e94c7",
  "transcript_path": "/home/user/.claude/projects/-home-user-workspace-agent-hub-linux/7a071efd-339d-4503-9dd5-660cbb1e94c7.jsonl",
  "cwd": "/home/user/workspace/agent-hub-linux",
  "hook_event_name": "SessionStart",
  "source": "startup",
  "model": "claude-sonnet-4-6"
}
```

`transcript_path` gives the full path to the session JSONL — no path derivation needed.

## Solution

### 1. Hook script `~/.claude/hooks/session-start.sh`

```bash
#!/bin/bash
INPUT=$(cat)

# Walk up process tree to find the claude process
SEARCH=$$
CLAUDE_PID=""
while [ "$SEARCH" -gt 1 ]; do
  COMM=$(cat /proc/$SEARCH/comm 2>/dev/null)
  if [ "$COMM" = "claude" ]; then
    CLAUDE_PID=$SEARCH
    break
  fi
  SEARCH=$(awk '/PPid/{print $2}' /proc/$SEARCH/status 2>/dev/null)
done

echo "${INPUT%\}},\"pid\":$CLAUDE_PID,\"ts\":$(date +%s)}" >> ~/.claude/session-pids.jsonl
```

### 2. Register in `~/.claude/settings.json`

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/session-start.sh"
          }
        ]
      }
    ]
  }
}
```

### 3. Resulting log `~/.claude/session-pids.jsonl`

One entry per session start:
```json
{"session_id":"7a071efd-...","transcript_path":"/home/user/.claude/projects/.../7a071efd-....jsonl","cwd":"/home/user/workspace/agent-hub-linux","hook_event_name":"SessionStart","source":"startup","model":"claude-sonnet-4-6","pid":90167,"ts":1773261461}
```

## AgentHub Integration

- Read `~/.claude/session-pids.jsonl` on startup and watch for new entries
- For each entry, check `kill -0 {pid}` to verify the process is still alive
- Map `transcript_path` → `pid` to know if a session file has a running Claude
- Use `source` field to distinguish fresh (`startup`) from resumed (`resume`) sessions
- Survives AgentHub restarts — log is persistent on disk

## Notes

- The hook is **global** — fires for all Claude sessions on the machine, not just AgentHub-launched ones. This is the desired behavior.
- Verified: for a fresh `claude` session (no `--resume`), `/proc/{pid}/cmdline` is just `claude` with no arguments — the hook is the only reliable way to capture the PID in this case.
- `session-pids.jsonl` should be periodically compacted — dead PIDs can be pruned by checking `kill -0`.
