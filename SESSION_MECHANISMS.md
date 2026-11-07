# Session Mechanisms Overview

## 1. Session Monitoring (File Watchers)

Sessions are monitored by watching Claude's JSONL transcript files for changes.

### Components
- **`SessionFileWatcher`** — watches Claude Code session JSONL files via `watchdog`
- **`CodexSessionFileWatcher`** — equivalent for Codex sessions
- **`session_jsonl_parser`** — parses JSONL lines into structured state

### Flow
1. `start_monitoring(session_id)` registers a session and starts a watchdog observer on its JSONL file
2. On file change → read new bytes from last `byte_offset` → split into lines → `parse_new_lines()`
3. Parser maintains a `ParseResult` accumulator per session:
   - `recent_activities` — last N parsed events
   - `pending_tool_uses` — tool_use entries not yet matched by a tool_result
   - `current_status` — derived status object
   - `cost`, `duration`, `message_count`, etc.
4. After parsing, `update_current_status()` evaluates the accumulated state to produce a status kind (`thinking`, `executing_tool`, `awaiting_approval`, `idle`, etc.)
5. `_update_state_from_parse()` copies parse results into the mutable `SessionMonitorState`
6. State is broadcast to WebSocket subscribers

### Status Timer
A periodic loop (`_status_timer_loop`, 1.5s interval) independently re-evaluates status:
- Detects stale watchers (file grew but no change event fired)
- Transitions active statuses to `idle` after inactivity thresholds
- Acts as a safety net for missed file system events

### Parse Cache
Non-monitored sessions can still be queried via `get_session_state()`, which does a one-shot parse of the full JSONL file. Results are cached to avoid re-parsing.

---

## 2. Terminal Connections

### Components
- **`terminal.py` (routes)** — REST endpoints for launch/terminate/list
- **`terminal_handler.py`** — WebSocket bridge between xterm.js and PTY
- **`terminal_launcher.py`** — PTY spawning via `forkpty()`
- **`ProcessRegistry`** — in-memory registry of active terminal processes (pid + master fd)

### Flow
1. `POST /api/terminal/launch` receives a session_id and/or project_path
2. `spawn_terminal()` calls `os.forkpty()`, execs `claude --resume <session_id>` in the child
3. Parent gets master fd + child pid, stored in `ProcessRegistry` under key `term-<session_id>`
4. `notify_hub_launch(pid, session_id)` tells the process tracker this is a hub-owned process
5. Frontend opens WebSocket to `/ws/terminal/<key>`
6. `terminal_websocket_endpoint` enters a read loop:
   - PTY fd → read bytes → send as WebSocket text to xterm.js
   - WebSocket text from xterm.js → write bytes to PTY fd
   - JSON messages with `type: "resize"` → `ioctl(TIOCSWINSZ)` on the fd
7. On disconnect or `DELETE /api/terminal/<key>`, the PTY is closed and process killed

### Terminal Keys
- Session-based: `term-<session_id>`
- Path-based: `term-<hash(project_path)>` (when no session_id provided)

---

## 3. Detecting "User Input Required"

### Mechanism
The system detects when Claude is waiting for user approval or asking a question by tracking tool_use / tool_result pairs with a timeout.

### Flow
1. Parser encounters a `tool_use` entry → adds to `pending_tool_uses[tool_id]` with timestamp and tool name
2. Parser encounters a matching `tool_result` → removes from `pending_tool_uses`
3. `update_current_status()` checks remaining pending tools:
   - If elapsed time since tool_use > `approval_timeout_seconds` (default 5s):
     - Tool name matches `askuserquestion` variants → status = `awaiting_question`
     - Otherwise → status = `awaiting_approval`
   - If elapsed < timeout but tool is pending → status = `executing_tool`

### Tool Name Detection
```python
is_question = pending.tool_name.lower() in ("askuserquestion", "ask_user_question")
```

### Timeout Rationale
The timeout exists to distinguish tools that are still executing from tools that are blocked waiting for user input. Claude's tool approval prompt appears nearly instantly, so 5s is generous.

---

## 4. Notifications

### Components
- **`ConnectionManager._check_attention_transition()`** — detects state transitions into/out of attention states
- **`notify_attention_needed()`** — sends desktop notifications via `notify-send`
- **WebSocket messages** — `ServerMessageNotification` / `ServerMessageNotificationResolved`

### Flow
1. Every state update triggers `_check_attention_transition(session_id, state)`
2. Compares current status kind against `_previous_status[session_id]`
3. If transitioning INTO an attention state (`awaiting_approval`, `awaiting_question`):
   - Creates an `AttentionNotification` in `_notifications` dict
   - Broadcasts `ServerMessageNotification` to all WebSocket clients
   - Fires `notify-send` desktop notification (async, fire-and-forget)
   - Records mapping in `_session_notification[session_id] = notif_id`
4. If transitioning OUT of an attention state:
   - Removes notification from `_notifications` and `_session_notification`
   - Broadcasts `ServerMessageNotificationResolved`

### Attention Kinds
```python
attention_kinds = {"awaiting_approval", "awaiting_question"}
```

---

## 5. Process Tracking

### Components
- **`hook_installer.py`** — installs a bash hook into `~/.claude/hooks/` that fires on SessionStart/SessionEnd
- **`claude_process_tracker.py`** — correlates hook data with live `/proc` scan
- **`session-pids.jsonl`** — append-only log written by the hook script

### Hook Script
Installed at `~/.claude/hooks/session-hook.sh`, registered in `~/.claude/settings.json` for `SessionStart` and `SessionEnd` events. On each event:
- Reads JSON from stdin (Claude passes event data)
- Appends `{session_id, transcript_path, cwd, pid, ts, hook_event_name}` to `~/.claude/session-pids.jsonl`

### Tracker Flow
1. On startup, parses `session-pids.jsonl` to build `pid → session` and `session → pid` maps
2. Scans `/proc` for processes with `comm == "claude"`
3. Classifies each PID into one of four categories:
   - **`hub`** — spawned by Agent Hub's ProcessRegistry
   - **`tmux`** — has a tmux ancestor in the process tree
   - **`user`** — running in a terminal (has controlling TTY)
   - **`third_party`** — background, SSH, or other origin
4. Watchdog observer on `session-pids.jsonl` detects new hook entries
5. Periodic refresh (10s) re-scans `/proc` to detect dead processes and reclassify

### Public API
- `get_process_for_session(session_id)` → `ClaudeProcessInfo | None`
- `get_all_process_states()` → `dict[str, SessionProcessState]`
- `get_unmatched_processes()` → `list[UnmatchedClaudeProcess]`
- `is_session_resumable(session_id)` → `True` if no live process owns it
- `notify_hub_launch(pid, session_id)` / `notify_hub_terminate(pid)` — register/unregister hub-spawned processes

### Process State Model
```
ClaudeProcessInfo: pid, session_id, category, monitored, terminal_connected, cwd, model, started_at
SessionProcessState: session_id, process (optional), resumable, possibly_owned_by_unmatched
UnmatchedClaudeProcess: pid, cwd (Claude process with no session mapping from hooks)
```

---

## 6. WebSocket Layer

### Components
- **`ConnectionManager`** — manages WebSocket connections, subscriptions, and broadcasts
- **`/ws/updates`** — main WebSocket endpoint for session/process state updates
- **`/ws/terminal/<key>`** — per-terminal WebSocket for PTY I/O

### Message Types (Server → Client)
- `session_state_update` — session monitoring state changed
- `process_state_update` — process tracking state changed
- `notification` / `notification_resolved` — attention state transitions
- `terminal_output` — raw bytes from PTY

### Message Types (Client → Server)
- `subscribe` / `unsubscribe` — per-session subscription management
- Raw text / `{"type": "resize", ...}` — terminal input and resize on terminal WebSocket

### Subscriptions
Clients subscribe to specific session IDs. State updates are only sent to subscribers of the relevant session. Notifications are broadcast to all connected clients.
