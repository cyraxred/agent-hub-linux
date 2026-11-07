# Unified Session State — Remaining Work

Status of the SessionManager refactoring as of 2026-03-23.

## Completed

- **SessionManager** created (`services/session_manager.py`) with `Session` dataclass, computed flags (`is_running`, `is_connectable`, `needs_attention`, `effective_status`), debounced broadcast
- **Unified WS message** `session_update` replaces old `process_state_update`, `notification`, `notification_resolved`, `notification_list` messages
- **Old ConnectionManager notification state** removed (no more `_notifications`, `_session_notification`, `handle_attention*`, duplicate desktop notification logic)
- **Frontend notification store** deleted, sidebar attention section driven by `sessionUpdates`
- **ProcessRegistry** uses session ID directly as key (no more `term-{session_id}` derived keys)
- **WS message cleaned up**: dropped `is_running`, `is_resumable`, `terminal_key` from `ServerMessageSessionUpdate`
- **`is_connectable` semantics fixed**: True when no process (can resume) OR hub/tmux process (can attach). False only for user/third_party.
- **Desktop notifications deduplicated** via `_notified_attention_ids` set

---

## 1. Attention state owned by two places

**Severity**: HIGH

**Problem**: Both ProcessTracker and SessionManager maintain independent `pending_attention` collections for the same data. The tracker is the real owner (it parses `sessions.jsonl`), but SessionManager copies entries via `on_attention` / `on_attention_resolved` callbacks. This creates desync:

- `_parse_sessions_file_full` restores attention entries but explicitly skips callbacks, so SessionManager never learns about them on startup.
- If a callback fires before wiring or fails silently, SessionManager keeps stale entries.
- Two `_AttentionEntry` dataclasses with the same fields exist in both files.

**Symptom**: A session shows "Needs Attention" permanently even though the tool call was resolved long ago.

**Fix**: Attention state should live only in ProcessTracker. SessionManager should not store it at all — instead, query the tracker on demand.

1. Remove from `Session`: `pending_attention` field, `_AttentionEntry` class.
2. Remove from `SessionManager`: `handle_attention()`, `handle_attention_resolved()`.
3. `Session.needs_attention` and `effective_status` call `self._tracker.get_pending_attention_for_session(session_id)` instead of reading a local list.
4. The tracker's attention callbacks still wire to SessionManager, but only to call `_schedule_notify(session_id)` — no data copy.
5. Remove the duplicated `_sm_tool_result` callback in `handler.py` (lines 325-329) and the `on_attention` / `on_attention_resolved` wiring (lines 317-318). The existing `_on_tool_result` callback (line 302-306) that calls `tracker.resolve_attention()` is sufficient — the tracker fires its own resolved callbacks which trigger the broadcast.

**Files**: `session_manager.py`, `handler.py`

---

## 2. Retire `CLISession` — REST API should return `Session`-derived data

**Severity**: HIGH

**Problem**: `CLISession` (in `models/session.py`) is a legacy Pydantic model that predates `SessionManager.Session`. Now that `Session` is the unified state object, `CLISession` creates several problems:

- **Conflicting semantics**: `CLISession.is_active` means "JSONL file modified within 60 seconds" (mtime-based, set at discovery time). `Session.is_running` means "has an OS process" (real-time). The frontend receives both under similar names.
- **Dead fields**: `message_count` (always 0), `last_message` (set but never read).
- **Redundant `needs_attention`**: `CLISession.needs_attention` is a `str | None` set by monitors via a stale heuristic. The authoritative attention state is in ProcessTracker, surfaced through `Session.needs_attention` (boolean) and `effective_status`.
- **Grouping models depend on `is_active`**: `WorktreeBranch.active_session_count`, `CLISessionGroup.active_session_count` use the mtime-based flag.

The REST session list/detail endpoints return `CLISession` objects, while the WS `session_update` returns `Session`-derived fields. Two models, two sets of semantics, same data.

**Fix**:

1. Define a new Pydantic response model (e.g. `SessionResponse`) derived from `SessionManager.Session` fields. Include `is_running`, `is_connectable`, `needs_attention`, `effective_status`, plus the discovery fields (`project_path`, `slug`, `first_message`, `branch_name`, etc.). Drop `is_active`, `message_count`, `last_message`.
2. REST list/detail endpoints return `SessionResponse` populated from `SessionManager.get_session()` / `get_all_sessions()`.
3. Monitors keep discovering sessions but their output becomes an internal data structure (or a simpler dataclass), not the API response model. `sync_discovered_sessions` continues to merge discovery data into `Session`.
4. Update grouping models (`WorktreeBranch`, `SelectedRepository`, `CLISessionGroup`) to use `SessionResponse` and replace `active_session_count` with `running_session_count` (process-based).
5. Update frontend `CLISession` TypeScript interface to match new response model. Remove `is_active`, add `is_running`, `is_connectable`, `effective_status`.
6. Remove the session detail endpoint's fallback paths (currently: SessionManager → process tracker → old monitor). SessionManager is the single source.
7. **Single `last_activity_at`**: `Session.last_activity_at` must be the sole source of truth. Currently three copies exist: `CLISession.last_activity_at` (mtime at discovery), `Session.last_activity_at` (copied from CLISession, never updated after), and `SessionMonitorState.last_activity_at` (real-time but only for monitored sessions). The frontend reads it from the REST CLISession object and ignores the WS value entirely. Fix: update `Session.last_activity_at` on the backend from every source — discovery sync, monitor state updates (`handle_monitor_state_update`), process events (`handle_process_update`), and attention events. The frontend reads it only from `SessionResponse` (REST) or `session_update` (WS), never computes it locally. Delete `_ACTIVE_THRESHOLD_SECONDS` and the mtime check from monitors — it only existed to feed `is_active`.

**Files**: `models/session.py`, `api/routes/sessions.py`, `services/session_manager.py`, `services/cli_session_monitor.py`, `services/codex_session_monitor.py`, `frontend/src/types/generated.ts`, `frontend/src/store/sessions.ts`, frontend components

---

## 3. Old `session_state_update` WS path still active in parallel

**Severity**: MEDIUM

**Problem**: The old `session_state_update` WS message (from file watchers via `_on_session_state_update` callback) still fires in parallel with the new `session_update` message. The frontend handles both in `useWebSocket.ts`. Monitor state changes are broadcast twice — once via the old path and once via SessionManager.

**Fix**:

1. Remove `_on_session_state_update` callback registration from `register_provider_callbacks` (handler.py lines 295-296).
2. Remove the `session_state_update` handler in `useWebSocket.ts` (lines 29-32).
3. Update `test_websocket.py` — tests still expect removed message types (`notification_list`, `session_state_update`). These are stale and will fail once the old path is removed.

**Files**: `handler.py`, `frontend/src/hooks/useWebSocket.ts`, `tests/test_api/test_websocket.py`

---

## 4. `monitoredSessionIds` in frontend store

**Severity**: LOW

**Problem**: The frontend sessions store still tracks `monitoredSessionIds` and `monitoredSessionInfo` for WS subscription management. But `session_update` messages are broadcast to ALL clients (not subscription-filtered). The subscription mechanism is only needed for `session_history_append`.

**Fix**: Once the old `session_state_update` path is removed (item 3), subscriptions are only needed for `session_history_append`. The `monitoredSessionIds` set can stay as an internal mechanism for that purpose, but should not be exposed in the UI.

**Files**: `frontend/src/store/sessions.ts`, `frontend/src/hooks/useSessions.ts`

---

## 5. Rename `session_key` → `session_id` across WS and terminal APIs

**Severity**: LOW

**Problem**: Now that ProcessRegistry uses session ID directly as key, several fields still carry the old `key` / `session_key` naming:

- `ClientMessageTerminalInput.session_key` and `ClientMessageTerminalResize.session_key` in `ws_messages.py`
- `ServerMessageTerminalOutput.session_key` in `ws_messages.py`
- `TerminalLaunchResponse.key` in `terminal.py`
- Terminal WebSocket URL path parameter `/ws/terminal/{key}`

All carry session IDs but the names suggest a derived key.

**Fix**: Rename all to `session_id` in a single pass. Update handler code, frontend `EmbeddedTerminal.tsx`, and the WebSocket route registration.

**Files**: `models/ws_messages.py`, `api/routes/terminal.py`, `api/websocket/handler.py`, `api/websocket/terminal_handler.py`, `frontend/src/components/terminal/EmbeddedTerminal.tsx`

---

## Summary

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | Attention state owned by two places — make ProcessTracker sole owner |
| 2 | HIGH | Retire `CLISession` — REST API should return `Session`-derived data |
| 3 | MEDIUM | Old `session_state_update` WS path fires in parallel with `session_update` |
| 4 | LOW | `monitoredSessionIds` partially redundant in frontend store |
| 5 | LOW | `session_key` / `key` field naming → `session_id` |
