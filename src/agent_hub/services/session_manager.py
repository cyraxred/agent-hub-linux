"""SessionManager — unified session state for the entire application.

Aggregates data from process tracker, file watchers, session monitors,
and terminal registry into a single ``Session`` object per session.
Fires callbacks on any mutation so the WebSocket handler can broadcast
a single ``session_update`` message.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.process_info import ClaudeProcessCategory, ClaudeProcessInfo

logger = logging.getLogger(__name__)

# Debounce: at most one broadcast per session per this interval.
_DEBOUNCE_SECONDS = 0.2


@dataclass
class _AttentionEntry:
    """Mirrors the tracker's attention entry for unified state."""

    session_id: str
    tool_use_id: str
    tool_name: str
    attention_kind: str  # "awaiting_approval" | "awaiting_question"
    ts: float = 0


@dataclass
class Session:
    """Unified session state."""

    session_id: str
    project_path: str = ""
    session_file_path: str = ""
    provider: str = "claude"
    slug: str = ""
    first_message: str = ""
    last_activity_at: datetime | None = None
    branch_name: str = ""
    monitor_state: SessionMonitorState | None = None
    process: ClaudeProcessInfo | None = None
    pending_attention: list[_AttentionEntry] = field(default_factory=list)
    terminal_key: str | None = None

    # -- Computed properties --

    @property
    def is_active(self) -> bool:
        """True when a live process owns this session."""
        return self.process is not None

    @property
    def is_connectable(self) -> bool:
        """True when active and the process category allows terminal attach."""
        if self.process is None:
            return False
        return self.process.category in (
            ClaudeProcessCategory.hub,
            ClaudeProcessCategory.tmux,
        )

    @property
    def is_resumable(self) -> bool:
        """True when no live process owns this session (safe to --resume)."""
        return self.process is None

    @property
    def needs_attention(self) -> bool:
        return len(self.pending_attention) > 0

    @property
    def is_monitored(self) -> bool:
        return self.monitor_state is not None

    @property
    def effective_status(self) -> str:
        """Derive a single status string for the UI.

        Priority: attention > monitor status > active > idle.
        """
        if self.pending_attention:
            return self.pending_attention[-1].attention_kind
        if self.monitor_state and self.monitor_state.status:
            return self.monitor_state.status.kind
        if self.is_active:
            return "active"
        return "idle"


class SessionManager:
    """Central session state aggregator.

    All mutation methods are designed to be called from async callbacks
    registered on the process tracker, file watchers, session monitors,
    and terminal routes.  After each mutation the registered update
    callbacks are fired (debounced per session).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._update_callbacks: list[Callable] = []
        self._lock = asyncio.Lock()
        # Per-session debounce: session_id -> scheduled Task
        self._pending_broadcasts: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_session_update(self, callback: Callable) -> None:
        """Register ``async def cb(session_id: str) -> None``."""
        self._update_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def get_all_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    # ------------------------------------------------------------------
    # Mutation entry points
    # ------------------------------------------------------------------

    async def handle_process_update(self) -> None:
        """Called by process tracker on_update (process state changed).

        We pull the latest states from the tracker and reconcile.
        The tracker ref is injected via ``set_tracker``.
        """
        if self._tracker is None:
            return
        async with self._lock:
            states = self._tracker.get_all_process_states()
            changed_ids: set[str] = set()

            # Update sessions that have a process
            seen_session_ids: set[str] = set()
            for sid, ps in states.items():
                seen_session_ids.add(sid)
                session = self._sessions.get(sid)
                if session is None:
                    session = Session(session_id=sid)
                    self._sessions[sid] = session
                if session.process != ps.process:
                    session.process = ps.process
                    changed_ids.add(sid)

            # Clear process for sessions that are no longer tracked
            for sid, session in self._sessions.items():
                if sid not in seen_session_ids and session.process is not None:
                    session.process = None
                    changed_ids.add(sid)

            for sid in changed_ids:
                self._schedule_notify(sid)

    async def handle_attention(self, entry: object) -> None:
        """Called by process tracker on_attention."""
        session_id: str = entry.session_id  # type: ignore[attr-defined]
        tool_use_id: str = entry.tool_use_id  # type: ignore[attr-defined]
        tool_name: str = entry.tool_name  # type: ignore[attr-defined]
        attention_kind: str = entry.attention_kind  # type: ignore[attr-defined]
        ts: float = getattr(entry, "ts", 0)

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(session_id=session_id)
                self._sessions[session_id] = session

            # Deduplicate by tool_use_id
            if any(a.tool_use_id == tool_use_id for a in session.pending_attention):
                return

            session.pending_attention.append(
                _AttentionEntry(
                    session_id=session_id,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    attention_kind=attention_kind,
                    ts=ts,
                )
            )
            self._schedule_notify(session_id)

    async def handle_attention_resolved(self, session_id: str, tool_use_id: str) -> None:
        """Called by process tracker on_attention_resolved or file watcher on_tool_result."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            before = len(session.pending_attention)
            session.pending_attention = [
                a for a in session.pending_attention if a.tool_use_id != tool_use_id
            ]
            if len(session.pending_attention) != before:
                self._schedule_notify(session_id)

    async def handle_monitor_state_update(
        self, session_id: str, state: SessionMonitorState
    ) -> None:
        """Called by file watcher on_state_update."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(session_id=session_id)
                self._sessions[session_id] = session
            session.monitor_state = state
            self._schedule_notify(session_id)

    async def handle_monitor_stopped(self, session_id: str) -> None:
        """Called when file watcher stops monitoring a session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.monitor_state = None
            self._schedule_notify(session_id)

    async def handle_terminal_registered(self, session_id: str, key: str) -> None:
        """Called after terminal launch."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(session_id=session_id)
                self._sessions[session_id] = session
            session.terminal_key = key
            self._schedule_notify(session_id)

    async def handle_terminal_unregistered(self, session_id: str) -> None:
        """Called after terminal terminate."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.terminal_key = None
            self._schedule_notify(session_id)

    async def sync_discovered_sessions(
        self,
        discovered: list[object],
        provider: str,
    ) -> None:
        """Called after CLISessionMonitorService / CodexSessionMonitorService refresh.

        ``discovered`` is a list of CLISession objects from the monitor.
        We merge discovery data (project_path, slug, etc.) into our state
        without overwriting live process/monitor data.
        """
        async with self._lock:
            seen: set[str] = set()
            for d in discovered:
                sid = d.id  # type: ignore[attr-defined]
                seen.add(sid)
                session = self._sessions.get(sid)
                if session is None:
                    session = Session(session_id=sid)
                    self._sessions[sid] = session

                # Merge discovery fields (don't overwrite process/monitor)
                session.project_path = getattr(d, "project_path", session.project_path)
                session.session_file_path = getattr(d, "session_file_path", session.session_file_path)
                session.provider = provider
                session.slug = getattr(d, "slug", session.slug) or session.slug
                session.first_message = getattr(d, "first_message", session.first_message) or session.first_message
                session.branch_name = getattr(d, "branch_name", session.branch_name) or session.branch_name
                last = getattr(d, "last_activity_at", None)
                if last is not None:
                    session.last_activity_at = last

            # We don't remove sessions not in discovered — they may still
            # have live processes or monitoring state.

    # ------------------------------------------------------------------
    # Tracker reference (set during wiring)
    # ------------------------------------------------------------------

    _tracker: object | None = None

    def set_tracker(self, tracker: object) -> None:
        self._tracker = tracker

    # ------------------------------------------------------------------
    # Internal: debounced notification
    # ------------------------------------------------------------------

    def _schedule_notify(self, session_id: str) -> None:
        """Schedule a debounced callback fire for this session."""
        existing = self._pending_broadcasts.get(session_id)
        if existing is not None and not existing.done():
            # Already scheduled — the pending task will pick up the latest state
            return
        self._pending_broadcasts[session_id] = asyncio.ensure_future(
            self._debounced_notify(session_id)
        )

    async def _debounced_notify(self, session_id: str) -> None:
        await asyncio.sleep(_DEBOUNCE_SECONDS)
        self._pending_broadcasts.pop(session_id, None)
        for cb in self._update_callbacks:
            try:
                await cb(session_id)
            except Exception:
                logger.exception("Error in session update callback for %s", session_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """No-op for now — manager is stateless on startup."""
        logger.info("SessionManager started")

    async def stop(self) -> None:
        """Cancel any pending debounce tasks."""
        for task in self._pending_broadcasts.values():
            task.cancel()
        self._pending_broadcasts.clear()
        logger.info("SessionManager stopped")
