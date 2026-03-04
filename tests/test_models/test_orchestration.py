"""Tests for agent_hub.models.orchestration module."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from agent_hub.models.orchestration import (
    OrchestrationPlan,
    OrchestrationSession,
    OrchestrationStatus,
)


# ---------- OrchestrationStatus ----------


class TestOrchestrationStatus:
    """Tests for the OrchestrationStatus enum."""

    def test_values(self) -> None:
        assert OrchestrationStatus.pending == "pending"
        assert OrchestrationStatus.running == "running"
        assert OrchestrationStatus.completed == "completed"
        assert OrchestrationStatus.failed == "failed"


# ---------- OrchestrationSession ----------


class TestOrchestrationSession:
    """Tests for the OrchestrationSession model."""

    def test_creation(self) -> None:
        session = OrchestrationSession(
            worktree_path="/repo/worktrees/feat-auth",
            prompt="Implement authentication",
            status=OrchestrationStatus.running,
        )
        assert session.worktree_path == "/repo/worktrees/feat-auth"
        assert session.prompt == "Implement authentication"
        assert session.status == OrchestrationStatus.running
        assert isinstance(session.id, UUID)

    def test_default_status(self) -> None:
        session = OrchestrationSession(
            worktree_path="/repo/wt",
            prompt="test",
        )
        assert session.status == OrchestrationStatus.pending

    def test_frozen(self) -> None:
        session = OrchestrationSession(
            worktree_path="/repo/wt",
            prompt="test",
        )
        with pytest.raises(Exception):
            session.status = OrchestrationStatus.running  # type: ignore[misc]

    def test_serialization(self) -> None:
        session = OrchestrationSession(
            worktree_path="/repo/wt",
            prompt="do something",
        )
        data = session.model_dump()
        restored = OrchestrationSession.model_validate(data)
        assert restored.worktree_path == "/repo/wt"
        assert restored.prompt == "do something"


# ---------- OrchestrationPlan ----------


class TestOrchestrationPlan:
    """Tests for the OrchestrationPlan model."""

    def test_creation(self) -> None:
        sessions = [
            OrchestrationSession(
                worktree_path="/repo/wt/a",
                prompt="Task A",
                status=OrchestrationStatus.pending,
            ),
            OrchestrationSession(
                worktree_path="/repo/wt/b",
                prompt="Task B",
                status=OrchestrationStatus.running,
            ),
        ]
        plan = OrchestrationPlan(
            name="Multi-task plan",
            sessions=sessions,
        )
        assert plan.name == "Multi-task plan"
        assert len(plan.sessions) == 2
        assert isinstance(plan.id, UUID)
        assert isinstance(plan.created_at, datetime)

    def test_defaults(self) -> None:
        plan = OrchestrationPlan(name="empty")
        assert plan.sessions == []
        assert plan.created_at is not None

    def test_serialization_roundtrip(self) -> None:
        plan = OrchestrationPlan(
            name="test-plan",
            sessions=[
                OrchestrationSession(
                    worktree_path="/wt", prompt="p"
                ),
            ],
        )
        data = plan.model_dump()
        restored = OrchestrationPlan.model_validate(data)
        assert restored.name == "test-plan"
        assert len(restored.sessions) == 1
