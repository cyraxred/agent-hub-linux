# Session Issues

## Critical

### 1. Event loop wrong in thread context (ProcessTracker)
**File**: `src/agent_hub/services/claude_process_tracker.py` — `_fire_callbacks()`

Watchdog file change handlers run in a background thread. `_fire_callbacks` calls `asyncio.get_event_loop()` which fails or returns the wrong loop in a non-main thread. The `except RuntimeError: pass` silently swallows the error.

**Impact**: Callbacks from `session-pids.jsonl` file changes never fire. Process state updates are delayed until the 10s periodic refresh instead of being near-instant.

**Fix**: Store the event loop reference at `__init__` time (or accept it as a constructor parameter) and use `asyncio.run_coroutine_threadsafe(cb(), self._loop)`.

---

### 2. Notification state not protected by lock (ConnectionManager)
**File**: `src/agent_hub/api/websocket/handler.py` — `_check_attention_transition()`

`_previous_status`, `_session_notification`, and `_notifications` are mutated without holding `self._lock`. Multiple file watcher callbacks can trigger `_check_attention_transition` concurrently for the same or different sessions.

**Scenario**: Two state updates arrive near-simultaneously. Both read `_previous_status[session_id]` as `None`, both create a notification, resulting in duplicates. Or one pops a notification while the other is reading it.

**Fix**: Acquire `self._lock` at the start of `_check_attention_transition`, or use a separate lock for notification state.

---

### 3. Byte offset advanced before parse completes (FileWatcher)
**File**: `src/agent_hub/services/session_file_watcher.py` — `_read_new_content()`

`watched.byte_offset += len(new_data)` executes before `parse_new_lines()`. If parsing throws an exception, the byte range is permanently skipped — those lines will never be re-read.

**Fix**: Advance byte offset only after `parse_new_lines()` succeeds.

---

## High

### 4. FD leak in ProcessRegistry.terminate()
**File**: `src/agent_hub/services/process_registry.py` — `terminate()`

The entry is popped from the dict before `os.close(fd)`. If the close fails (or is interrupted), the fd handle is lost with no recovery path. Over many terminal open/close cycles this leads to fd exhaustion.

**Fix**: Close the fd before removing from the dict. If close fails, log a warning but still remove.

---

### 5. No bounds checking on terminal resize
**File**: `src/agent_hub/api/websocket/terminal_handler.py`

Resize messages from WebSocket are passed directly to `ioctl(TIOCSWINSZ)` with no validation. A malformed message like `{"type": "resize", "rows": -1, "cols": 999999}` is accepted.

**Fix**: Clamp rows to 1–500, cols to 1–1000 (or similar reasonable bounds).

---

### 6. Notifications never cleaned up (ConnectionManager)
**File**: `src/agent_hub/api/websocket/handler.py`

Entries in `_notifications` are only removed on transition OUT of an attention state. If a session enters attention and the process dies (no further JSONL writes), or the session is abandoned, the notification persists in memory forever.

**Fix**: Add TTL-based cleanup. Periodically sweep `_notifications` and remove entries older than a threshold (e.g., 30 minutes). Also clean up when a session's process is detected as dead by the tracker.

---

### 7. Hook not registered when settings.json doesn't exist (HookInstaller)
**File**: `src/agent_hub/services/hook_installer.py`

The hook script file is always written to `~/.claude/hooks/session-hook.sh`. But if `~/.claude/settings.json` doesn't exist yet (fresh Claude install, never run), the code reads an empty dict and writes back with hooks — but it doesn't create the parent directory if missing, and the logic depends on the file already existing for the JSON merge.

**Impact**: First-time Agent Hub installations on systems where Claude hasn't been configured yet may silently fail to register hooks. Process tracking won't work until Claude is run once and Agent Hub is restarted.

**Fix**: Create `~/.claude/settings.json` with the hooks config if it doesn't exist, ensuring the directory is created first.

---

### 8. Duplicate desktop notifications
**File**: `src/agent_hub/api/websocket/handler.py`

`notify_attention_needed()` is launched via `asyncio.create_task()` (fire-and-forget). Combined with issue #2 (no lock on notification state), rapid state updates can trigger multiple `notify-send` invocations for the same attention event before the first one completes.

**Fix**: Resolves naturally if issue #2 is fixed (lock protects against duplicate creation). Additionally, the notification task could check if the notification is still active before calling `notify-send`.

---

## Medium

### 9. Hardcoded timeouts instead of config constants
**File**: `src/agent_hub/services/session_jsonl_parser.py` — `update_current_status()`

Timeout values are hardcoded (`60` for tool execution, `30` for thinking) instead of using the config constants defined in `src/agent_hub/config/defaults.py` (`TOOL_RESULT_TIMEOUT`, `THINKING_TIMEOUT`, `SESSION_ACTIVE_THRESHOLD`).

**Impact**: Changing the config constants has no effect. Developers may assume the constants are wired up when they aren't.

**Fix**: Import and use the config constants, or pass them as parameters.

---

### 10. Session dict iterated without lock (FileWatcher)
**File**: `src/agent_hub/services/session_file_watcher.py` — `_status_timer_loop()`

`self._sessions.values()` is iterated without holding `self._lock`. If `start_monitoring` or `stop_monitoring` modifies the dict concurrently, the iteration can raise `RuntimeError: dictionary changed size during iteration`.

The code does `list(self._sessions.values())` which creates a snapshot, partially mitigating this — but the snapshot itself is not atomic.

**Fix**: Acquire `self._lock` before creating the snapshot.

---

### 11. Approval state has a fixed delay equal to timeout
**File**: `src/agent_hub/services/session_jsonl_parser.py` — `update_current_status()`

A tool enters `awaiting_approval` status only after `approval_timeout_seconds` (5s) elapses with no tool_result. This means the UI shows `executing_tool` for 5 full seconds before switching to `awaiting_approval`, even though Claude's approval prompt appears nearly instantly.

This is a UX issue — the user sees "executing" when Claude is actually waiting for them.

**Possible fix**: Reduce the timeout to 1-2 seconds, or use a two-phase approach: show `pending_approval` immediately when a tool_use has no result, then confirm as `awaiting_approval` after the timeout.

---

### 12. Race in notification resolution
**File**: `src/agent_hub/api/websocket/handler.py`

When transitioning out of an attention state, `_session_notification.pop()` and `_notifications.pop()` are not atomic. If two state updates race (one entering, one leaving attention), the pops can conflict with the inserts.

**Fix**: Subsumes into fix for issue #2 (lock on notification state).

---

## Low

### 13. Two divergent status evaluation paths
**Files**: `session_jsonl_parser.py` `update_current_status()` and `session_file_watcher.py` `_status_timer_loop()`

Status is computed in two places with different logic:
- The parser computes status after each new batch of JSONL lines
- The timer re-evaluates status periodically based on elapsed time

Both use different timeout values and different conditions. This is architecturally intentional (timer is a safety net) but the divergent logic makes it easy for the two paths to disagree on the current status.

**Suggestion**: Extract shared status evaluation logic into a single function called from both paths.

---

### 14. Process classification scattered across call sites
**File**: `src/agent_hub/services/claude_process_tracker.py`

`_classify_pid()` is called during initial scan, periodic refresh, and on hub launch/terminate. Each call site has slightly different assumptions about what locks are held and whether the process is still alive. `/proc` reads can fail mid-classification if the process exits.

**Impact**: Transient misclassification (e.g., a process briefly shows as `user` before being reclassified as `hub`). Low impact since the periodic refresh self-corrects within 10s.

---

### 15. Hook script is Unix-only
**File**: `src/agent_hub/services/hook_installer.py`

The hook script is a bash script. No platform detection. Not relevant for the current Linux target, but would break if the project is extended to other platforms.

---

## Summary

| # | Severity | Component | Issue | Status |
|---|----------|-----------|-------|--------|
| 1 | CRITICAL | ProcessTracker | Event loop wrong in thread → callbacks fail silently | OPEN |
| 2 | CRITICAL | ConnectionManager | Notification state unprotected by lock | **RESOLVED** — notification state removed in SessionManager refactoring |
| 3 | CRITICAL | FileWatcher | Byte offset advanced before parse | OPEN |
| 4 | HIGH | ProcessRegistry | FD leak on failed close | OPEN |
| 5 | HIGH | TerminalHandler | No resize bounds checking | OPEN |
| 6 | HIGH | ConnectionManager | Notification entries never cleaned up | **RESOLVED** — ConnectionManager no longer owns notifications; SessionManager clears on process exit |
| 7 | HIGH | HookInstaller | Hook not registered without existing settings.json | OPEN |
| 8 | HIGH | ConnectionManager | Duplicate desktop notifications | **RESOLVED** — deduplicated via `_notified_attention_ids` set |
| 9 | MED | Parser | Hardcoded timeouts, config constants unused | OPEN |
| 10 | MED | FileWatcher | Dict iteration without lock | OPEN |
| 11 | MED | Parser | Approval delay equals full timeout | OPEN |
| 12 | MED | ConnectionManager | Race in notification resolution | **RESOLVED** — notification state removed, SessionManager uses async lock |
| 13 | LOW | Status eval | Two divergent status computation paths | OPEN |
| 14 | LOW | ProcessTracker | Classification logic scattered, transient misclassification | OPEN |
| 15 | LOW | HookInstaller | Unix-only hook script | OPEN |

See also: `SESSION_REFACTORING_TODO.md` for remaining work from the unified session state refactoring.
