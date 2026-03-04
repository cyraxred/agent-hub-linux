"""Tests for agent_hub.models.monitor_state module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from agent_hub.models.monitor_state import (
    ActivityEntry,
    ActivityType,
    ActivityTypeAssistantMessage,
    ActivityTypeThinking,
    ActivityTypeToolResult,
    ActivityTypeToolUse,
    ActivityTypeUserMessage,
    CodeChangeInput,
    CodeChangeToolType,
    CostBreakdown,
    CostCalculator,
    EditEntry,
    PendingToolUse,
    SessionMonitorState,
    SessionStatus,
    SessionStatusAwaitingApproval,
    SessionStatusExecutingTool,
    SessionStatusIdle,
    SessionStatusThinking,
    SessionStatusWaitingForUser,
)


# ---------- SessionStatus ----------


class TestSessionStatus:
    """Tests for the SessionStatus discriminated union."""

    def test_thinking(self) -> None:
        s = SessionStatusThinking()
        assert s.kind == "thinking"
        assert s.display_name == "Thinking"
        assert s.icon == "brain"
        assert s.color == "purple"

    def test_executing_tool(self) -> None:
        s = SessionStatusExecutingTool(name="Bash")
        assert s.kind == "executing_tool"
        assert s.display_name == "Running Bash"
        assert s.icon == "hammer"
        assert s.color == "blue"

    def test_waiting_for_user(self) -> None:
        s = SessionStatusWaitingForUser()
        assert s.kind == "waiting_for_user"
        assert s.display_name == "Waiting for user"
        assert s.icon == "person"
        assert s.color == "orange"

    def test_awaiting_approval(self) -> None:
        s = SessionStatusAwaitingApproval(tool="Edit")
        assert s.kind == "awaiting_approval"
        assert s.display_name == "Approve Edit"
        assert s.icon == "checkmark.shield"
        assert s.color == "yellow"

    def test_idle(self) -> None:
        s = SessionStatusIdle()
        assert s.kind == "idle"
        assert s.display_name == "Idle"
        assert s.icon == "moon"
        assert s.color == "gray"

    def test_discriminated_union_roundtrip(self) -> None:
        adapter = TypeAdapter(SessionStatus)

        exec_tool = SessionStatusExecutingTool(name="Write")
        data = adapter.dump_python(exec_tool)
        restored = adapter.validate_python(data)
        assert restored.kind == "executing_tool"

        approval = SessionStatusAwaitingApproval(tool="Bash")
        data2 = adapter.dump_python(approval)
        restored2 = adapter.validate_python(data2)
        assert restored2.kind == "awaiting_approval"

    def test_all_variants(self) -> None:
        adapter = TypeAdapter(SessionStatus)
        variants = [
            {"kind": "thinking"},
            {"kind": "executing_tool", "name": "Bash"},
            {"kind": "waiting_for_user"},
            {"kind": "awaiting_approval", "tool": "Edit"},
            {"kind": "idle"},
        ]
        for v in variants:
            parsed = adapter.validate_python(v)
            assert parsed.kind == v["kind"]


# ---------- ActivityType ----------


class TestActivityType:
    """Tests for the ActivityType discriminated union."""

    def test_tool_use(self) -> None:
        a = ActivityTypeToolUse(name="Bash")
        assert a.kind == "tool_use"
        assert a.name == "Bash"
        assert a.icon == "hammer"

    def test_tool_result_success(self) -> None:
        a = ActivityTypeToolResult(name="Edit", success=True)
        assert a.kind == "tool_result"
        assert a.icon == "checkmark.circle"

    def test_tool_result_failure(self) -> None:
        a = ActivityTypeToolResult(name="Edit", success=False)
        assert a.icon == "xmark.circle"

    def test_user_message(self) -> None:
        a = ActivityTypeUserMessage()
        assert a.kind == "user_message"
        assert a.icon == "person"

    def test_assistant_message(self) -> None:
        a = ActivityTypeAssistantMessage()
        assert a.kind == "assistant_message"
        assert a.icon == "sparkles"

    def test_thinking(self) -> None:
        a = ActivityTypeThinking()
        assert a.kind == "thinking"
        assert a.icon == "brain"

    def test_discriminated_union(self) -> None:
        adapter = TypeAdapter(ActivityType)
        variants = [
            {"kind": "tool_use", "name": "Bash"},
            {"kind": "tool_result", "name": "Edit", "success": True},
            {"kind": "user_message"},
            {"kind": "assistant_message"},
            {"kind": "thinking"},
        ]
        for v in variants:
            parsed = adapter.validate_python(v)
            assert parsed.kind == v["kind"]


# ---------- CodeChangeInput ----------


class TestCodeChangeInput:
    """Tests for CodeChangeInput model and to_tool_parameters()."""

    def test_edit_to_tool_parameters(self) -> None:
        cci = CodeChangeInput(
            tool_type=CodeChangeToolType.edit,
            file_path="/src/main.py",
            old_string="hello",
            new_string="world",
            replace_all=False,
        )
        params = cci.to_tool_parameters()
        assert params["file_path"] == "/src/main.py"
        assert params["old_string"] == "hello"
        assert params["new_string"] == "world"
        assert "replace_all" not in params  # only set when True

    def test_edit_replace_all(self) -> None:
        cci = CodeChangeInput(
            tool_type=CodeChangeToolType.edit,
            file_path="/src/main.py",
            old_string="a",
            new_string="b",
            replace_all=True,
        )
        params = cci.to_tool_parameters()
        assert params["replace_all"] is True

    def test_write_to_tool_parameters(self) -> None:
        cci = CodeChangeInput(
            tool_type=CodeChangeToolType.write,
            file_path="/new_file.py",
            new_string="print('hello')",
        )
        params = cci.to_tool_parameters()
        assert params["file_path"] == "/new_file.py"
        assert params["new_string"] == "print('hello')"
        assert "old_string" not in params

    def test_multi_edit_to_tool_parameters(self) -> None:
        cci = CodeChangeInput(
            tool_type=CodeChangeToolType.multi_edit,
            file_path="/src/lib.py",
            edits=[
                EditEntry(old_string="a", new_string="b"),
                EditEntry(old_string="c", new_string="d"),
            ],
        )
        params = cci.to_tool_parameters()
        assert params["file_path"] == "/src/lib.py"
        assert isinstance(params["edits"], list)
        assert len(params["edits"]) == 2  # type: ignore[arg-type]
        assert params["edits"][0] == {"old_string": "a", "new_string": "b"}  # type: ignore[index]

    def test_file_name(self) -> None:
        cci = CodeChangeInput(
            tool_type=CodeChangeToolType.edit,
            file_path="/home/user/project/src/main.py",
        )
        assert cci.file_name == "main.py"

    def test_serialization(self) -> None:
        cci = CodeChangeInput(
            tool_type=CodeChangeToolType.write,
            file_path="/test.py",
            new_string="content",
        )
        data = cci.model_dump()
        restored = CodeChangeInput.model_validate(data)
        assert restored.file_path == "/test.py"
        assert restored.tool_type == CodeChangeToolType.write


# ---------- PendingToolUse ----------


class TestPendingToolUse:
    """Tests for PendingToolUse model."""

    def test_pending_duration(self) -> None:
        old_ts = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        ptu = PendingToolUse(
            tool_name="Bash",
            tool_use_id="tu_001",
            timestamp=old_ts,
        )
        assert ptu.pending_duration >= 9.0  # at least 9 seconds

    def test_is_likely_awaiting_approval_true(self) -> None:
        old_ts = datetime.now(tz=timezone.utc) - timedelta(seconds=5)
        ptu = PendingToolUse(
            tool_name="Bash",
            tool_use_id="tu_001",
            timestamp=old_ts,
        )
        assert ptu.is_likely_awaiting_approval is True

    def test_is_likely_awaiting_approval_false(self) -> None:
        recent_ts = datetime.now(tz=timezone.utc)
        ptu = PendingToolUse(
            tool_name="Bash",
            tool_use_id="tu_001",
            timestamp=recent_ts,
        )
        assert ptu.is_likely_awaiting_approval is False

    def test_is_code_change_tool(self) -> None:
        ptu_with = PendingToolUse(
            tool_name="Edit",
            tool_use_id="tu_002",
            timestamp=datetime.now(tz=timezone.utc),
            code_change_input=CodeChangeInput(
                tool_type=CodeChangeToolType.edit,
                file_path="/f.py",
            ),
        )
        assert ptu_with.is_code_change_tool is True

        ptu_without = PendingToolUse(
            tool_name="Bash",
            tool_use_id="tu_003",
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert ptu_without.is_code_change_tool is False


# ---------- ActivityEntry ----------


class TestActivityEntry:
    """Tests for ActivityEntry model."""

    def test_creation(self) -> None:
        now = datetime.now(tz=timezone.utc)
        entry = ActivityEntry(
            timestamp=now,
            type=ActivityTypeToolUse(name="Bash"),
            description="Running command",
        )
        assert entry.type.kind == "tool_use"
        assert entry.description == "Running command"
        assert entry.tool_input is None
        assert entry.id is not None  # auto-generated UUID

    def test_with_tool_input(self) -> None:
        now = datetime.now(tz=timezone.utc)
        cci = CodeChangeInput(
            tool_type=CodeChangeToolType.edit,
            file_path="/main.py",
        )
        entry = ActivityEntry(
            timestamp=now,
            type=ActivityTypeToolUse(name="Edit"),
            description="Editing file",
            tool_input=cci,
        )
        assert entry.tool_input is not None
        assert entry.tool_input.file_path == "/main.py"


# ---------- CostBreakdown ----------


class TestCostBreakdown:
    """Tests for CostBreakdown model."""

    def test_total_cost(self) -> None:
        cb = CostBreakdown(
            input_cost=0.10,
            output_cost=0.20,
            cache_read_cost=0.05,
            cache_creation_cost=0.03,
        )
        assert abs(cb.total_cost - 0.38) < 1e-9

    def test_zero_cost(self) -> None:
        cb = CostBreakdown(
            input_cost=0.0,
            output_cost=0.0,
            cache_read_cost=0.0,
            cache_creation_cost=0.0,
        )
        assert cb.total_cost == 0.0


# ---------- CostCalculator ----------


class TestCostCalculator:
    """Tests for CostCalculator.calculate() with known model pricing."""

    def test_opus_pricing(self) -> None:
        breakdown = CostCalculator.calculate(
            model="claude-opus-4-20250514",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=1_000_000,
            cache_creation_tokens=1_000_000,
        )
        # Opus: input=$15, output=$75, cache_read=$1.50, cache_creation=$18.75 per M
        assert abs(breakdown.input_cost - 15.0) < 1e-6
        assert abs(breakdown.output_cost - 75.0) < 1e-6
        assert abs(breakdown.cache_read_cost - 1.50) < 1e-6
        assert abs(breakdown.cache_creation_cost - 18.75) < 1e-6
        assert abs(breakdown.total_cost - 110.25) < 1e-6

    def test_sonnet_pricing(self) -> None:
        breakdown = CostCalculator.calculate(
            model="claude-sonnet-4-20250514",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=1_000_000,
            cache_creation_tokens=1_000_000,
        )
        assert abs(breakdown.input_cost - 3.0) < 1e-6
        assert abs(breakdown.output_cost - 15.0) < 1e-6
        assert abs(breakdown.cache_read_cost - 0.30) < 1e-6
        assert abs(breakdown.cache_creation_cost - 3.75) < 1e-6

    def test_haiku_pricing(self) -> None:
        breakdown = CostCalculator.calculate(
            model="claude-haiku-3",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=1_000_000,
            cache_creation_tokens=1_000_000,
        )
        assert abs(breakdown.input_cost - 0.25) < 1e-6
        assert abs(breakdown.output_cost - 1.25) < 1e-6
        assert abs(breakdown.cache_read_cost - 0.025) < 1e-6
        assert abs(breakdown.cache_creation_cost - 0.30) < 1e-6

    def test_unknown_model_defaults_to_sonnet(self) -> None:
        breakdown = CostCalculator.calculate(
            model="unknown-model-v9",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        # Should use sonnet pricing: $3/M input
        assert abs(breakdown.input_cost - 3.0) < 1e-6

    def test_zero_tokens(self) -> None:
        breakdown = CostCalculator.calculate(
            model="claude-sonnet-4-20250514",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        assert breakdown.total_cost == 0.0

    def test_small_token_count(self) -> None:
        breakdown = CostCalculator.calculate(
            model="claude-opus-4-20250514",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cache_creation_tokens=100,
        )
        expected_input = 1000 * 15.0 / 1_000_000
        expected_output = 500 * 75.0 / 1_000_000
        expected_cache_read = 200 * 1.50 / 1_000_000
        expected_cache_create = 100 * 18.75 / 1_000_000
        assert abs(breakdown.input_cost - expected_input) < 1e-9
        assert abs(breakdown.output_cost - expected_output) < 1e-9
        assert abs(breakdown.cache_read_cost - expected_cache_read) < 1e-9
        assert abs(breakdown.cache_creation_cost - expected_cache_create) < 1e-9


# ---------- SessionMonitorState ----------


class TestSessionMonitorState:
    """Tests for SessionMonitorState model."""

    def test_defaults(self) -> None:
        state = SessionMonitorState()
        assert state.status.kind == "idle"
        assert state.input_tokens == 0
        assert state.output_tokens == 0
        assert state.message_count == 0
        assert state.model == ""

    def test_total_tokens(self) -> None:
        state = SessionMonitorState(
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cache_creation_tokens=100,
        )
        assert state.total_tokens == 1800

    def test_context_window_usage_percentage(self) -> None:
        state = SessionMonitorState(
            input_tokens=100_000,
            output_tokens=50_000,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        # total = 150K, window = 200K => 75%
        assert abs(state.context_window_usage_percentage - 75.0) < 0.01

    def test_formatted_context_usage(self) -> None:
        state = SessionMonitorState(
            input_tokens=100_000,
            output_tokens=50_000,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        formatted = state.formatted_context_usage
        assert "150.0K" in formatted
        assert "200.0K" in formatted
        assert "75.0%" in formatted

    def test_format_token_count_millions(self) -> None:
        assert SessionMonitorState.format_token_count(2_500_000) == "2.5M"

    def test_format_token_count_thousands(self) -> None:
        assert SessionMonitorState.format_token_count(15_000) == "15.0K"

    def test_format_token_count_small(self) -> None:
        assert SessionMonitorState.format_token_count(500) == "500"

    def test_format_token_count_zero(self) -> None:
        assert SessionMonitorState.format_token_count(0) == "0"

    def test_context_window_size(self) -> None:
        state = SessionMonitorState()
        assert state.context_window_size == 200_000

    def test_is_awaiting_approval_with_recent_pending(self) -> None:
        # Pending tool use that was just created (less than 2 seconds ago)
        state = SessionMonitorState(
            pending_tool_use=PendingToolUse(
                tool_name="Edit",
                tool_use_id="tu_001",
                timestamp=datetime.now(tz=timezone.utc),
            ),
        )
        # Should not be awaiting approval yet
        assert state.is_awaiting_approval is False

    def test_is_awaiting_approval_with_old_pending(self) -> None:
        old_ts = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        state = SessionMonitorState(
            pending_tool_use=PendingToolUse(
                tool_name="Edit",
                tool_use_id="tu_001",
                timestamp=old_ts,
            ),
        )
        assert state.is_awaiting_approval is True

    def test_is_awaiting_approval_no_pending(self) -> None:
        state = SessionMonitorState()
        assert state.is_awaiting_approval is False

    def test_mutable(self) -> None:
        state = SessionMonitorState()
        state.input_tokens = 5000
        state.model = "claude-sonnet-4-20250514"
        assert state.input_tokens == 5000
        assert state.model == "claude-sonnet-4-20250514"

    def test_serialization(self) -> None:
        state = SessionMonitorState(
            input_tokens=1000,
            output_tokens=200,
            model="claude-opus-4-20250514",
        )
        data = state.model_dump()
        assert data["input_tokens"] == 1000
        assert data["total_tokens"] == 1200
        assert data["model"] == "claude-opus-4-20250514"

        restored = SessionMonitorState.model_validate(data)
        assert restored.input_tokens == 1000
        assert restored.total_tokens == 1200
