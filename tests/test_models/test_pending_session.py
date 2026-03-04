"""Tests for agent_hub.models.pending_session module."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from agent_hub.models.pending_session import PendingHubSession
from agent_hub.models.session import CLISession, WorktreeBranch


# ---------- PendingHubSession ----------


class TestPendingHubSession:
    """Tests for the PendingHubSession model."""

    def test_creation(self) -> None:
        now = datetime.now(tz=timezone.utc)
        wt = WorktreeBranch(
            name="main",
            path="/repo",
            sessions=[
                CLISession(
                    id="s1",
                    project_path="/repo",
                    last_activity_at=now,
                ),
            ],
        )
        session = PendingHubSession(
            worktree=wt,
            initial_prompt="Fix the bug",
            initial_input_text="some input",
            dangerously_skip_permissions=True,
            worktree_name="feat-auth",
        )
        assert isinstance(session.id, UUID)
        assert isinstance(session.started_at, datetime)
        assert session.worktree.name == "main"
        assert session.initial_prompt == "Fix the bug"
        assert session.initial_input_text == "some input"
        assert session.dangerously_skip_permissions is True
        assert session.worktree_name == "feat-auth"

    def test_defaults(self) -> None:
        wt = WorktreeBranch(name="main", path="/repo")
        session = PendingHubSession(worktree=wt)
        assert session.initial_prompt == ""
        assert session.initial_input_text == ""
        assert session.dangerously_skip_permissions is False
        assert session.worktree_name == ""

    def test_frozen(self) -> None:
        wt = WorktreeBranch(name="main", path="/repo")
        session = PendingHubSession(worktree=wt)
        with pytest.raises(Exception):
            session.initial_prompt = "new"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        wt = WorktreeBranch(name="main", path="/repo")
        session = PendingHubSession(
            worktree=wt,
            initial_prompt="test prompt",
        )
        data = session.model_dump()
        restored = PendingHubSession.model_validate(data)
        assert restored.initial_prompt == "test prompt"
        assert restored.worktree.name == "main"
