"""Tests for agent_hub.models.worktree module."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from agent_hub.models.worktree import (
    RemoteBranch,
    WorktreeCreationProgress,
    WorktreeCreationProgressCompleted,
    WorktreeCreationProgressFailed,
    WorktreeCreationProgressIdle,
    WorktreeCreationProgressPreparing,
    WorktreeCreationProgressUpdatingFiles,
)


# ---------- WorktreeCreationProgress ----------


class TestWorktreeCreationProgressIdle:
    """Tests for the idle worktree state."""

    def test_defaults(self) -> None:
        state = WorktreeCreationProgressIdle()
        assert state.kind == "idle"
        assert state.progress_value == 0.0
        assert state.status_message == ""
        assert state.is_in_progress is False
        assert state.icon == "circle"


class TestWorktreeCreationProgressPreparing:
    """Tests for the preparing worktree state."""

    def test_with_message(self) -> None:
        state = WorktreeCreationProgressPreparing(message="Setting up...")
        assert state.kind == "preparing"
        assert state.progress_value == 0.1
        assert state.status_message == "Setting up..."
        assert state.is_in_progress is True
        assert state.icon == "gear"

    def test_default_message(self) -> None:
        state = WorktreeCreationProgressPreparing()
        assert state.status_message == "Preparing..."


class TestWorktreeCreationProgressUpdatingFiles:
    """Tests for the updating_files worktree state."""

    def test_progress_midway(self) -> None:
        state = WorktreeCreationProgressUpdatingFiles(current=50, total=100)
        assert state.kind == "updating_files"
        assert state.progress_value == pytest.approx(0.5, abs=0.01)
        assert "50/100" in state.status_message
        assert state.is_in_progress is True
        assert state.icon == "doc.on.doc"

    def test_progress_zero_total(self) -> None:
        state = WorktreeCreationProgressUpdatingFiles(current=0, total=0)
        assert state.progress_value == 0.5  # fallback

    def test_progress_complete(self) -> None:
        state = WorktreeCreationProgressUpdatingFiles(current=100, total=100)
        assert state.progress_value == pytest.approx(0.9, abs=0.01)


class TestWorktreeCreationProgressCompleted:
    """Tests for the completed worktree state."""

    def test_values(self) -> None:
        state = WorktreeCreationProgressCompleted(path="/repo/worktrees/feat")
        assert state.kind == "completed"
        assert state.path == "/repo/worktrees/feat"
        assert state.progress_value == 1.0
        assert state.status_message == "Completed"
        assert state.is_in_progress is False
        assert state.icon == "checkmark.circle"


class TestWorktreeCreationProgressFailed:
    """Tests for the failed worktree state."""

    def test_values(self) -> None:
        state = WorktreeCreationProgressFailed(error="branch already exists")
        assert state.kind == "failed"
        assert state.progress_value == 0.0
        assert "branch already exists" in state.status_message
        assert state.is_in_progress is False
        assert state.icon == "xmark.circle"


class TestWorktreeCreationProgressDiscriminator:
    """Tests for the WorktreeCreationProgress discriminated union."""

    def test_all_variants(self) -> None:
        adapter = TypeAdapter(WorktreeCreationProgress)
        variants = [
            {"kind": "idle"},
            {"kind": "preparing", "message": ""},
            {"kind": "updating_files", "current": 5, "total": 10},
            {"kind": "completed", "path": "/x"},
            {"kind": "failed", "error": "oops"},
        ]
        for v in variants:
            parsed = adapter.validate_python(v)
            assert parsed.kind == v["kind"]

    def test_serialization_roundtrip(self) -> None:
        adapter = TypeAdapter(WorktreeCreationProgress)
        state = WorktreeCreationProgressUpdatingFiles(current=3, total=10)
        data = adapter.dump_python(state)
        restored = adapter.validate_python(data)
        assert restored.kind == "updating_files"


# ---------- RemoteBranch ----------


class TestRemoteBranch:
    """Tests for the RemoteBranch model."""

    def test_display_name_with_prefix(self) -> None:
        branch = RemoteBranch(name="origin/feature/auth", remote="origin")
        assert branch.display_name == "feature/auth"

    def test_display_name_without_prefix(self) -> None:
        branch = RemoteBranch(name="feature/auth", remote="upstream")
        assert branch.display_name == "feature/auth"

    def test_display_name_exact_remote(self) -> None:
        branch = RemoteBranch(name="origin/main", remote="origin")
        assert branch.display_name == "main"

    def test_serialization(self) -> None:
        branch = RemoteBranch(name="origin/main", remote="origin")
        data = branch.model_dump()
        assert data["display_name"] == "main"
        restored = RemoteBranch.model_validate(data)
        assert restored.display_name == "main"
