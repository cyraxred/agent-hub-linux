"""TranscriptRegistry — central owner of all transcript state.

Watches project directories via FileWatcher, classifies ``.jsonl`` files,
and manages ``SessionTranscript`` instances.  Fires callbacks when
transcripts are added/removed so that SessionManager can create/remove
sessions.

One registry per provider (claude / codex), each configured with its
``parse_fn``, ``parse_result_factory``, and base directories.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from agent_hub.config.defaults import STATUS_TIMER_INTERVAL
from agent_hub.services.file_watcher import FileWatcher
from agent_hub.services.path_utils import (
    _is_conversation_file,
    project_path_from_session_dir,
    session_id_from_path,
)
from agent_hub.services.session_transcript import SessionTranscript

logger = logging.getLogger(__name__)


class TranscriptRegistry:
    """Central transcript state for a single provider.

    Tracks all ``.jsonl`` files in watched project directories.
    Unclassified files are stored as ``int`` (last known file size);
    confirmed conversations are promoted to ``SessionTranscript``.
    """

    def __init__(
        self,
        provider: str,
        parse_fn: Callable,
        parse_result_factory: Callable[[], Any],
        approval_timeout_seconds: int = 5,
        parse_cache: Any | None = None,
        file_watcher: FileWatcher | None = None,
    ) -> None:
        self.provider = provider
        self._parse_fn = parse_fn
        self._parse_result_factory = parse_result_factory
        self._approval_timeout_seconds = approval_timeout_seconds
        self._parse_cache = parse_cache
        self._file_watcher = file_watcher or FileWatcher.get_instance()

        # Primary index: file_path -> SessionTranscript | int
        # int = last known file size (unclassified or not a session)
        self._entries: dict[str, SessionTranscript | int] = {}

        # Secondary index: session_id -> file_path
        self._session_index: dict[str, str] = {}

        # Tracked project directories
        self._project_dirs: set[str] = set()

        # Directory callback reference (for unwatch)
        self._dir_callbacks: dict[str, Callable] = {}

        # Callbacks
        self._on_added_callbacks: list[Callable] = []
        self._on_removed_callbacks: list[Callable] = []

        # Global callbacks for all transcripts (wired through to each)
        self._state_callbacks: list[Callable] = []
        self._history_callbacks: list[Callable] = []
        self._tool_result_callbacks: list[Callable] = []

        # Status timer
        self._status_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_transcript_added(self, callback: Callable) -> None:
        """Register: ``async def cb(session_id: str, transcript: SessionTranscript) -> None``"""
        self._on_added_callbacks.append(callback)

    def on_transcript_removed(self, callback: Callable) -> None:
        """Register: ``async def cb(session_id: str) -> None``"""
        self._on_removed_callbacks.append(callback)

    def on_state_update(self, callback: Callable) -> None:
        """Register a state-update callback that is wired into every transcript."""
        self._state_callbacks.append(callback)
        # Wire into existing transcripts
        for entry in self._entries.values():
            if isinstance(entry, SessionTranscript):
                entry.on_state_update(callback)

    def on_history_append(self, callback: Callable) -> None:
        """Register a history-append callback wired into every transcript."""
        self._history_callbacks.append(callback)
        for entry in self._entries.values():
            if isinstance(entry, SessionTranscript):
                entry.on_history_append(callback)

    def on_tool_result(self, callback: Callable) -> None:
        """Register a tool-result callback wired into every transcript."""
        self._tool_result_callbacks.append(callback)
        for entry in self._entries.values():
            if isinstance(entry, SessionTranscript):
                entry.on_tool_result(callback)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_transcript(self, session_id: str) -> SessionTranscript | None:
        """Return the transcript for a session, or None."""
        fp = self._session_index.get(session_id)
        if fp is None:
            return None
        entry = self._entries.get(fp)
        return entry if isinstance(entry, SessionTranscript) else None

    def get_all_transcripts(self) -> list[SessionTranscript]:
        """Return all confirmed transcripts."""
        return [e for e in self._entries.values() if isinstance(e, SessionTranscript)]

    def get_all_session_ids(self) -> set[str]:
        """Return all known session IDs."""
        return set(self._session_index.keys())

    # ------------------------------------------------------------------
    # Project directory management
    # ------------------------------------------------------------------

    async def add_project_directory(self, path: str) -> None:
        """Start watching a project directory for transcript files.

        Awaits the initial file enumeration so all existing transcripts
        are registered before this method returns.
        """
        dir_path = str(Path(path).resolve())
        if dir_path in self._project_dirs:
            return
        self._project_dirs.add(dir_path)

        async def _on_dir_event(event_type: str, file_path: str) -> None:
            await self._handle_dir_event(dir_path, event_type, file_path)

        self._dir_callbacks[dir_path] = _on_dir_event
        await self._file_watcher.watch_directory(dir_path, _on_dir_event)

    def remove_project_directory(self, path: str) -> None:
        """Stop watching a project directory."""
        dir_path = str(Path(path).resolve())
        if dir_path not in self._project_dirs:
            return
        self._project_dirs.discard(dir_path)

        cb = self._dir_callbacks.pop(dir_path, None)
        if cb is not None:
            self._file_watcher.unwatch_directory(dir_path, cb)

        # Remove all entries under this directory
        to_remove = [fp for fp in self._entries if fp.startswith(dir_path + "/")]
        for fp in to_remove:
            entry = self._entries.pop(fp, None)
            if isinstance(entry, SessionTranscript):
                sid = entry.session_id
                self._session_index.pop(sid, None)
                if entry.is_monitored:
                    self._unwatch_transcript_file(entry)
                self._fire_removed(sid)

    # ------------------------------------------------------------------
    # Monitoring control (called by SessionManager)
    # ------------------------------------------------------------------

    def set_monitored(self, session_id: str, monitored: bool) -> None:
        """Set per-file monitoring for instant notification.

        When monitored, the transcript's file is watched via
        FileWatcher.watch_file() for immediate inotify events.
        When not monitored, only directory-level events reach it.
        """
        transcript = self.get_transcript(session_id)
        if transcript is None:
            return
        if transcript.is_monitored == monitored:
            return
        transcript.is_monitored = monitored
        if monitored:
            self._watch_transcript_file(transcript)
        else:
            self._unwatch_transcript_file(transcript)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the status timer loop."""
        if self._status_task is None:
            self._status_task = asyncio.create_task(self._status_timer_loop())

    async def stop(self) -> None:
        """Stop background tasks and unwatch all directories."""
        if self._status_task is not None:
            self._status_task.cancel()
            self._status_task = None

        # Unwatch all directories
        for dir_path in list(self._project_dirs):
            self.remove_project_directory(dir_path)

        # Unwatch all per-file watches
        for entry in self._entries.values():
            if isinstance(entry, SessionTranscript) and entry.is_monitored:
                self._unwatch_transcript_file(entry)

        self._entries.clear()
        self._session_index.clear()

    # ------------------------------------------------------------------
    # Internal: directory event handling
    # ------------------------------------------------------------------

    async def _handle_dir_event(
        self, dir_path: str, event_type: str, file_path: str
    ) -> None:
        """Handle a FileWatcher directory event."""
        if not file_path.endswith(".jsonl"):
            return

        if event_type == "created":
            if file_path not in self._entries:
                # New file — check file size and classify
                await self._classify_and_add(file_path, dir_path)

        elif event_type == "modified":
            entry = self._entries.get(file_path)
            if entry is None:
                # File we haven't seen before (race between created/modified)
                await self._classify_and_add(file_path, dir_path)
            elif isinstance(entry, int):
                # Unclassified file grew — re-check
                try:
                    new_size = Path(file_path).stat().st_size
                except OSError:
                    return
                if new_size > entry:
                    self._entries[file_path] = new_size
                    await self._try_promote(file_path, dir_path)
            elif isinstance(entry, SessionTranscript):
                # Confirmed transcript — notify
                await entry.notify_file_modified()

        elif event_type == "deleted":
            entry = self._entries.pop(file_path, None)
            if isinstance(entry, SessionTranscript):
                sid = entry.session_id
                self._session_index.pop(sid, None)
                if entry.is_monitored:
                    self._unwatch_transcript_file(entry)
                self._fire_removed(sid)

    async def _classify_and_add(self, file_path: str, dir_path: str) -> None:
        """Classify a new file and add it to the registry."""
        p = Path(file_path)
        if not p.is_file():
            return

        try:
            size = p.stat().st_size
        except OSError:
            return

        if _is_conversation_file(p):
            await self._promote(file_path, dir_path)
        else:
            self._entries[file_path] = size

    async def _try_promote(self, file_path: str, dir_path: str) -> None:
        """Re-classify and promote if the file is now a conversation."""
        p = Path(file_path)
        if _is_conversation_file(p):
            await self._promote(file_path, dir_path)

    async def _promote(self, file_path: str, dir_path: str) -> None:
        """Promote a file to a SessionTranscript."""
        p = Path(file_path)
        session_id = session_id_from_path(p)

        # Decode the project path from the encoded directory name
        # dir_path is like ~/.claude/projects/{encoded}/
        project_path = project_path_from_session_dir(Path(dir_path))

        transcript = SessionTranscript(
            session_id=session_id,
            file_path=file_path,
            project_path=project_path,
            parse_fn=self._parse_fn,
            parse_result_factory=self._parse_result_factory,
            provider=self.provider,
            approval_timeout_seconds=self._approval_timeout_seconds,
            parse_cache=self._parse_cache,
        )

        # Wire global callbacks
        for cb in self._state_callbacks:
            transcript.on_state_update(cb)
        for cb in self._history_callbacks:
            transcript.on_history_append(cb)
        for cb in self._tool_result_callbacks:
            transcript.on_tool_result(cb)

        self._entries[file_path] = transcript
        self._session_index[session_id] = file_path

        # Do initial parse
        await transcript.do_initial_parse()

        # Fire callback
        await self._fire_added(session_id, transcript)

    # ------------------------------------------------------------------
    # Internal: per-file watch management
    # ------------------------------------------------------------------

    def _watch_transcript_file(self, transcript: SessionTranscript) -> None:
        """Subscribe to per-file events for instant notification."""

        async def _on_file_event(event_type: str, file_path: str) -> None:
            if event_type == "modified":
                await transcript.notify_file_modified()

        # Store reference for unwatch
        transcript._file_watch_cb = _on_file_event  # type: ignore[attr-defined]
        self._file_watcher.watch_file(transcript.file_path, _on_file_event)

    def _unwatch_transcript_file(self, transcript: SessionTranscript) -> None:
        """Remove per-file subscription."""
        cb = getattr(transcript, "_file_watch_cb", None)
        if cb is not None:
            self._file_watcher.unwatch_file(transcript.file_path, cb)
            transcript._file_watch_cb = None  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Internal: callbacks
    # ------------------------------------------------------------------

    async def _fire_added(
        self, session_id: str, transcript: SessionTranscript
    ) -> None:
        for cb in self._on_added_callbacks:
            try:
                await cb(session_id, transcript)
            except Exception:
                logger.exception("Error in on_transcript_added callback")

    def _fire_removed(self, session_id: str) -> None:
        for cb in self._on_removed_callbacks:
            try:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(cb(session_id), loop)
            except Exception:
                logger.exception("Error in on_transcript_removed callback")

    # ------------------------------------------------------------------
    # Internal: status timer
    # ------------------------------------------------------------------

    async def _status_timer_loop(self) -> None:
        """Periodically re-evaluate session statuses."""
        try:
            from datetime import datetime, timezone

            while True:
                await asyncio.sleep(STATUS_TIMER_INTERVAL)
                now = datetime.now(tz=timezone.utc)
                for entry in list(self._entries.values()):
                    if not isinstance(entry, SessionTranscript):
                        continue
                    if entry.check_status_timeout(now):
                        await entry._notify_state_update()

                    # Stale watcher health check (for monitored transcripts)
                    if entry.is_monitored:
                        path = Path(entry.file_path)
                        if path.is_file():
                            try:
                                file_size = path.stat().st_size
                                if (
                                    file_size > entry.byte_offset
                                    and entry.last_file_check > 0
                                    and (now.timestamp() - entry.last_file_check > 30)
                                ):
                                    await entry.notify_file_modified()
                            except OSError:
                                pass
                        entry.last_file_check = now.timestamp()
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Manual transcript registration (for backward compat)
    # ------------------------------------------------------------------

    async def register_transcript(
        self,
        session_id: str,
        project_path: str,
        file_path: str,
    ) -> SessionTranscript:
        """Manually register a transcript (used by start_monitoring compat layer).

        If the transcript already exists, returns it.
        """
        existing = self.get_transcript(session_id)
        if existing is not None:
            return existing

        resolved_path = str(Path(file_path).resolve())
        dir_path = str(Path(resolved_path).parent)

        transcript = SessionTranscript(
            session_id=session_id,
            file_path=resolved_path,
            project_path=project_path,
            parse_fn=self._parse_fn,
            parse_result_factory=self._parse_result_factory,
            provider=self.provider,
            approval_timeout_seconds=self._approval_timeout_seconds,
            parse_cache=self._parse_cache,
        )

        # Wire global callbacks
        for cb in self._state_callbacks:
            transcript.on_state_update(cb)
        for cb in self._history_callbacks:
            transcript.on_history_append(cb)
        for cb in self._tool_result_callbacks:
            transcript.on_tool_result(cb)

        self._entries[resolved_path] = transcript
        self._session_index[session_id] = resolved_path

        # Initial parse
        await transcript.do_initial_parse()

        # Fire callback
        await self._fire_added(session_id, transcript)

        return transcript
