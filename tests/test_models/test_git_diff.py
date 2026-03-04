"""Tests for agent_hub.models.git_diff module."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import TypeAdapter

from agent_hub.models.git_diff import (
    DiffMode,
    GitDiffFileEntry,
    GitDiffState,
    ParsedFileDiff,
    _WEB_RENDERABLE_EXTENSIONS,
)


# ---------- DiffMode ----------


class TestDiffMode:
    """Tests for the DiffMode enum and its properties."""

    def test_values(self) -> None:
        assert DiffMode.unstaged == "unstaged"
        assert DiffMode.staged == "staged"
        assert DiffMode.branch == "branch"

    def test_icon_unstaged(self) -> None:
        assert DiffMode.unstaged.icon == "pencil.circle"

    def test_icon_staged(self) -> None:
        assert DiffMode.staged.icon == "checkmark.circle"

    def test_icon_branch(self) -> None:
        assert DiffMode.branch.icon == "arrow.triangle.branch"

    def test_empty_state_title_unstaged(self) -> None:
        assert DiffMode.unstaged.empty_state_title == "No Unstaged Changes"

    def test_empty_state_title_staged(self) -> None:
        assert DiffMode.staged.empty_state_title == "No Staged Changes"

    def test_empty_state_title_branch(self) -> None:
        assert DiffMode.branch.empty_state_title == "No Branch Changes"

    def test_empty_state_description_unstaged(self) -> None:
        assert "unstaged" in DiffMode.unstaged.empty_state_description.lower()

    def test_empty_state_description_staged(self) -> None:
        assert "staged" in DiffMode.staged.empty_state_description.lower()

    def test_empty_state_description_branch(self) -> None:
        assert "branch" in DiffMode.branch.empty_state_description.lower()

    def test_loading_message_unstaged(self) -> None:
        assert "unstaged" in DiffMode.unstaged.loading_message.lower()

    def test_loading_message_staged(self) -> None:
        assert "staged" in DiffMode.staged.loading_message.lower()

    def test_loading_message_branch(self) -> None:
        assert "branch" in DiffMode.branch.loading_message.lower()


# ---------- GitDiffFileEntry ----------


class TestGitDiffFileEntry:
    """Tests for the GitDiffFileEntry model."""

    def test_basic_creation(self) -> None:
        entry = GitDiffFileEntry(
            file_path="/home/user/repo/src/main.py",
            relative_path="src/main.py",
            additions=10,
            deletions=5,
        )
        assert entry.file_path == "/home/user/repo/src/main.py"
        assert entry.relative_path == "src/main.py"
        assert entry.additions == 10
        assert entry.deletions == 5
        assert isinstance(entry.id, UUID)

    def test_file_name_computed(self) -> None:
        entry = GitDiffFileEntry(
            file_path="src/components/Button.tsx",
            relative_path="src/components/Button.tsx",
        )
        assert entry.file_name == "Button.tsx"

    def test_directory_path_computed(self) -> None:
        entry = GitDiffFileEntry(
            file_path="src/components/Button.tsx",
            relative_path="src/components/Button.tsx",
        )
        assert entry.directory_path == "src/components"

    def test_directory_path_root_file(self) -> None:
        entry = GitDiffFileEntry(
            file_path="README.md",
            relative_path="README.md",
        )
        assert entry.directory_path == ""

    def test_is_web_renderable_true(self) -> None:
        for ext in [".py", ".js", ".tsx", ".html", ".css", ".json", ".md"]:
            entry = GitDiffFileEntry(
                file_path=f"file{ext}",
                relative_path=f"file{ext}",
            )
            assert entry.is_web_renderable is True, f"Expected {ext} to be renderable"

    def test_is_web_renderable_false(self) -> None:
        for ext in [".png", ".jpg", ".bin", ".zip", ".wasm"]:
            entry = GitDiffFileEntry(
                file_path=f"file{ext}",
                relative_path=f"file{ext}",
            )
            assert entry.is_web_renderable is False, f"Expected {ext} to not be renderable"

    def test_defaults(self) -> None:
        entry = GitDiffFileEntry(
            file_path="test.py",
            relative_path="test.py",
        )
        assert entry.additions == 0
        assert entry.deletions == 0

    def test_serialization_roundtrip(self) -> None:
        entry = GitDiffFileEntry(
            file_path="/repo/src/main.py",
            relative_path="src/main.py",
            additions=10,
            deletions=3,
        )
        data = entry.model_dump()
        assert data["file_name"] == "main.py"
        # directory_path is extracted from file_path (the full path)
        assert data["directory_path"] == "/repo/src"
        assert data["is_web_renderable"] is True

        restored = GitDiffFileEntry.model_validate(data)
        assert restored.file_path == "/repo/src/main.py"
        assert restored.file_name == "main.py"

    def test_frozen(self) -> None:
        entry = GitDiffFileEntry(
            file_path="test.py",
            relative_path="test.py",
        )
        with pytest.raises(Exception):
            entry.file_path = "other.py"  # type: ignore[misc]


# ---------- GitDiffState ----------


class TestGitDiffState:
    """Tests for the GitDiffState model."""

    def test_file_count(self) -> None:
        state = GitDiffState(
            files=[
                GitDiffFileEntry(file_path="a.py", relative_path="a.py"),
                GitDiffFileEntry(file_path="b.py", relative_path="b.py"),
            ]
        )
        assert state.file_count == 2

    def test_file_count_empty(self) -> None:
        state = GitDiffState()
        assert state.file_count == 0

    def test_empty_factory(self) -> None:
        state = GitDiffState.empty()
        assert state.files == []
        assert state.file_count == 0

    def test_serialization(self) -> None:
        state = GitDiffState(
            files=[GitDiffFileEntry(file_path="a.py", relative_path="a.py")]
        )
        data = state.model_dump()
        assert data["file_count"] == 1
        restored = GitDiffState.model_validate(data)
        assert restored.file_count == 1


# ---------- ParsedFileDiff ----------


class TestParsedFileDiff:
    """Tests for the ParsedFileDiff model."""

    def test_creation(self) -> None:
        diff = ParsedFileDiff(
            file_path="/src/main.py",
            old_content="hello",
            new_content="world",
        )
        assert diff.file_path == "/src/main.py"
        assert diff.old_content == "hello"
        assert diff.new_content == "world"

    def test_defaults(self) -> None:
        diff = ParsedFileDiff(file_path="/test.py")
        assert diff.old_content == ""
        assert diff.new_content == ""

    def test_serialization(self) -> None:
        diff = ParsedFileDiff(
            file_path="/test.py",
            old_content="old",
            new_content="new",
        )
        data = diff.model_dump()
        restored = ParsedFileDiff.model_validate(data)
        assert restored.old_content == "old"
        assert restored.new_content == "new"
