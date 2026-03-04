"""Session monitor state models ported from Swift SessionMonitorState.swift."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field


# --- SessionStatus tagged union ---


class SessionStatusThinking(BaseModel, frozen=True):
    """Session is thinking."""

    kind: Literal["thinking"] = "thinking"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        return "Thinking"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "brain"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def color(self) -> str:
        return "purple"


class SessionStatusExecutingTool(BaseModel, frozen=True):
    """Session is executing a tool."""

    kind: Literal["executing_tool"] = "executing_tool"
    name: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        return f"Running {self.name}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "hammer"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def color(self) -> str:
        return "blue"


class SessionStatusWaitingForUser(BaseModel, frozen=True):
    """Session is waiting for user input."""

    kind: Literal["waiting_for_user"] = "waiting_for_user"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        return "Waiting for user"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "person"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def color(self) -> str:
        return "orange"


class SessionStatusAwaitingApproval(BaseModel, frozen=True):
    """Session is awaiting tool approval."""

    kind: Literal["awaiting_approval"] = "awaiting_approval"
    tool: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        return f"Approve {self.tool}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "checkmark.shield"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def color(self) -> str:
        return "yellow"


class SessionStatusAwaitingQuestion(BaseModel, frozen=True):
    """Session is awaiting an answer to AskUserQuestion."""

    kind: Literal["awaiting_question"] = "awaiting_question"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        return "Answer question"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "questionmark.circle"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def color(self) -> str:
        return "orange"


class SessionStatusIdle(BaseModel, frozen=True):
    """Session is idle."""

    kind: Literal["idle"] = "idle"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        return "Idle"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "moon"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def color(self) -> str:
        return "gray"


SessionStatus = Annotated[
    SessionStatusThinking
    | SessionStatusExecutingTool
    | SessionStatusWaitingForUser
    | SessionStatusAwaitingApproval
    | SessionStatusAwaitingQuestion
    | SessionStatusIdle,
    Field(discriminator="kind"),
]


# --- ActivityType tagged union ---


class ActivityTypeToolUse(BaseModel, frozen=True):
    """Tool use activity."""

    kind: Literal["tool_use"] = "tool_use"
    name: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "hammer"


class ActivityTypeToolResult(BaseModel, frozen=True):
    """Tool result activity."""

    kind: Literal["tool_result"] = "tool_result"
    name: str
    success: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "checkmark.circle" if self.success else "xmark.circle"


class ActivityTypeUserMessage(BaseModel, frozen=True):
    """User message activity."""

    kind: Literal["user_message"] = "user_message"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "person"


class ActivityTypeAssistantMessage(BaseModel, frozen=True):
    """Assistant message activity."""

    kind: Literal["assistant_message"] = "assistant_message"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "sparkles"


class ActivityTypeThinking(BaseModel, frozen=True):
    """Thinking activity."""

    kind: Literal["thinking"] = "thinking"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "brain"


ActivityType = Annotated[
    ActivityTypeToolUse
    | ActivityTypeToolResult
    | ActivityTypeUserMessage
    | ActivityTypeAssistantMessage
    | ActivityTypeThinking,
    Field(discriminator="kind"),
]


# --- CodeChangeInput ---


class CodeChangeToolType(StrEnum):
    """Type of code change tool."""

    edit = "edit"
    write = "write"
    multi_edit = "multi_edit"


class EditEntry(BaseModel, frozen=True):
    """A single edit within a multi-edit operation."""

    old_string: str = ""
    new_string: str = ""


class CodeChangeInput(BaseModel, frozen=True):
    """Input for a code change operation."""

    tool_type: CodeChangeToolType
    file_path: str
    old_string: str = ""
    new_string: str = ""
    replace_all: bool = False
    edits: list[EditEntry] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_name(self) -> str:
        """Extract file name from file_path."""
        return PurePosixPath(self.file_path).name

    def to_tool_parameters(self) -> dict[str, str | bool | list[dict[str, str]]]:
        """Convert to tool parameter dictionary."""
        params: dict[str, str | bool | list[dict[str, str]]] = {
            "file_path": self.file_path,
        }
        if self.tool_type == CodeChangeToolType.edit:
            params["old_string"] = self.old_string
            params["new_string"] = self.new_string
            if self.replace_all:
                params["replace_all"] = self.replace_all
        elif self.tool_type == CodeChangeToolType.write:
            params["new_string"] = self.new_string
        elif self.tool_type == CodeChangeToolType.multi_edit:
            params["edits"] = [
                {"old_string": e.old_string, "new_string": e.new_string}
                for e in self.edits
            ]
        return params


# --- PendingToolUse ---


class PendingToolUse(BaseModel, frozen=True):
    """A tool use that is pending approval."""

    tool_name: str
    tool_use_id: str
    timestamp: datetime
    input_str: str = ""
    code_change_input: CodeChangeInput | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pending_duration(self) -> float:
        """Duration in seconds since the tool use was created."""
        now = datetime.now(tz=timezone.utc)
        return (now - self.timestamp).total_seconds()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_likely_awaiting_approval(self) -> bool:
        """Whether this tool use has been pending for more than 2 seconds."""
        return self.pending_duration > 2.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_code_change_tool(self) -> bool:
        """Whether this is a code change tool."""
        return self.code_change_input is not None


# --- ActivityEntry ---


class ActivityEntry(BaseModel, frozen=True):
    """An entry in the session activity log."""

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime
    type: ActivityType
    description: str = ""
    tool_input: CodeChangeInput | None = None


# --- ConsolidatedFileChange ---


class FileOperation(BaseModel, frozen=True):
    """A single file operation."""

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime
    input: CodeChangeInput


class ConsolidatedFileChange(BaseModel, frozen=True):
    """Consolidated changes to a single file."""

    id: UUID = Field(default_factory=uuid4)
    file_path: str
    operations: list[FileOperation] = Field(default_factory=list)
    first_timestamp: datetime
    last_timestamp: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_name(self) -> str:
        """Extract file name from file_path."""
        return PurePosixPath(self.file_path).name

    @computed_field  # type: ignore[prop-decorator]
    @property
    def operation_count(self) -> int:
        """Number of operations on this file."""
        return len(self.operations)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def operation_summary(self) -> str:
        """Summary of operations performed."""
        count = self.operation_count
        if count == 1:
            return "1 change"
        return f"{count} changes"


# --- CostBreakdown and CostCalculator ---


class PlanInfo(BaseModel, frozen=True):
    """A detected plan file and its content."""

    file_path: str
    content: str
    timestamp: str = ""


class MermaidDiagramInfo(BaseModel, frozen=True):
    """A detected mermaid diagram with its source."""

    source: str
    file_path: str = ""
    timestamp: str = ""


class CostBreakdown(BaseModel, frozen=True):
    """Breakdown of API costs."""

    input_cost: float
    output_cost: float
    cache_read_cost: float
    cache_creation_cost: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_cost(self) -> float:
        """Total cost across all components."""
        return (
            self.input_cost
            + self.output_cost
            + self.cache_read_cost
            + self.cache_creation_cost
        )


class _ModelPricing(BaseModel, frozen=True):
    """Pricing per million tokens for a model."""

    input: float
    output: float
    cache_read: float
    cache_creation: float


class CostCalculator:
    """Calculator for API costs based on model and token counts."""

    _PRICING: dict[str, _ModelPricing] = {
        "opus": _ModelPricing(
            input=15.0,
            output=75.0,
            cache_read=1.50,
            cache_creation=18.75,
        ),
        "sonnet": _ModelPricing(
            input=3.0,
            output=15.0,
            cache_read=0.30,
            cache_creation=3.75,
        ),
        "haiku": _ModelPricing(
            input=0.25,
            output=1.25,
            cache_read=0.025,
            cache_creation=0.30,
        ),
    }

    @staticmethod
    def calculate(
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
    ) -> CostBreakdown:
        """Calculate cost breakdown for a given model and token counts."""
        model_lower = model.lower()
        pricing: _ModelPricing | None = None
        for key, p in CostCalculator._PRICING.items():
            if key in model_lower:
                pricing = p
                break

        if pricing is None:
            # Default to sonnet pricing for unknown models
            pricing = CostCalculator._PRICING["sonnet"]

        per_million = 1_000_000.0
        return CostBreakdown(
            input_cost=input_tokens * pricing.input / per_million,
            output_cost=output_tokens * pricing.output / per_million,
            cache_read_cost=cache_read_tokens * pricing.cache_read / per_million,
            cache_creation_cost=cache_creation_tokens
            * pricing.cache_creation
            / per_million,
        )


# --- SessionMonitorState (mutable) ---


class SessionMonitorState(BaseModel, frozen=False):
    """Mutable state for a monitored session."""

    status: SessionStatus = Field(default_factory=lambda: SessionStatusIdle())
    current_tool: str = ""
    last_activity_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    input_tokens: int = 0
    output_tokens: int = 0
    total_output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    message_count: int = 0
    tool_calls: dict[str, int] = Field(default_factory=dict)
    session_started_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    model: str = ""
    git_branch: str = ""

    pending_tool_use: PendingToolUse | None = None

    recent_activities: list[ActivityEntry] = Field(default_factory=list)
    has_mermaid_content: bool = False
    plan_file_path: str = ""
    plan_content: str = ""
    plans: list[PlanInfo] = Field(default_factory=list)
    mermaid_diagrams: list[MermaidDiagramInfo] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output + cache)."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def session_duration(self) -> float:
        """Session duration in seconds."""
        now = datetime.now(tz=timezone.utc)
        return (now - self.session_started_at).total_seconds()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_awaiting_approval(self) -> bool:
        """Whether the session is awaiting tool approval."""
        if self.pending_tool_use is not None:
            return self.pending_tool_use.is_likely_awaiting_approval
        return False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def context_window_size(self) -> int:
        """Maximum context window size."""
        return 200_000

    @computed_field  # type: ignore[prop-decorator]
    @property
    def context_window_usage_percentage(self) -> float:
        """Percentage of context window used."""
        if self.context_window_size == 0:
            return 0.0
        return (self.total_tokens / self.context_window_size) * 100.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def formatted_context_usage(self) -> str:
        """Formatted string showing context usage."""
        used = self.format_token_count(self.total_tokens)
        total = self.format_token_count(self.context_window_size)
        return f"{used} / {total} ({self.context_window_usage_percentage:.1f}%)"

    @staticmethod
    def format_token_count(count: int) -> str:
        """Format a token count for display."""
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)
