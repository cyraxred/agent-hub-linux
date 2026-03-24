"""SessionTranscript — owns parsing state for a single conversation file.

Extracted from ``SessionFileWatcher._WatchedSession`` and
``SessionFileWatcher._read_new_content()``.  Provider-agnostic: accepts a
``parse_fn`` callable that implements the provider's ``parse_new_lines()``.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent_hub.config.defaults import SESSION_ACTIVE_THRESHOLD, STATUS_TIMER_INTERVAL
from agent_hub.models.monitor_state import (
    MermaidDiagramInfo,
    PlanInfo,
    SessionMonitorState,
    SessionStatusIdle,
)

logger = logging.getLogger(__name__)

# Type alias for the provider-specific parser function.
# Signature: parse_fn(lines: list[str], result: Any, approval_timeout: int) -> None
ParseFn = Callable[[list[str], Any, int], None]


class SessionTranscript:
    """Owns byte-offset incremental parsing for one conversation file.

    Fires callbacks on state change, history append, and tool_result
    resolution (for attention tracking).
    """

    def __init__(
        self,
        session_id: str,
        file_path: str,
        project_path: str,
        parse_fn: ParseFn,
        parse_result_factory: Callable[[], Any],
        provider: str = "claude",
        approval_timeout_seconds: int = 5,
        parse_cache: Any | None = None,
    ) -> None:
        self.session_id = session_id
        self.file_path = file_path
        self.project_path = project_path
        self.provider = provider

        self._parse_fn = parse_fn
        self._approval_timeout_seconds = approval_timeout_seconds
        self._parse_cache = parse_cache

        # Parsing state
        self.byte_offset: int = 0
        self.line_count: int = 0
        self.parse_result: Any = parse_result_factory()
        self.state: SessionMonitorState = SessionMonitorState()
        self.last_file_check: float = 0.0

        # Monitoring state (controlled by TranscriptRegistry)
        self.is_monitored: bool = False

        # Callbacks
        self._state_callbacks: list[Callable] = []
        self._history_callbacks: list[Callable] = []
        self._tool_result_callbacks: list[Callable] = []

    @property
    def first_message(self) -> str:
        """First user message text, extracted by the parser."""
        return getattr(self.parse_result, "first_user_message", "")

    @property
    def slug(self) -> str:
        """Session slug, extracted by the parser."""
        return getattr(self.parse_result, "slug", "")

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_state_update(self, callback: Callable) -> None:
        """Register: ``async def cb(session_id, state) -> None``"""
        self._state_callbacks.append(callback)

    def on_history_append(self, callback: Callable) -> None:
        """Register: ``async def cb(session_id, entries, total_lines) -> None``"""
        self._history_callbacks.append(callback)

    def on_tool_result(self, callback: Callable) -> None:
        """Register: ``async def cb(session_id, tool_use_id) -> None``"""
        self._tool_result_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Core: file-change notification
    # ------------------------------------------------------------------

    async def notify_file_modified(self) -> None:
        """Called when the underlying file has been modified.

        Reads the delta since ``byte_offset``, parses via the provider's
        ``parse_fn``, updates state, and fires callbacks.
        """
        path = Path(self.file_path)
        if not path.is_file():
            return

        try:
            file_size = path.stat().st_size

            # Handle truncation (file was rewritten)
            if file_size < self.byte_offset:
                self.byte_offset = 0
                self.line_count = 0
                self.parse_result = self.parse_result.__class__()

            if file_size <= self.byte_offset:
                return

            loop = asyncio.get_event_loop()
            new_data = await loop.run_in_executor(
                None, _read_bytes, self.file_path, self.byte_offset
            )
            if not new_data:
                return

            self.byte_offset += len(new_data)
            lines = new_data.decode("utf-8", errors="replace").splitlines()

            # Snapshot pending tool_use_ids before parsing (for Claude provider)
            pending_before: set[str] = set()
            if hasattr(self.parse_result, "pending_tool_uses"):
                pending_before = set(self.parse_result.pending_tool_uses.keys())

            # Parse
            self._parse_fn(lines, self.parse_result, self._approval_timeout_seconds)

            # Detect resolved tool_use_ids
            resolved_ids: set[str] = set()
            if hasattr(self.parse_result, "pending_tool_uses"):
                pending_after = set(self.parse_result.pending_tool_uses.keys())
                resolved_ids = pending_before - pending_after

            # Build raw history entries
            new_entries: list[dict[str, object]] = []
            for raw_line in lines:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    data = _json.loads(raw_line)
                    if isinstance(data, dict):
                        self.line_count += 1
                        new_entries.append(
                            {
                                "line": self.line_count,
                                "type": str(data.get("type", "")),
                                "data": data,
                            }
                        )
                except (ValueError, _json.JSONDecodeError):
                    continue

            # Update state from parse result
            _update_state_from_parse(self.state, self.parse_result)

            # Fire callbacks
            await self._notify_state_update()
            if new_entries:
                await self._notify_history_append(new_entries)
            if resolved_ids and self._tool_result_callbacks:
                await self._notify_tool_results(resolved_ids)

            # Write-through to parse cache
            if self._parse_cache is not None:
                self._parse_cache.put(
                    session_id=self.session_id,
                    file_path=self.file_path,
                    file_size=self.byte_offset,
                    parse_result=self.parse_result,
                    provider=self.provider,
                )

        except OSError:
            logger.exception("Error reading session file: %s", self.file_path)

    async def do_initial_parse(self) -> None:
        """Perform the initial parse (read from offset 0 or current offset)."""
        await self.notify_file_modified()

    async def refresh(self) -> None:
        """Force a full re-parse from the beginning."""
        self.byte_offset = 0
        self.line_count = 0
        self.parse_result = self.parse_result.__class__()
        await self.notify_file_modified()

    # ------------------------------------------------------------------
    # Status timer check (called periodically by registry)
    # ------------------------------------------------------------------

    def check_status_timeout(self, now: datetime | None = None) -> bool:
        """Re-evaluate timeout-based status transitions.

        Returns True if state changed (caller should broadcast).
        """
        if now is None:
            now = datetime.now(tz=timezone.utc)

        if self.parse_result.recent_activities:
            last = self.parse_result.recent_activities[-1]
            elapsed = (now - last.timestamp).total_seconds()
            if elapsed > SESSION_ACTIVE_THRESHOLD:
                if self.state.status.kind != "idle":
                    self.state.status = SessionStatusIdle()
                    return True
        return False

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------

    async def _notify_state_update(self) -> None:
        for cb in self._state_callbacks:
            try:
                await cb(self.session_id, self.state)
            except Exception:
                logger.exception("Error in state update callback")

    async def _notify_history_append(self, entries: list[dict[str, object]]) -> None:
        for cb in self._history_callbacks:
            try:
                await cb(self.session_id, entries, self.line_count)
            except Exception:
                logger.exception("Error in history append callback")

    async def _notify_tool_results(self, resolved_ids: set[str]) -> None:
        for tool_use_id in resolved_ids:
            for cb in self._tool_result_callbacks:
                try:
                    await cb(self.session_id, tool_use_id)
                except Exception:
                    logger.exception("Error in tool_result callback")


# ---------------------------------------------------------------------------
# Helpers (module-level, reused from original watchers)
# ---------------------------------------------------------------------------


def _read_bytes(file_path: str, offset: int) -> bytes:
    """Read bytes from file starting at offset (runs in executor)."""
    with open(file_path, "rb") as f:
        f.seek(offset)
        return f.read()


def _update_state_from_parse(state: SessionMonitorState, pr: Any) -> None:
    """Update a SessionMonitorState from a ParseResult.

    Extracted from SessionFileWatcher._update_state_from_parse and
    CodexSessionFileWatcher._update_state_from_parse — identical logic.
    """
    state.model = pr.model
    state.input_tokens = pr.last_input_tokens
    state.output_tokens = pr.last_output_tokens
    state.total_output_tokens = pr.total_output_tokens
    state.cache_read_tokens = pr.cache_read_tokens
    state.cache_creation_tokens = pr.cache_creation_tokens
    state.message_count = pr.message_count
    state.tool_calls = dict(pr.tool_calls)
    state.recent_activities = list(pr.recent_activities)

    # git_branch is Claude-only but both ParseResults may have it
    if hasattr(pr, "git_branch"):
        state.git_branch = pr.git_branch

    # Mermaid / plan fields
    state.has_mermaid_content = pr.has_mermaid_content
    state.plan_file_path = pr.plan_file_path
    state.plan_content = pr.plan_content

    state.plans = [
        PlanInfo(
            file_path=p.file_path,
            content=p.content,
            timestamp=p.timestamp.isoformat(),
        )
        for p in pr.plans
    ]
    state.mermaid_diagrams = [
        MermaidDiagramInfo(
            source=d.source,
            file_path=d.file_path,
            timestamp=d.timestamp.isoformat(),
        )
        for d in pr.mermaid_diagrams
    ]

    if pr.session_started_at:
        state.session_started_at = pr.session_started_at
    if pr.last_activity_at:
        state.last_activity_at = pr.last_activity_at

    if pr.current_status is not None:
        state.status = pr.current_status.status
        state.pending_tool_use = pr.current_status.pending_tool_use
