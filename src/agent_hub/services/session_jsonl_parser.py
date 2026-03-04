"""Claude JSONL parser ported from Swift SessionJSONLParser.swift.

Parses session JSONL files incrementally with byte-offset tracking.
"""

from __future__ import annotations

import json
import logging
import re
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
    CodeChangeInput,
    CodeChangeToolType,
    EditEntry,
    PendingToolUse,
    SessionMonitorState,
    SessionStatusAwaitingApproval,
    SessionStatusAwaitingQuestion,
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
    input_str: str = ""
    code_change_input: CodeChangeInput | None = None


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


_MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


def _extract_mermaid_blocks(
    result: ParseResult,
    text: str,
    origin_tool: str,
    file_path: str,
    ts: datetime,
) -> None:
    """Extract all ```mermaid blocks from text and append to result."""
    for m in _MERMAID_RE.finditer(text):
        source = m.group(1).strip()
        if source:
            result.mermaid_diagrams.append(
                MermaidDiagram(
                    source=source,
                    origin_tool=origin_tool,
                    file_path=file_path,
                    timestamp=ts,
                )
            )


@dataclass
class ParseResult:
    """Accumulated result from parsing a session JSONL file."""

    model: str = ""
    last_input_tokens: int = 0
    last_output_tokens: int = 0
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
    git_branch: str = ""
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


def _extract_code_change_input(
    tool_name: str, input_data: dict[str, object]
) -> CodeChangeInput | None:
    """Extract CodeChangeInput from tool input data."""
    name_lower = tool_name.lower()
    if name_lower in ("edit", "write", "multiedit", "multi_edit"):
        file_path = str(input_data.get("file_path", ""))
        if not file_path:
            return None

        if name_lower == "write":
            return CodeChangeInput(
                tool_type=CodeChangeToolType.write,
                file_path=file_path,
                new_string=str(input_data.get("content", input_data.get("new_string", ""))),
            )
        elif name_lower in ("multiedit", "multi_edit"):
            raw_edits = input_data.get("edits", [])
            edits: list[EditEntry] = []
            if isinstance(raw_edits, list):
                for e in raw_edits:
                    if isinstance(e, dict):
                        edits.append(
                            EditEntry(
                                old_string=str(e.get("old_string", "")),
                                new_string=str(e.get("new_string", "")),
                            )
                        )
            return CodeChangeInput(
                tool_type=CodeChangeToolType.multi_edit,
                file_path=file_path,
                edits=edits,
            )
        else:
            return CodeChangeInput(
                tool_type=CodeChangeToolType.edit,
                file_path=file_path,
                old_string=str(input_data.get("old_string", "")),
                new_string=str(input_data.get("new_string", "")),
                replace_all=bool(input_data.get("replace_all", False)),
            )
    return None


def _add_activity(result: ParseResult, activity: ActivityEntry) -> None:
    """Add an activity entry, keeping the list capped."""
    result.recent_activities.append(activity)
    if len(result.recent_activities) > MAX_RECENT_ACTIVITIES:
        result.recent_activities = result.recent_activities[-MAX_RECENT_ACTIVITIES:]


def parse_entry(line: str) -> dict[str, object] | None:
    """Parse a single JSONL line into a dictionary."""
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
        if isinstance(data, dict):
            return data  # type: ignore[return-value]
        return None
    except json.JSONDecodeError:
        return None


def parse_new_lines(
    lines: list[str],
    result: ParseResult,
    approval_timeout_seconds: int = 0,
) -> None:
    """Parse new JSONL lines into an existing ParseResult."""
    for line in lines:
        entry = parse_entry(line)
        if entry is None:
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
            input_t = usage.get("inputTokens") or usage.get("input_tokens")
            output_t = usage.get("outputTokens") or usage.get("output_tokens")
            cache_read_t = usage.get("cacheReadInputTokens") or usage.get("cache_read_input_tokens")
            cache_create_t = (
                usage.get("cacheCreationInputTokens")
                or usage.get("cache_creation_input_tokens")
            )

            if isinstance(input_t, int):
                result.last_input_tokens = input_t
            if isinstance(output_t, int):
                result.last_output_tokens = output_t
                result.total_output_tokens += output_t
            if isinstance(cache_read_t, int):
                result.cache_read_tokens = cache_read_t
            if isinstance(cache_create_t, int):
                result.cache_creation_tokens = cache_create_t

        content = message.get("content")
        if not isinstance(content, list):
            # Simple role-based tracking
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

        # Process content blocks
        has_user_text = False
        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = str(block.get("type", ""))

            if block_type == "tool_use":
                tool_name = str(block.get("name", "unknown"))
                tool_id = str(block.get("id", ""))
                result.tool_calls[tool_name] = result.tool_calls.get(tool_name, 0) + 1

                input_data = block.get("input")
                code_change: CodeChangeInput | None = None
                input_str = ""
                if isinstance(input_data, dict):
                    code_change = _extract_code_change_input(tool_name, input_data)
                    try:
                        input_str = json.dumps(input_data)
                    except (TypeError, ValueError):
                        input_str = str(input_data)

                result.pending_tool_uses[tool_id] = PendingToolInfo(
                    tool_name=tool_name,
                    tool_use_id=tool_id,
                    timestamp=ts,
                    input_str=input_str,
                    code_change_input=code_change,
                )

                _add_activity(
                    result,
                    ActivityEntry(
                        timestamp=ts,
                        type=ActivityTypeToolUse(name=tool_name),
                        description=f"Using {tool_name}",
                        tool_input=code_change,
                    ),
                )

                # Track plan file writes
                if code_change is not None and ".claude/plans/" in code_change.file_path:
                    result.plans.append(
                        PlanEntry(
                            file_path=code_change.file_path,
                            content=code_change.new_string,
                            timestamp=ts,
                        )
                    )

                # Extract mermaid diagrams
                if isinstance(input_data, dict):
                    content_val = str(input_data.get("content", ""))
                    if "```mermaid" in content_val:
                        _extract_mermaid_blocks(
                            result, content_val, tool_name,
                            code_change.file_path if code_change else "", ts,
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
                        type=ActivityTypeToolResult(
                            name=tool_name, success=not is_error
                        ),
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

            elif block_type == "text":
                text_val = str(block.get("text", ""))
                if role == "user" and text_val.strip():
                    has_user_text = True
                if "```mermaid" in text_val:
                    _extract_mermaid_blocks(result, text_val, "", "", ts)

        # Track role-level events — only count user messages that contain
        # actual text from the user (not tool-result-only turns).
        if role == "user" and has_user_text:
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

    update_current_status(result, approval_timeout_seconds)


def update_current_status(
    result: ParseResult, approval_timeout_seconds: int = 0
) -> None:
    """Update the current session status based on recent activities."""
    if not result.recent_activities:
        return

    # Check for pending tool uses that may be awaiting approval
    if result.pending_tool_uses and approval_timeout_seconds > 0:
        now = datetime.now(tz=timezone.utc)
        for pending in result.pending_tool_uses.values():
            elapsed = (now - pending.timestamp).total_seconds()
            if elapsed >= approval_timeout_seconds:
                is_question = pending.tool_name.lower() in (
                    "askuserquestion",
                    "ask_user_question",
                )
                status = (
                    SessionStatusAwaitingQuestion()
                    if is_question
                    else SessionStatusAwaitingApproval(tool=pending.tool_name)
                )
                result.current_status = SessionMonitorState(
                    status=status,
                    pending_tool_use=PendingToolUse(
                        tool_name=pending.tool_name,
                        tool_use_id=pending.tool_use_id,
                        timestamp=pending.timestamp,
                        input_str=pending.input_str,
                        code_change_input=pending.code_change_input,
                    ),
                )
                return

    # Determine status from last activity
    last = result.recent_activities[-1]
    now = datetime.now(tz=timezone.utc)
    elapsed = (now - last.timestamp).total_seconds()

    if last.type.kind == "tool_use":
        if elapsed < 60:
            name = last.type.name if hasattr(last.type, "name") else "unknown"
            # Status is executing_tool or awaiting_approval
            if result.pending_tool_uses:
                # Still has pending tools
                status_obj = SessionStatusExecutingTool(name=name)
            else:
                status_obj = SessionStatusExecutingTool(name=name)
        else:
            status_obj = SessionStatusIdle()
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

    # Always update the status (the awaiting_approval check above returns
    # early when it takes precedence, so at this point we always want to
    # reflect the latest activity).
    if result.current_status is None:
        result.current_status = SessionMonitorState(status=status_obj)
    else:
        result.current_status.status = status_obj


def parse_session_file(
    path: str, approval_timeout_seconds: int = 0
) -> ParseResult:
    """Parse an entire session JSONL file."""
    result = ParseResult()
    file_path = Path(path)

    if not file_path.is_file():
        return result

    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        logger.exception("Failed to read session file: %s", path)
        return result

    parse_new_lines(lines, result, approval_timeout_seconds)
    return result


def parse_session_head(path: str, max_bytes: int = 16384) -> dict[str, str]:
    """Read the first max_bytes of a session file to extract slug and git branch.

    Returns dict with 'slug' and 'git_branch' keys (may be empty).
    """
    import re

    info: dict[str, str] = {"slug": "", "git_branch": ""}
    file_path = Path(path)

    if not file_path.is_file():
        return info

    try:
        with open(file_path, "rb") as f:
            head = f.read(max_bytes)

        for line in head.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    continue

                # Check for top-level slug / gitBranch fields
                for key in ("slug", "sessionSlug", "session_slug"):
                    val = data.get(key)
                    if isinstance(val, str) and val and not info["slug"]:
                        info["slug"] = val

                for key in ("gitBranch", "git_branch", "branch"):
                    val = data.get(key)
                    if isinstance(val, str) and val and not info["git_branch"]:
                        info["git_branch"] = val

                msg = data.get("message")
                if not isinstance(msg, dict):
                    continue

                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "text":
                            continue
                        text = str(block.get("text", ""))

                        # Extract git branch from common patterns in
                        # system/initial context text
                        if not info["git_branch"]:
                            # "Current branch: main" or "on branch main"
                            m = re.search(
                                r"(?:current branch|on branch|branch)[:\s]+(\S+)",
                                text,
                                re.IGNORECASE,
                            )
                            if m:
                                info["git_branch"] = m.group(1).strip("'\"`).,")

                        if not info["git_branch"]:
                            # "gitBranch": "main" in JSON-like text
                            m = re.search(
                                r'"(?:gitBranch|git_branch)"\s*:\s*"([^"]+)"', text
                            )
                            if m:
                                info["git_branch"] = m.group(1)

                        # Extract slug from text if not already found
                        if not info["slug"]:
                            m = re.search(r'"slug"\s*:\s*"([^"]+)"', text)
                            if m:
                                info["slug"] = m.group(1)

                # Stop early if we have both values
                if info["slug"] and info["git_branch"]:
                    break

            except json.JSONDecodeError:
                continue
    except OSError:
        pass

    return info
