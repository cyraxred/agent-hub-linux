# Complete Unified File Watching Migration

## Context

The UNIFIED_FILE_WATCHING_PLAN.md introduced FileWatcher, TranscriptRegistry, and SessionTranscript to replace fragmented file watching. Phases 1-5 are done, but Phase 6 is incomplete: `CLISessionMonitorService` and `CodexSessionMonitorService` still do their own filesystem scanning instead of querying TranscriptRegistry. This creates two parallel discovery paths that can disagree about what sessions exist.

Additionally, test coverage for the new architecture is thin — FileWatcher has no direct unit tests, SessionTranscript is only tested indirectly, and TranscriptRegistry coverage is partial.

## Goal

1. Replace filesystem scanning in monitor services with TranscriptRegistry queries
2. Add comprehensive test coverage for the new architecture

---

## Part 1: Replace File Scanning in Monitor Services

### Step 1: `CLISessionMonitorService._find_sessions_for_path()` → query TranscriptRegistry

**File:** `src/agent_hub/services/cli_session_monitor.py`

- Add `_transcript_registry: TranscriptRegistry | None` field, set via new `set_transcript_registry()` method
- Rewrite `_find_sessions_for_path()`:
  - Instead of calling `find_session_files(session_dir)` + `parse_session_head()` + `stat()` per file, query `self._transcript_registry.get_all_transcripts()`
  - Filter transcripts whose `file_path` starts with `str(session_dir)`
  - Map each `SessionTranscript` → `CLISession` using transcript's `session_id`, `file_path`, `project_path`, and state data
  - Still enrich with `history.jsonl` data for `first_message` (history is not part of transcript state)
  - Still extract `slug` and `branch_name` from transcript's `parse_result` if available, otherwise fall back to `parse_session_head()`
  - **Fallback**: if `_transcript_registry` is None (not wired yet), use the existing filesystem scan — this keeps backward compat during startup sequencing

### Step 2: `CodexSessionMonitorService._find_sessions_for_path()` → query TranscriptRegistry

**File:** `src/agent_hub/services/codex_session_monitor.py`

- Same pattern: add `_transcript_registry` field and `set_transcript_registry()` method
- Rewrite `_find_sessions_for_path()` to query codex registry transcripts
- Filter by session dir path prefix
- Map to `CLISession` objects
- Enrich with history data
- Fallback to filesystem scan if registry not wired

### Step 3: Wire registries into monitor services

**File:** `src/agent_hub/provider.py`

In `init()`, after transcript registries are started and project directories are discovered (around line 342), call:
```python
self.claude_monitor.set_transcript_registry(self.claude_transcript_registry)
self.codex_monitor.set_transcript_registry(self.codex_transcript_registry)
```

### Step 4: Remove dead imports

**File:** `src/agent_hub/services/cli_session_monitor.py`
- Remove `find_session_files` import (only used in the old scanning path, kept in fallback)
- Remove `parse_session_head` import if no longer needed in primary path

### Step 5: Verify `handler.py` on_refresh wiring still works

**File:** `src/agent_hub/api/websocket/handler.py` (lines 322-331)

The `on_refresh` callbacks that call `sm.sync_discovered_sessions()` still work — the monitor's `refresh_sessions()` still fires `on_refresh` with `CLISession` list, but now that list comes from the registry instead of filesystem scanning. No changes needed here.

---

## Part 2: Test Coverage

### Test File 1: `tests/test_services/test_file_watcher_unit.py` (new)

FileWatcher singleton — currently 0% coverage.

Tests:
- `test_get_instance_returns_singleton` — two calls return same object
- `test_reset_instance` — creates new instance after reset
- `test_set_loop` — stores event loop reference
- `test_watch_directory_calls_schedule` — mock Observer, verify schedule called
- `test_unwatch_directory_decrements_refcount` — unwatch after last subscriber unschedules
- `test_watch_file_creates_parent_watch` — watching a file sets up directory watch internally
- `test_unwatch_file_removes_subscription`
- `test_on_modified_dispatches_to_file_subscribers` — simulate watchdog event, verify callback
- `test_on_created_dispatches_to_directory_subscribers` — simulate created event
- `test_on_deleted_dispatches_to_directory_subscribers`
- `test_initial_enumerate_fires_created` — on `watch_directory`, existing files get "created" callback
- `test_shutdown_stops_observer` — verify observer.stop() and observer.join()
- `test_multiple_subscribers_same_directory` — both callbacks fire, refcount correct

### Test File 2: `tests/test_services/test_session_transcript_unit.py` (new)

SessionTranscript — currently only tested indirectly through registry.

Tests:
- `test_initial_parse_reads_full_file` — byte_offset advances to file size
- `test_notify_file_modified_reads_delta` — only reads new bytes after offset
- `test_truncated_file_resets_offset` — file shrinks → offset resets to 0, re-parses
- `test_state_update_callback_fires` — on_state_update callback called after parse
- `test_history_append_callback_fires` — on_history_append with entries and total count
- `test_tool_result_callback_fires` — pending tool_use resolved → on_tool_result fires
- `test_check_status_timeout` — status transitions to idle after timeout
- `test_partial_line_handling` — file ends mid-JSON line, next read completes it
- `test_empty_file_no_crash` — 0-byte file doesn't error
- `test_file_not_found` — missing file handled gracefully in notify_file_modified

### Test File 3: `tests/test_services/test_transcript_registry_unit.py` (new)

TranscriptRegistry — extend coverage beyond existing `test_file_watcher.py`.

Tests:
- `test_add_project_directory_subscribes_to_filewatcher` — verify watch_directory called
- `test_remove_project_directory_unsubscribes` — verify unwatch + entries cleaned
- `test_classify_conversation_file_promotes` — .jsonl with valid content → SessionTranscript
- `test_classify_non_conversation_stays_int` — .jsonl without resumable content stays as int
- `test_unclassified_file_grows_and_promotes` — file starts small, grows, reclassified
- `test_deleted_file_fires_removed_callback` — on_transcript_removed called
- `test_on_transcript_added_callback` — fires with session_id and transcript
- `test_set_monitored_true_watches_file` — per-file watch subscription
- `test_set_monitored_false_unwatches_file`
- `test_register_transcript_manual` — backward compat `register_transcript()` method
- `test_register_transcript_idempotent` — calling twice returns same transcript
- `test_global_callbacks_wired_to_new_transcripts` — state/history/tool_result callbacks
- `test_stop_cleans_everything` — all watches removed, entries cleared

### Test File 4: `tests/test_services/test_session_manager_monitoring.py` (new)

SessionManager monitoring flags — manual_monitoring/auto_monitoring interaction.

Tests:
- `test_set_manual_monitoring_true` — sets flag, calls registry.set_monitored(True)
- `test_set_manual_monitoring_false` — clears flag, calls registry.set_monitored(False) if no auto
- `test_auto_monitoring_from_terminal_connected` — terminal connection sets auto_monitoring
- `test_auto_monitoring_from_attention` — pending attention + live process sets auto_monitoring
- `test_auto_monitoring_cleared_on_process_death` — process dies → auto_monitoring False
- `test_auto_monitoring_cleared_on_attention_resolved` — attention resolved → auto_monitoring recalculated
- `test_manual_and_auto_both_true` — monitored stays True when manual cleared but auto still True
- `test_handle_transcript_added_creates_session` — new transcript → Session created
- `test_handle_transcript_removed_without_process` — removes session
- `test_handle_transcript_removed_with_process` — keeps session, clears monitoring
- `test_sync_discovered_sessions_merges` — discovery data merged without overwriting live state

### Test File 5: `tests/test_services/test_monitor_service_registry_integration.py` (new)

Integration: monitor services using TranscriptRegistry instead of filesystem.

Tests:
- `test_refresh_sessions_uses_registry` — CLISessionMonitorService.refresh_sessions() returns sessions from registry, not from filesystem scan
- `test_refresh_sessions_fallback_without_registry` — when registry not set, falls back to filesystem
- `test_refresh_fires_callback_with_registry_data` — on_refresh callback receives correct CLISession list
- `test_history_enrichment` — first_message populated from history.jsonl even when using registry
- `test_codex_refresh_uses_registry` — same for CodexSessionMonitorService
- `test_worktree_detection_with_registry_data` — git worktree grouping works with registry-sourced sessions

---

## Execution Order

1. Write all new test files first (they'll initially fail or test missing functionality)
2. Modify `cli_session_monitor.py` — add registry field + rewrite `_find_sessions_for_path()`
3. Modify `codex_session_monitor.py` — same treatment
4. Modify `provider.py` — wire registries into monitors
5. Run full test suite, fix any failures
6. Clean up dead imports

## Key Files

| File | Action |
|------|--------|
| `src/agent_hub/services/cli_session_monitor.py` | Modify: add registry, rewrite `_find_sessions_for_path` |
| `src/agent_hub/services/codex_session_monitor.py` | Modify: add registry, rewrite `_find_sessions_for_path` |
| `src/agent_hub/provider.py` | Modify: wire registries into monitors (2 lines) |
| `src/agent_hub/services/transcript_registry.py` | Read-only (already has needed query API) |
| `src/agent_hub/services/session_transcript.py` | Read-only |
| `src/agent_hub/services/file_watcher.py` | Read-only |
| `src/agent_hub/services/session_manager.py` | Read-only |
| `tests/test_services/test_file_watcher_unit.py` | New |
| `tests/test_services/test_session_transcript_unit.py` | New |
| `tests/test_services/test_transcript_registry_unit.py` | New |
| `tests/test_services/test_session_manager_monitoring.py` | New |
| `tests/test_services/test_monitor_service_registry_integration.py` | New |

## Verification

1. `python -m pytest tests/ -x -q` — all tests pass
2. `python -m pytest tests/test_services/test_file_watcher_unit.py -v` — new FileWatcher tests
3. `python -m pytest tests/test_services/test_transcript_registry_unit.py -v` — new registry tests
4. `python -m pytest tests/test_integration/ -v` — existing integration tests still pass
5. Manual: start Agent Hub, verify sessions appear in UI via registry path (not filesystem scan)
