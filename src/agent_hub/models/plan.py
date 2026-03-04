"""Plan models for activity-based plan state extraction."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from pydantic import BaseModel, computed_field

if TYPE_CHECKING:
    from agent_hub.models.monitor_state import ActivityEntry


class PlanState(BaseModel, frozen=True):
    """State representing a detected plan file."""

    file_path: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_name(self) -> str:
        """Extract file name from the plan file path."""
        return PurePosixPath(self.file_path).name

    @staticmethod
    def from_activities(activities: list[ActivityEntry]) -> PlanState | None:
        """Extract a PlanState from recent activities if a plan file was written.

        Looks for write or edit operations on files that look like plan files
        (e.g., PLAN.md, plan.md, TODO.md, etc.).
        """
        plan_file_names = frozenset({
            "plan.md",
            "plan.txt",
            "todo.md",
            "todo.txt",
            "tasks.md",
            "tasks.txt",
        })

        for activity in reversed(activities):
            if activity.tool_input is not None:
                fp = activity.tool_input.file_path
                file_name = activity.tool_input.file_name.lower()
                if file_name in plan_file_names or ".claude/plans/" in fp:
                    return PlanState(file_path=fp)

        return None
