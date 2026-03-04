"""Codex JSONL parser ported from Swift CodexSessionJSONLParser.swift."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent_hub.config.defaults import MAX_RECENT_ACTIVITIES
from agent_hub.models.monitor_state import (
    ActivityEntry,
    ActivityTypeAssistantMessage,
    ActivityTypeThinking,
    ActivityTypeToolResult,
    ActivityTypeToolUse,
    ActivityTypeUserMessage,
    PendingToolUse,
    SessionMonitorState,
    SessionStatusAwaitingApproval,
    SessionStatusExecutingTool,
    SessionStatusIdle,
    SessionStatusThinking,
    SessionStatusWaitingForUser,
)

logger = logging.getLogger(__name__)


@dataclass
class PendingToolInfo:
    """Tracks a pending tool use awaiting result."""

    tool_name: str
    tool_use_id: str
    timestamp: datetime


@dataclass
class GlobalStatsParseResult:
    """Result from parsing codex sessions for global stats."""

    model: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cache_read_tokens: int = 0
    message_count: int = 0


@dataclass
class PlanEntry:
    """A single detected plan write."""

    file_path: str
    content: str
    timestamp: datetime


@dataclass
class MermaidDiagram:
    """A single extracted mermaid diagram."""

    source: str
    origin_tool: str
    file_path: str
    timestamp: datetime


@dataclass
class ParseResult:
    """Accumulated result from parsing a Codex session JSONL file."""

    model: str = ""
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    message_count: int = 0
    tool_calls: dict[str, int] = field(default_factory=dict)
    pending_tool_uses: dict[str, PendingToolInfo] = field(default_factory=dict)
    recent_activities: list[ActivityEntry] = field(default_factory=list)
    last_activity_at: datetime | None = None
    session_started_at: datetime | None = None
    current_status: SessionMonitorState | None = None
    plans: list[PlanEntry] = field(default_factory=list)
    mermaid_diagrams: list[MermaidDiagram] = field(default_factory=list)

    @property
    def plan_file_path(self) -> str:
        """Latest plan file path (backward compat)."""
        return self.plans[-1].file_path if self.plans else ""

    @property
    def plan_content(self) -> str:
        """Latest plan content (backward compat)."""
        return self.plans[-1].content if self.plans else ""

    @property
    def has_mermaid_content(self) -> bool:
        """Whether any mermaid diagrams were found (backward compat)."""
        return len(self.mermaid_diagrams) > 0


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO 8601 timestamp string."""
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(tz=timezone.utc)


def _add_activity(result: ParseResult, activity: ActivityEntry) -> None:
    """Add an activity entry, keeping the list capped."""
    result.recent_activities.append(activity)
    if len(result.recent_activities) > MAX_RECENT_ACTIVITIES:
        result.recent_activities = result.recent_activities[-MAX_RECENT_ACTIVITIES:]


def parse_new_lines(
    lines: list[str],
    result: ParseResult,
    approval_timeout_seconds: int = 0,
) -> None:
    """Parse new JSONL lines into an existing ParseResult (Codex format)."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(entry, dict):
            continue

        entry_type = str(entry.get("type", ""))
        timestamp_str = str(entry.get("timestamp", ""))
        ts = _parse_timestamp(timestamp_str) if timestamp_str else datetime.now(tz=timezone.utc)

        if result.session_started_at is None:
            result.session_started_at = ts
        result.last_activity_at = ts

        message = entry.get("message")
        if not isinstance(message, dict):
            continue

        role = str(message.get("role", ""))
        model_val = message.get("model")
        if isinstance(model_val, str) and model_val:
            result.model = model_val

        # Usage tracking
        usage = message.get("usage")
        if isinstance(usage, dict):
            input_t = usage.get("input_tokens") or usage.get("inputTokens")
            output_t = usage.get("output_tokens") or usage.get("outputTokens")
            cache_read_t = usage.get("cache_read_input_tokens") or usage.get("cacheReadInputTokens")
            cache_create_t = (
                usage.get("cache_creation_input_tokens")
                or usage.get("cacheCreationInputTokens")
            )

            if isinstance(input_t, int):
                result.last_input_tokens = input_t
                result.total_input_tokens += input_t
            if isinstance(output_t, int):
                result.last_output_tokens = output_t
                result.total_output_tokens += output_t
            if isinstance(cache_read_t, int):
                result.cache_read_tokens += cache_read_t
            if isinstance(cache_create_t, int):
                result.cache_creation_tokens += cache_create_t

        content = message.get("content")
        if not isinstance(content, list):
            if role == "user":
                result.message_count += 1
                _add_activity(
                    result,
                    ActivityEntry(
                        timestamp=ts,
                        type=ActivityTypeUserMessage(),
                        description="User message",
                    ),
                )
            elif role == "assistant":
                _add_activity(
                    result,
                    ActivityEntry(
                        timestamp=ts,
                        type=ActivityTypeAssistantMessage(),
                        description="Assistant response",
                    ),
                )
            continue

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = str(block.get("type", ""))

            if block_type == "tool_use":
                tool_name = str(block.get("name", "unknown"))
                tool_id = str(block.get("id", ""))
                result.tool_calls[tool_name] = result.tool_calls.get(tool_name, 0) + 1

                result.pending_tool_uses[tool_id] = PendingToolInfo(
                    tool_name=tool_name,
                    tool_use_id=tool_id,
                    timestamp=ts,
                )

                _add_activity(
                    result,
                    ActivityEntry(
                        timestamp=ts,
                        type=ActivityTypeToolUse(name=tool_name),
                        description=f"Using {tool_name}",
                    ),
                )

            elif block_type == "tool_result":
                tool_use_id = str(block.get("tool_use_id", ""))
                is_error = bool(block.get("is_error", False))
                pending = result.pending_tool_uses.pop(tool_use_id, None)
                tool_name = pending.tool_name if pending else "unknown"

                _add_activity(
                    result,
                    ActivityEntry(
                        timestamp=ts,
                        type=ActivityTypeToolResult(name=tool_name, success=not is_error),
                        description=f"{tool_name} {'failed' if is_error else 'completed'}",
                    ),
                )

            elif block_type == "thinking":
                _add_activity(
                    result,
                    ActivityEntry(
                        timestamp=ts,
                        type=ActivityTypeThinking(),
                        description="Thinking...",
                    ),
                )

        if role == "user":
            result.message_count += 1
        elif role == "assistant":
            pass

    update_current_status(result, approval_timeout_seconds)


def update_current_status(result: ParseResult, approval_timeout_seconds: int = 0) -> None:
    """Update the current session status based on recent activities."""
    if not result.recent_activities:
        return

    if result.pending_tool_uses and approval_timeout_seconds > 0:
        now = datetime.now(tz=timezone.utc)
        for pending in result.pending_tool_uses.values():
            elapsed = (now - pending.timestamp).total_seconds()
            if elapsed >= approval_timeout_seconds:
                result.current_status = SessionMonitorState(
                    status=SessionStatusAwaitingApproval(tool=pending.tool_name),
                    pending_tool_use=PendingToolUse(
                        tool_name=pending.tool_name,
                        tool_use_id=pending.tool_use_id,
                        timestamp=pending.timestamp,
                    ),
                )
                return

    last = result.recent_activities[-1]
    now = datetime.now(tz=timezone.utc)
    elapsed = (now - last.timestamp).total_seconds()

    if last.type.kind == "tool_use":
        name = last.type.name if hasattr(last.type, "name") else "unknown"
        status_obj = (
            SessionStatusExecutingTool(name=name) if elapsed < 60 else SessionStatusIdle()
        )
    elif last.type.kind == "tool_result":
        status_obj = SessionStatusThinking() if elapsed < 60 else SessionStatusIdle()
    elif last.type.kind == "assistant_message":
        status_obj = SessionStatusWaitingForUser()
    elif last.type.kind == "user_message":
        status_obj = SessionStatusThinking() if elapsed < 60 else SessionStatusIdle()
    elif last.type.kind == "thinking":
        status_obj = SessionStatusThinking() if elapsed < 30 else SessionStatusIdle()
    else:
        status_obj = SessionStatusIdle()

    if result.current_status is None:
        result.current_status = SessionMonitorState(status=status_obj)


def parse_session_file(path: str, approval_timeout_seconds: int = 0) -> ParseResult:
    """Parse an entire Codex session JSONL file."""
    result = ParseResult()
    file_path = Path(path)

    if not file_path.is_file():
        return result

    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        logger.exception("Failed to read Codex session file: %s", path)
        return result

    parse_new_lines(lines, result, approval_timeout_seconds)
    return result


def parse_for_global_stats(path: str) -> GlobalStatsParseResult:
    """Parse a Codex session file for global stats only (lighter weight)."""
    result = GlobalStatsParseResult()
    file_path = Path(path)

    if not file_path.is_file():
        return result

    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(entry, dict):
                    continue

                message = entry.get("message")
                if not isinstance(message, dict):
                    continue

                role = str(message.get("role", ""))
                model_val = message.get("model")
                if isinstance(model_val, str) and model_val:
                    result.model = model_val

                if role == "user":
                    result.message_count += 1

                usage = message.get("usage")
                if isinstance(usage, dict):
                    input_t = usage.get("input_tokens") or usage.get("inputTokens")
                    output_t = usage.get("output_tokens") or usage.get("outputTokens")
                    cache_read_t = (
                        usage.get("cache_read_input_tokens")
                        or usage.get("cacheReadInputTokens")
                    )
                    if isinstance(input_t, int):
                        result.total_input_tokens += input_t
                    if isinstance(output_t, int):
                        result.total_output_tokens += output_t
                    if isinstance(cache_read_t, int):
                        result.cache_read_tokens += cache_read_t

    except OSError:
        logger.exception("Failed to read Codex session for stats: %s", path)

    return result
