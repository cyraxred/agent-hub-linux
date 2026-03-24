"""SessionManager — unified session state for the entire application.

Aggregates data from process tracker, file watchers, session monitors,
and terminal registry into a single ``Session`` object per session.
Fires callbacks on any mutation so the WebSocket handler can broadcast
a single ``session_update`` message.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from agent_hub.config.defaults import STOP_IDLE_PROCESS_MS, STOP_NOANSWER_PROCESS_MS
from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.process_info import ClaudeProcessCategory, ClaudeProcessInfo

if TYPE_CHECKING:
    from agent_hub.services.claude_process_tracker import ClaudeProcessTracker
    from agent_hub.services.process_registry import ProcessRegistry

logger = logging.getLogger(__name__)

# Debounce: at most one broadcast per session per this interval.
_DEBOUNCE_SECONDS = 0.2


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

    # -- Computed properties --
    #
    # These flags are the authoritative session state sent to the frontend
    # via the ``session_update`` WS message.  They drive badge rendering,
    # terminal launch guards, and attention indicators.
    #
    # State matrix:
    #
    #   process        | is_running | is_connectable
    #   ---------------+------------+---------------
    #   None (idle)    |   False    |     True       (resume)
    #   hub / tmux     |   True     |     True       (attach)
    #   user / 3rd_pty |   True     |     False      (blocked)
    #
    # ``is_running`` is internal only (not sent to the frontend).
    # ``is_connectable`` is the single flag the UI needs for the terminal
    # button.  The backend decides resume vs attach in the launch endpoint.
    #
    # Attention state (``needs_attention``, ``effective_status``) is owned
    # exclusively by the ProcessTracker and queried via SessionManager
    # methods — not stored on Session.

    @property
    def is_running(self) -> bool:
        """A ``claude`` OS process is alive and mapped to this session.

        Determined by the process tracker scanning ``/proc`` and correlating
        PIDs with entries in ``~/.claude/agent-hub/sessions.jsonl``.

        Internal only — not sent to the frontend.  The frontend derives
        "running" from ``process_pid is not None`` if it ever needs it.
        """
        return self.process is not None

    @property
    def is_connectable(self) -> bool:
        """Whether a terminal can be opened for this session.

        True in two cases:
        - No process running → safe to ``claude --resume``.
        - Process running with ``hub`` or ``tmux`` category →
          backend will attach to the existing process.

        False when:
        - A ``user`` or ``third_party`` process is running (no multiplexer).

        This is the single flag the UI needs for the terminal button.
        """
        if self.process is None:
            return True
        return self.process.category in (
            ClaudeProcessCategory.hub,
            ClaudeProcessCategory.tmux,
        )

    @property
    def is_monitored(self) -> bool:
        """A file watcher is actively parsing this session's JSONL.

        Provides live token counts, activity history, tool calls, etc.
        Monitoring starts automatically when the session detail view opens
        and stops when it closes.
        """
        return self.monitor_state is not None


class SessionManager:
    """Central session state aggregator.

    All mutation methods are designed to be called from async callbacks
    registered on the process tracker, file watchers, session monitors,
    and terminal routes.  After each mutation the registered update
    callbacks are fired (debounced per session).

    Attention state is owned exclusively by the ProcessTracker.
    This manager queries it on demand via ``get_needs_attention`` and
    ``get_effective_status`` — no local copy is kept.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._update_callbacks: list[Callable] = []
        self._lock = asyncio.Lock()
        # Per-session debounce: session_id -> scheduled Task
        self._pending_broadcasts: dict[str, asyncio.Task] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._process_registry: ProcessRegistry | None = None

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

    def get_needs_attention(self, session_id: str) -> bool:
        """Whether the session has pending attention events.

        Queries the ProcessTracker directly — no local copy.
        """
        session = self._sessions.get(session_id)
        if session is None or not session.is_running or self._tracker is None:
            return False
        return len(self._tracker.get_pending_attention_for_session(session_id)) > 0

    def get_effective_status(self, session_id: str) -> str:
        """Single status string for the UI.

        Priority: attention > monitor status > running > idle.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return "idle"
        if self.get_needs_attention(session_id):
            entries = self._tracker.get_pending_attention_for_session(session_id)
            return entries[-1].attention_kind if entries else "idle"
        if session.monitor_state and session.monitor_state.status:
            return session.monitor_state.status.kind
        if session.is_running:
            return "running"
        return "idle"

    def get_pending_attention(self, session_id: str) -> list:
        """Return pending attention entries from the tracker."""
        if self._tracker is None:
            return []
        return self._tracker.get_pending_attention_for_session(session_id)

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
            now = datetime.now(tz=timezone.utc)

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
                    session.last_activity_at = now
                    changed_ids.add(sid)

            # Clear process for sessions no longer tracked
            for sid, session in self._sessions.items():
                if sid not in seen_session_ids and session.process is not None:
                    session.process = None
                    session.last_activity_at = now
                    changed_ids.add(sid)

            for sid in changed_ids:
                self._schedule_notify(sid)

    async def handle_attention_changed(self, session_id: str) -> None:
        """Called when the tracker fires an attention or attention-resolved callback.

        We don't store any attention data — just trigger a broadcast so
        the WS handler can query the tracker for the current state.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_activity_at = datetime.now(tz=timezone.utc)
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
            if state.last_activity_at:
                session.last_activity_at = state.last_activity_at
            self._schedule_notify(session_id)

    async def handle_monitor_stopped(self, session_id: str) -> None:
        """Called when file watcher stops monitoring a session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.monitor_state = None
            self._schedule_notify(session_id)

    async def handle_terminal_registered(self, session_id: str) -> None:
        """Called after terminal launch. Triggers a broadcast."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(session_id=session_id)
                self._sessions[session_id] = session
            self._schedule_notify(session_id)

    async def handle_terminal_unregistered(self, session_id: str) -> None:
        """Called after terminal terminate. Triggers a broadcast."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
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
            for d in discovered:
                sid = d.id  # type: ignore[attr-defined]
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

    _tracker: ClaudeProcessTracker | None = None

    def set_tracker(self, tracker: ClaudeProcessTracker) -> None:
        self._tracker = tracker

    def set_process_registry(self, registry: ProcessRegistry) -> None:
        self._process_registry = registry
        registry.set_activity_callback(self.handle_terminal_activity)

    # ------------------------------------------------------------------
    # Terminal I/O activity
    # ------------------------------------------------------------------

    async def handle_terminal_activity(self, session_id: str) -> None:
        """Called by ProcessRegistry on PTY output or input.

        Updates ``last_activity_at`` without triggering a broadcast
        (to avoid flooding WS with timestamp-only updates).
        """
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_activity_at = datetime.now(tz=timezone.utc)

    # ------------------------------------------------------------------
    # Idle hub process cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """Periodically kill idle hub-spawned processes."""
        interval = 30.0  # check every 30s
        while True:
            await asyncio.sleep(interval)
            try:
                await self._cleanup_idle_hub_processes()
            except Exception:
                logger.debug("Cleanup loop error", exc_info=True)

    async def _cleanup_idle_hub_processes(self) -> None:
        if self._process_registry is None:
            return

        now = datetime.now(tz=timezone.utc)

        async with self._lock:
            for sid, session in list(self._sessions.items()):
                if session.process is None:
                    continue
                if session.process.category != ClaudeProcessCategory.hub:
                    continue
                if session.last_activity_at is None:
                    continue

                idle_ms = (now - session.last_activity_at).total_seconds() * 1000
                needs_attention = self.get_needs_attention(sid)

                if needs_attention:
                    timeout_ms = STOP_NOANSWER_PROCESS_MS
                else:
                    timeout_ms = STOP_IDLE_PROCESS_MS

                if timeout_ms <= 0:
                    continue  # 0 = never kill

                if idle_ms >= timeout_ms:
                    logger.info(
                        "Killing idle hub process for session %s "
                        "(idle %.0fs, attention=%s)",
                        sid[:8],
                        idle_ms / 1000,
                        needs_attention,
                    )
                    self._process_registry.terminate(sid)

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
        """Start the idle process cleanup loop."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("SessionManager started")

    async def stop(self) -> None:
        """Cancel any pending debounce tasks and the cleanup loop."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None
        for task in self._pending_broadcasts.values():
            task.cancel()
        self._pending_broadcasts.clear()
        logger.info("SessionManager stopped")
