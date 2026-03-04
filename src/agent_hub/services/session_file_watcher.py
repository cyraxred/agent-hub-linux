"""Session file watcher using watchdog + byte-offset incremental reads.

Ported from Swift SessionFileWatcher.swift.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agent_hub.config.defaults import (
    SESSION_ACTIVE_THRESHOLD,
    STALE_WATCHER_THRESHOLD,
    STATUS_TIMER_INTERVAL,
)
from agent_hub.models.monitor_state import (
    MermaidDiagramInfo,
    PlanInfo,
    SessionMonitorState,
    SessionStatusIdle,
)
import json as _json

from agent_hub.services.session_jsonl_parser import ParseResult, parse_new_lines

logger = logging.getLogger(__name__)


@dataclass
class _WatchedSession:
    """Internal state for a single watched session file."""

    session_id: str
    project_path: str
    file_path: str
    byte_offset: int = 0
    line_count: int = 0
    parse_result: ParseResult = field(default_factory=ParseResult)
    state: SessionMonitorState = field(default_factory=SessionMonitorState)
    last_file_check: float = 0.0


class _FileChangeHandler(FileSystemEventHandler):
    """Handle file modification events from watchdog."""

    def __init__(self, callback: asyncio.coroutines, loop: asyncio.AbstractEventLoop) -> None:  # type: ignore[type-arg]
        super().__init__()
        self._callback = callback
        self._loop = loop

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            asyncio.run_coroutine_threadsafe(self._callback(str(event.src_path)), self._loop)


class SessionFileWatcher:
    """Watches session JSONL files for changes and maintains parse state."""

    def __init__(
        self,
        claude_path: str = "~/.claude",
        approval_timeout_seconds: int = 5,
        parse_cache: object | None = None,
    ) -> None:
        self._claude_path = str(Path(claude_path).expanduser())
        self._approval_timeout_seconds = approval_timeout_seconds
        self._parse_cache = parse_cache
        self._sessions: dict[str, _WatchedSession] = {}
        self._observer: Observer | None = None
        self._status_task: asyncio.Task[None] | None = None
        self._state_callbacks: list[
            asyncio.coroutines  # type: ignore[type-arg]
        ] = []
        self._history_callbacks: list[
            asyncio.coroutines  # type: ignore[type-arg]
        ] = []
        self._lock = asyncio.Lock()

    def on_state_update(self, callback: object) -> None:
        """Register a callback for state updates."""
        self._state_callbacks.append(callback)  # type: ignore[arg-type]

    def on_history_append(self, callback: object) -> None:
        """Register a callback for new raw JSONL entries."""
        self._history_callbacks.append(callback)  # type: ignore[arg-type]

    async def _notify_state_update(self, session_id: str, state: SessionMonitorState) -> None:
        """Notify all registered callbacks of a state update."""
        for cb in self._state_callbacks:
            try:
                await cb(session_id, state)  # type: ignore[misc]
            except Exception:
                logger.exception("Error in state update callback")

    async def _notify_history_append(
        self,
        session_id: str,
        new_entries: list[dict[str, object]],
        total_lines: int,
    ) -> None:
        """Notify callbacks of newly parsed raw JSONL entries."""
        for cb in self._history_callbacks:
            try:
                await cb(session_id, new_entries, total_lines)  # type: ignore[misc]
            except Exception:
                logger.exception("Error in history append callback")

    async def start_monitoring(
        self,
        session_id: str,
        project_path: str,
        session_file_path: str | None = None,
    ) -> None:
        """Start monitoring a session's JSONL file."""
        async with self._lock:
            if session_id in self._sessions:
                return

            # Determine file path
            if session_file_path:
                file_path = session_file_path
            else:
                from agent_hub.services.path_utils import encode_project_path

                encoded = encode_project_path(project_path)
                file_path = str(
                    Path(self._claude_path) / "projects" / encoded / f"{session_id}.jsonl"
                )

            watched = _WatchedSession(
                session_id=session_id,
                project_path=project_path,
                file_path=file_path,
            )
            self._sessions[session_id] = watched

            # Initial parse
            await self._read_new_content(watched)

            # Start observer if not running
            if self._observer is None:
                self._observer = Observer()
                self._observer.daemon = True
                self._observer.start()

            # Start status timer if not running
            if self._status_task is None:
                self._status_task = asyncio.create_task(self._status_timer_loop())

            # Watch the directory containing the session file
            dir_path = str(Path(file_path).parent)
            if Path(dir_path).is_dir():
                loop = asyncio.get_event_loop()
                handler = _FileChangeHandler(self._on_file_changed, loop)
                self._observer.schedule(handler, dir_path, recursive=False)

    async def stop_monitoring(self, session_id: str) -> None:
        """Stop monitoring a session."""
        async with self._lock:
            self._sessions.pop(session_id, None)

            if not self._sessions:
                if self._observer is not None:
                    self._observer.stop()
                    self._observer = None
                if self._status_task is not None:
                    self._status_task.cancel()
                    self._status_task = None

    async def get_state(self, session_id: str) -> SessionMonitorState | None:
        """Get current monitor state for a session."""
        watched = self._sessions.get(session_id)
        return watched.state if watched else None

    async def refresh_state(self, session_id: str) -> None:
        """Force-refresh the monitor state for a session."""
        watched = self._sessions.get(session_id)
        if watched:
            watched.byte_offset = 0
            watched.parse_result = ParseResult()
            await self._read_new_content(watched)

    async def set_approval_timeout(self, seconds: int) -> None:
        """Set the approval timeout threshold."""
        self._approval_timeout_seconds = seconds

    async def _on_file_changed(self, file_path: str) -> None:
        """Handle a file change notification."""
        for watched in self._sessions.values():
            if watched.file_path == file_path:
                await self._read_new_content(watched)
                break

    async def _read_new_content(self, watched: _WatchedSession) -> None:
        """Read new content from a session file using byte-offset."""
        path = Path(watched.file_path)
        if not path.is_file():
            return

        try:
            file_size = path.stat().st_size
            if file_size <= watched.byte_offset:
                return

            loop = asyncio.get_event_loop()
            new_data = await loop.run_in_executor(
                None, self._read_bytes, watched.file_path, watched.byte_offset
            )

            if not new_data:
                return

            watched.byte_offset += len(new_data)
            lines = new_data.decode("utf-8", errors="replace").splitlines()

            parse_new_lines(
                lines, watched.parse_result, self._approval_timeout_seconds
            )

            # Build raw history entries from the new lines
            new_entries: list[dict[str, object]] = []
            for raw_line in lines:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    data = _json.loads(raw_line)
                    if isinstance(data, dict):
                        watched.line_count += 1
                        new_entries.append(
                            {
                                "line": watched.line_count,
                                "type": str(data.get("type", "")),
                                "data": data,
                            }
                        )
                except (ValueError, _json.JSONDecodeError):
                    continue

            self._update_state_from_parse(watched)
            await self._notify_state_update(watched.session_id, watched.state)

            if new_entries:
                await self._notify_history_append(
                    watched.session_id, new_entries, watched.line_count
                )

            # Write-through to parse cache
            if self._parse_cache is not None:
                self._parse_cache.put(  # type: ignore[union-attr]
                    session_id=watched.session_id,
                    file_path=watched.file_path,
                    file_size=watched.byte_offset,
                    parse_result=watched.parse_result,
                    provider="claude",
                )

        except OSError:
            logger.exception("Error reading session file: %s", watched.file_path)

    @staticmethod
    def _read_bytes(file_path: str, offset: int) -> bytes:
        """Read bytes from file starting at offset (runs in executor)."""
        with open(file_path, "rb") as f:
            f.seek(offset)
            return f.read()

    def _update_state_from_parse(self, watched: _WatchedSession) -> None:
        """Update the SessionMonitorState from the ParseResult."""
        pr = watched.parse_result

        watched.state.model = pr.model
        watched.state.input_tokens = pr.last_input_tokens
        watched.state.output_tokens = pr.last_output_tokens
        watched.state.total_output_tokens = pr.total_output_tokens
        watched.state.cache_read_tokens = pr.cache_read_tokens
        watched.state.cache_creation_tokens = pr.cache_creation_tokens
        watched.state.message_count = pr.message_count
        watched.state.tool_calls = dict(pr.tool_calls)
        watched.state.recent_activities = list(pr.recent_activities)
        watched.state.git_branch = pr.git_branch

        # Backward-compat scalar fields (from properties on ParseResult)
        watched.state.has_mermaid_content = pr.has_mermaid_content
        watched.state.plan_file_path = pr.plan_file_path
        watched.state.plan_content = pr.plan_content

        # List fields
        watched.state.plans = [
            PlanInfo(file_path=p.file_path, content=p.content, timestamp=p.timestamp.isoformat())
            for p in pr.plans
        ]
        watched.state.mermaid_diagrams = [
            MermaidDiagramInfo(source=d.source, file_path=d.file_path, timestamp=d.timestamp.isoformat())
            for d in pr.mermaid_diagrams
        ]

        if pr.session_started_at:
            watched.state.session_started_at = pr.session_started_at
        if pr.last_activity_at:
            watched.state.last_activity_at = pr.last_activity_at

        if pr.current_status is not None:
            watched.state.status = pr.current_status.status
            watched.state.pending_tool_use = pr.current_status.pending_tool_use

    async def _status_timer_loop(self) -> None:
        """Periodically re-evaluate session statuses."""
        try:
            while True:
                await asyncio.sleep(STATUS_TIMER_INTERVAL)
                now = datetime.now(tz=timezone.utc)
                for watched in list(self._sessions.values()):
                    # Re-evaluate timeout-based status transitions
                    if watched.parse_result.recent_activities:
                        last = watched.parse_result.recent_activities[-1]
                        elapsed = (now - last.timestamp).total_seconds()

                        if elapsed > SESSION_ACTIVE_THRESHOLD:
                            if watched.state.status.kind != "idle":
                                watched.state.status = SessionStatusIdle()
                                await self._notify_state_update(
                                    watched.session_id, watched.state
                                )

                    # Stale watcher health check
                    path = Path(watched.file_path)
                    if path.is_file():
                        try:
                            file_size = path.stat().st_size
                            if (
                                file_size > watched.byte_offset
                                and watched.last_file_check > 0
                                and (
                                    now.timestamp() - watched.last_file_check
                                    > STALE_WATCHER_THRESHOLD
                                )
                            ):
                                await self._read_new_content(watched)
                        except OSError:
                            pass
                    watched.last_file_check = now.timestamp()
        except asyncio.CancelledError:
            pass

    async def shutdown(self) -> None:
        """Clean up all watchers and timers."""
        if self._observer is not None:
            self._observer.stop()
            self._observer = None
        if self._status_task is not None:
            self._status_task.cancel()
            self._status_task = None
        self._sessions.clear()
