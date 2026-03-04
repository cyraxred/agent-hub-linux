"""Tests for agent_hub.models.plan module."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_hub.models.monitor_state import (
    ActivityEntry,
    ActivityTypeToolUse,
    CodeChangeInput,
    CodeChangeToolType,
)
from agent_hub.models.plan import PlanState


# ---------- PlanState ----------


class TestPlanState:
    """Tests for the PlanState model."""

    def test_file_name(self) -> None:
        state = PlanState(file_path="/home/user/project/PLAN.md")
        assert state.file_name == "PLAN.md"

    def test_file_name_nested(self) -> None:
        state = PlanState(file_path="/home/user/project/docs/todo.txt")
        assert state.file_name == "todo.txt"

    def test_serialization(self) -> None:
        state = PlanState(file_path="/proj/PLAN.md")
        data = state.model_dump()
        assert data["file_name"] == "PLAN.md"
        restored = PlanState.model_validate(data)
        assert restored.file_path == "/proj/PLAN.md"

    def test_from_activities_finds_plan(self) -> None:
        now = datetime.now(tz=timezone.utc)
        activities = [
            ActivityEntry(
                timestamp=now,
                type=ActivityTypeToolUse(name="Write"),
                description="Writing plan",
                tool_input=CodeChangeInput(
                    tool_type=CodeChangeToolType.write,
                    file_path="/home/user/project/PLAN.md",
                    new_string="# Plan\n- Step 1",
                ),
            ),
        ]
        result = PlanState.from_activities(activities)
        assert result is not None
        assert result.file_path == "/home/user/project/PLAN.md"
        assert result.file_name == "PLAN.md"

    def test_from_activities_finds_todo(self) -> None:
        now = datetime.now(tz=timezone.utc)
        activities = [
            ActivityEntry(
                timestamp=now,
                type=ActivityTypeToolUse(name="Edit"),
                description="Editing todo",
                tool_input=CodeChangeInput(
                    tool_type=CodeChangeToolType.edit,
                    file_path="/proj/todo.md",
                ),
            ),
        ]
        result = PlanState.from_activities(activities)
        assert result is not None
        assert result.file_name == "todo.md"

    def test_from_activities_finds_tasks(self) -> None:
        now = datetime.now(tz=timezone.utc)
        activities = [
            ActivityEntry(
                timestamp=now,
                type=ActivityTypeToolUse(name="Write"),
                tool_input=CodeChangeInput(
                    tool_type=CodeChangeToolType.write,
                    file_path="/proj/tasks.txt",
                ),
            ),
        ]
        result = PlanState.from_activities(activities)
        assert result is not None
        assert result.file_name == "tasks.txt"

    def test_from_activities_no_plan(self) -> None:
        now = datetime.now(tz=timezone.utc)
        activities = [
            ActivityEntry(
                timestamp=now,
                type=ActivityTypeToolUse(name="Write"),
                tool_input=CodeChangeInput(
                    tool_type=CodeChangeToolType.write,
                    file_path="/proj/main.py",
                ),
            ),
        ]
        result = PlanState.from_activities(activities)
        assert result is None

    def test_from_activities_empty(self) -> None:
        result = PlanState.from_activities([])
        assert result is None

    def test_from_activities_no_tool_input(self) -> None:
        now = datetime.now(tz=timezone.utc)
        activities = [
            ActivityEntry(
                timestamp=now,
                type=ActivityTypeToolUse(name="Bash"),
                description="Running command",
            ),
        ]
        result = PlanState.from_activities(activities)
        assert result is None

    def test_from_activities_prefers_last_match(self) -> None:
        """from_activities iterates reversed, so the last plan file wins."""
        now = datetime.now(tz=timezone.utc)
        activities = [
            ActivityEntry(
                timestamp=now,
                type=ActivityTypeToolUse(name="Write"),
                tool_input=CodeChangeInput(
                    tool_type=CodeChangeToolType.write,
                    file_path="/proj/plan.md",
                ),
            ),
            ActivityEntry(
                timestamp=now,
                type=ActivityTypeToolUse(name="Write"),
                tool_input=CodeChangeInput(
                    tool_type=CodeChangeToolType.write,
                    file_path="/proj/todo.md",
                ),
            ),
        ]
        result = PlanState.from_activities(activities)
        assert result is not None
        assert result.file_name == "todo.md"
