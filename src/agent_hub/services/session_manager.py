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

from pathlib import Path

from agent_hub.config.defaults import STOP_IDLE_PROCESS_MS, STOP_NOANSWER_PROCESS_MS
from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.process_info import ClaudeProcessCategory, ClaudeProcessInfo
from agent_hub.models.session import CLISession

if TYPE_CHECKING:
    from agent_hub.services.claude_process_tracker import ClaudeProcessTracker
    from agent_hub.services.process_registry import ProcessRegistry
    from agent_hub.services.transcript_registry import TranscriptRegistry

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

    # -- Monitoring flags --
    # manual_monitoring: set by WS subscribe, cleared by WS unsubscribe
    manual_monitoring: bool = False
    # auto_monitoring: set when terminal-connected OR
    #   (has pending attention AND process is alive)
    auto_monitoring: bool = False

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
    def should_monitor(self) -> bool:
        """Whether transcript monitoring should be active.

        True when *either* manual or auto monitoring is on.
        """
        return self.manual_monitoring or self.auto_monitoring

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
        self._repositories: set[str] = set()
        self._claude_registry: TranscriptRegistry | None = None
        self._codex_registry: TranscriptRegistry | None = None
        self._claude_data_path: str = "~/.claude"

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
                session = self._sessions.get(sid)
                if session is not None:
                    self._recompute_auto_monitoring(session)
                self._schedule_notify(sid)

    async def handle_attention_changed(self, session_id: str) -> None:
        """Called when the tracker fires an attention or attention-resolved callback.

        We don't store any attention data — just trigger a broadcast so
        the WS handler can query the tracker for the current state.
        Also recomputes auto_monitoring (attention may require watching).
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_activity_at = datetime.now(tz=timezone.utc)
                self._recompute_auto_monitoring(session)
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

            # Refresh metadata from transcript (slug/first_message may
            # not have been available during the initial parse)
            self._refresh_session_metadata(session)

            self._schedule_notify(session_id)

    def _refresh_session_metadata(self, session: Session) -> None:
        """Pull slug, first_message, branch_name from the transcript if available."""
        registry = self._registry_for_session(session)
        if registry is None:
            return
        transcript = registry.get_transcript(session.session_id)
        if transcript is None:
            return
        slug = getattr(transcript, "slug", "")
        if slug and not session.slug:
            session.slug = slug
        first_msg = getattr(transcript, "first_message", "")
        if first_msg and not session.first_message:
            session.first_message = first_msg
        branch = getattr(transcript.parse_result, "git_branch", "")
        if branch and not session.branch_name:
            session.branch_name = branch

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
            self._recompute_auto_monitoring(session)
            self._schedule_notify(session_id)

    async def handle_terminal_unregistered(self, session_id: str) -> None:
        """Called after terminal terminate. Triggers a broadcast."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            self._recompute_auto_monitoring(session)
            self._schedule_notify(session_id)

    async def handle_transcript_added(
        self, session_id: str, transcript: object
    ) -> None:
        """Called by TranscriptRegistry when a new transcript is confirmed.

        Creates a Session if one doesn't exist, populates file_path,
        project_path, and metadata (slug, first_message, branch_name)
        from the transcript.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(session_id=session_id)
                self._sessions[session_id] = session
            session.session_file_path = getattr(transcript, "file_path", session.session_file_path)
            project_path = getattr(transcript, "project_path", session.project_path)
            session.project_path = project_path
            session.provider = getattr(transcript, "provider", session.provider)

            # Auto-track the repository
            if project_path:
                self._repositories.add(project_path)

            # Populate metadata from transcript parse result
            slug = getattr(transcript, "slug", "")
            if slug:
                session.slug = slug
            first_msg = getattr(transcript, "first_message", "")
            if first_msg:
                session.first_message = first_msg
            branch = ""
            pr = getattr(transcript, "parse_result", None)
            if pr is not None:
                branch = getattr(pr, "git_branch", "")
            if branch:
                session.branch_name = branch

            self._schedule_notify(session_id)

    async def handle_transcript_removed(self, session_id: str) -> None:
        """Called by TranscriptRegistry when a transcript file is deleted."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            # Only remove if no live process
            if session.process is None:
                self._sessions.pop(session_id, None)
            else:
                session.monitor_state = None
                session.manual_monitoring = False
                session.auto_monitoring = False
            self._schedule_notify(session_id)

    # ------------------------------------------------------------------
    # Repository management
    # ------------------------------------------------------------------

    def get_repositories(self) -> list[str]:
        """Return all watched repository paths."""
        return sorted(self._repositories)

    async def add_repository(self, path: str, provider: str = "claude") -> bool:
        """Add a repository path and register its project directory with the registry.

        Returns True if newly added, False if already tracked.
        """
        resolved = str(Path(path).resolve())
        if resolved in self._repositories:
            return False
        self._repositories.add(resolved)

        # Register the corresponding Claude/Codex project directory
        registry = self._claude_registry if provider == "claude" else self._codex_registry
        if registry is not None:
            if provider == "claude":
                from agent_hub.services.path_utils import encode_project_path, get_claude_projects_dir
                projects_dir = get_claude_projects_dir(self._claude_data_path)
                encoded = encode_project_path(resolved)
                project_dir = projects_dir / encoded
                if project_dir.is_dir():
                    await registry.add_project_directory(str(project_dir))
        return True

    async def remove_repository(self, path: str, provider: str = "claude") -> None:
        """Remove a repository path and unregister its project directory."""
        resolved = str(Path(path).resolve())
        self._repositories.discard(resolved)

        registry = self._claude_registry if provider == "claude" else self._codex_registry
        if registry is not None and provider == "claude":
            from agent_hub.services.path_utils import encode_project_path, get_claude_projects_dir
            projects_dir = get_claude_projects_dir(self._claude_data_path)
            encoded = encode_project_path(resolved)
            project_dir = projects_dir / encoded
            registry.remove_project_directory(str(project_dir))

    # ------------------------------------------------------------------
    # Session listing (replaces CLISessionMonitorService)
    # ------------------------------------------------------------------

    def get_all_cli_sessions(self) -> list[CLISession]:
        """Build a CLISession list from all known sessions.

        This replaces the monitor's ``_collect_all_sessions`` helper and
        the ``SelectedRepository → WorktreeBranch → CLISession`` tree.
        """
        now = datetime.now(tz=timezone.utc)
        sessions: list[CLISession] = []
        for s in self._sessions.values():
            sessions.append(CLISession(
                id=s.session_id,
                project_path=s.project_path,
                branch_name=s.branch_name,
                last_activity_at=s.last_activity_at or now,
                first_message=s.first_message,
                slug=s.slug,
                session_file_path=s.session_file_path,
            ))
        sessions.sort(key=lambda s: s.last_activity_at, reverse=True)
        return sessions

    def find_cli_session(self, session_id: str) -> tuple[CLISession | None, str]:
        """Find a single CLISession by ID. Returns (session, provider)."""
        now = datetime.now(tz=timezone.utc)
        s = self._sessions.get(session_id)
        if s is None:
            return None, ""
        cli = CLISession(
            id=s.session_id,
            project_path=s.project_path,
            branch_name=s.branch_name,
            last_activity_at=s.last_activity_at or now,
            first_message=s.first_message,
            slug=s.slug,
            session_file_path=s.session_file_path,
        )
        return cli, s.provider

    # ------------------------------------------------------------------
    # Tracker reference (set during wiring)
    # ------------------------------------------------------------------

    _tracker: ClaudeProcessTracker | None = None

    def set_tracker(self, tracker: ClaudeProcessTracker) -> None:
        self._tracker = tracker

    def set_process_registry(self, registry: ProcessRegistry) -> None:
        self._process_registry = registry
        registry.set_activity_callback(self.handle_terminal_activity)

    def set_transcript_registry(
        self,
        claude_registry: TranscriptRegistry | None = None,
        codex_registry: TranscriptRegistry | None = None,
        claude_data_path: str = "~/.claude",
    ) -> None:
        """Inject transcript registries.  Called during wiring."""
        if claude_registry is not None:
            self._claude_registry = claude_registry
        if codex_registry is not None:
            self._codex_registry = codex_registry
        self._claude_data_path = claude_data_path

    def _registry_for_session(self, session: Session) -> TranscriptRegistry | None:
        if session.provider == "codex":
            return self._codex_registry
        return self._claude_registry

    # ------------------------------------------------------------------
    # Monitoring state management
    # ------------------------------------------------------------------

    def _update_monitoring(self, session: Session) -> None:
        """Reconcile monitoring state with the transcript registry.

        Called after any change to manual_monitoring, auto_monitoring,
        or process state.
        """
        registry = self._registry_for_session(session)
        if registry is None:
            return
        registry.set_monitored(session.session_id, session.should_monitor)

    def _recompute_auto_monitoring(self, session: Session) -> None:
        """Recompute auto_monitoring based on current state.

        auto_monitoring is True when:
        - terminal is connected, OR
        - session has pending attention AND process is alive
        """
        terminal_connected = (
            session.process is not None
            and session.process.terminal_connected
        )
        has_attention = (
            self._tracker is not None
            and session.is_running
            and len(self._tracker.get_pending_attention_for_session(session.session_id)) > 0
        )
        old = session.auto_monitoring
        session.auto_monitoring = terminal_connected or has_attention
        if session.auto_monitoring != old:
            self._update_monitoring(session)

    async def set_manual_monitoring(self, session_id: str, enabled: bool) -> None:
        """Called by WS subscribe/unsubscribe to toggle manual monitoring."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            if session.manual_monitoring == enabled:
                return
            session.manual_monitoring = enabled
            self._update_monitoring(session)

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
