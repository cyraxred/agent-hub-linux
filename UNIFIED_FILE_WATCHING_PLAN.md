# Unified File Watching and Transcript Management

## Context

Stuck notifications for active sessions. Root cause: attention events (from `sessions.jsonl` hooks) are only resolved when the `SessionFileWatcher` detects `tool_result` in a transcript file — but the watcher only monitors transcripts for WS-subscribed sessions. Active sessions without a WS subscriber have no transcript monitoring, so attention stays stuck forever.

The fix requires unifying file watching and transcript management so that all active sessions have their transcripts monitored, not just WS-subscribed ones.

## New Components

### 1. `FileWatcher` (singleton)
**File:** `src/agent_hub/services/file_watcher.py` (new)

Replaces the 4 separate watchdog `Observer` usages (SessionFileWatcher, CodexSessionFileWatcher, ClaudeProcessTracker, GlobalStatsService).

- Single `Observer` instance, watches directories via inotify
- Handles: `on_created`, `on_modified`, `on_deleted` (current code only handles `on_modified`)
- **Directory subscriptions**: `watch_directory(path, callback)` / `unwatch_directory(path)`
  - Callback receives `(event_type: str, file_path: str)` where event_type is `"created"` | `"modified"` | `"deleted"`
  - On subscribe, enumerates existing files and calls callback with `"created"` for each
- **File subscriptions**: `watch_file(path, callback)` / `unwatch_file(path)`
  - Callback receives `(event_type: str, file_path: str)`
  - For single-file watches (sessions.jsonl, stats-cache.json)
- Internally groups by parent directory — one `schedule()` per unique directory
- Refcounts per directory — unschedule when last subscriber removed
- Thread-safe async bridge via `asyncio.run_coroutine_threadsafe`

### 2. `TranscriptRegistry`
**File:** `src/agent_hub/services/transcript_registry.py` (new)

Central owner of all transcript state. Replaces the `_sessions` dict in `SessionFileWatcher` and the file scanning in `CLISessionMonitorService._find_sessions_for_path()`.

- **State:** `dict[str, SessionTranscript | int]` keyed by file_path
  - `int` = last known file size (unclassified or confirmed non-session)
  - `SessionTranscript` = confirmed real conversation
- **Listens to FileWatcher** directory events for `~/.claude/projects/*/` dirs:
  - `created` → add `int` entry (file size), run classification
  - `modified` on `int` entry → re-check classification (file may have grown into a real session)
  - `modified` on `SessionTranscript` entry → call `transcript.notify_file_modified()`
  - `deleted` → remove entry, fire `on_transcript_removed` callback
- **Classification**: reuses `_is_conversation_file()` logic from `path_utils.py` (first 16KB check for resumable types)
- **Promotion**: `int` → `SessionTranscript` when classification succeeds; fires `on_transcript_added` callback
- **Callbacks:**
  - `on_transcript_added(session_id)` — SessionManager creates Session (registry has the transcript with file_path/project_path)
  - `on_transcript_removed(session_id)` — SessionManager removes Session
- **Query:** `get_transcript(session_id) -> SessionTranscript | None`
- Internal dict keyed by file_path (from FileWatcher events), secondary index `dict[session_id, file_path]` for lookups
- **Project directory management:** `add_project_directory(path)` / `remove_project_directory(path)` — subscribes/unsubscribes from FileWatcher

### 3. `SessionTranscript`
**File:** `src/agent_hub/services/session_transcript.py` (new)

Extracted from `_WatchedSession` + `_read_new_content()` in `SessionFileWatcher`. One per confirmed conversation file.

- **Owns:** `file_path`, `session_id`, `project_path`, `byte_offset`, `line_count`, `ParseResult`, `SessionMonitorState`
- **Constructor takes `parse_fn`** — either Claude's or Codex's `parse_new_lines()`. Provider-agnostic otherwise.
- **`notify_file_modified()`**: stats file, reads delta from `byte_offset`, parses via `parse_fn`, updates state, detects resolved tool_use_ids, fires callbacks. Handles truncation (size < offset → reset and re-parse).
- **Callbacks:**
  - `on_state_update(session_id, state)` — same as today
  - `on_history_append(session_id, entries, total_lines)` — same as today
  - `on_tool_result(session_id, tool_use_id)` — for attention resolution (Claude only; Codex transcripts won't fire this since Codex parser doesn't track pending tool_uses)
- **Monitoring flag:** `is_monitored: bool` — when True, TranscriptRegistry subscribes the file to FileWatcher per-file for instant notification. When False, only directory-level events reach it.
- **`set_monitored(flag)`** — TranscriptRegistry calls this based on Session monitoring state

**Provider handling:** One TranscriptRegistry per provider (claude/codex), each configured with its `parse_fn` and base directories. Same pattern as today's `claude_watcher` / `codex_watcher`. FileWatcher singleton is shared.

### 4. Session monitoring logic (modified `Session` / `SessionManager`)
**File:** `src/agent_hub/services/session_manager.py` (modified)

Add to `Session`:
- `manual_monitoring: bool = False` — set by WS subscribe, cleared by WS unsubscribe
- `auto_monitoring: bool = False` — set when: terminal-connected OR (has pending attention AND process is alive)

Add to `SessionManager`:
- When `manual_monitoring or auto_monitoring` becomes True → tell TranscriptRegistry to set transcript as monitored (per-file FileWatcher subscription)
- When both become False → tell TranscriptRegistry to unset monitored
- On attention event → check if session should become auto_monitored
- On process death / attention resolved → check if session should stop auto_monitoring

## Migration Plan (ordered phases)

### Phase 1: FileWatcher singleton
- Create `file_watcher.py`
- Unit-testable in isolation

### Phase 2: SessionTranscript
- Extract from `SessionFileWatcher._WatchedSession` + `_read_new_content()`
- Reuse `parse_new_lines()` from `session_jsonl_parser.py` as-is
- Reuse `_is_conversation_file()` from `path_utils.py` as-is
- Reuse write-through `SessionParseCache` integration

### Phase 3: TranscriptRegistry
- Create `transcript_registry.py`
- Wire to FileWatcher for `~/.claude/projects/*/` directories
- Fire `on_transcript_added` / `on_transcript_removed` callbacks

### Phase 4: Wire into SessionManager
- SessionManager listens to TranscriptRegistry callbacks for Session creation/removal
- Add `manual_monitoring` / `auto_monitoring` flags to Session
- SessionManager drives monitoring state changes on TranscriptRegistry

### Phase 5: Wire attention resolution
- All SessionTranscripts fire `on_tool_result` when they detect resolved tool_use_ids
- Process tracker's `resolve_attention` is called for ALL sessions, not just WS-subscribed ones
- Test: create attention via hook → respond → verify notification clears without WS subscription

### Phase 6: Migrate existing consumers
- `SessionFileWatcher`: replace internals with TranscriptRegistry + FileWatcher. Keep the public API (`start_monitoring`/`stop_monitoring`) as thin wrappers that set `manual_monitoring` on Session. Eventually remove the class entirely.
- `CodexSessionFileWatcher`: same treatment
- `ClaudeProcessTracker`: replace internal `_SessionsFileHandler` + `Observer` with `FileWatcher.watch_file()` for sessions.jsonl
- `GlobalStatsService`: replace internal `_StatsFileHandler` + `Observer` with `FileWatcher.watch_file()` for stats-cache.json
- `CLISessionMonitorService._find_sessions_for_path()`: replace file scanning with TranscriptRegistry query. Keep repository/worktree management, history.jsonl parsing.

### Phase 7: Cleanup
- Remove `_FileChangeHandler`, `_SessionsFileHandler`, `_StatsFileHandler` classes
- Remove per-service `Observer` instances
- Remove `_WatchedSession` from `SessionFileWatcher` (replaced by `SessionTranscript`)

## Files to Modify
- `src/agent_hub/services/file_watcher.py` — **new**
- `src/agent_hub/services/session_transcript.py` — **new**
- `src/agent_hub/services/transcript_registry.py` — **new**
- `src/agent_hub/services/session_manager.py` — add monitoring flags, wire registry callbacks
- `src/agent_hub/services/session_file_watcher.py` — gut internals, thin wrapper → eventually remove
- `src/agent_hub/services/codex_file_watcher.py` — same
- `src/agent_hub/services/claude_process_tracker.py` — use FileWatcher for sessions.jsonl
- `src/agent_hub/services/global_stats_service.py` — use FileWatcher for stats-cache.json
- `src/agent_hub/services/cli_session_monitor.py` — replace file scanning with registry query
- `src/agent_hub/provider.py` — initialization wiring
- `src/agent_hub/api/websocket/handler.py` — update callback registration

## Reuse (not rewrite)
- `parse_new_lines()` from `session_jsonl_parser.py` — transcript parsing
- `_is_conversation_file()` / `_RESUMABLE_TYPES` from `path_utils.py` — classification
- `SessionParseCache` — write-through cache
- `SessionMonitorState` model — state representation
- `_update_state_from_parse()` logic — moves into SessionTranscript

## Verification
1. Start Agent Hub, open two Claude sessions in separate terminals
2. Both should show as "running" in the UI without opening their detail views
3. Trigger a permission request in one session — notification should appear
4. Approve/deny the permission — notification should clear (even without the session detail view open)
5. Open session detail view — should show live token counts and activity (manual monitoring)
6. Close session detail view — auto_monitoring should keep transcript watched if process is alive with pending attention
7. Kill a claude process — session should transition to idle, attention should clear
8. Delete a session file — session should disappear from the UI
