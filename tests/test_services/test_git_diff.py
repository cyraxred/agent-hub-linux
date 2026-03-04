"""Tests for agent_hub.services.git_diff_service module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_hub.services.git_diff_service import (
    GitDiffError,
    _parse_numstat,
    detect_base_branch,
    find_git_root,
)


# ---------- _parse_numstat ----------


class TestParseNumstat:
    """Tests for the _parse_numstat() function."""

    def test_basic_numstat(self) -> None:
        output = "10\t5\tsrc/main.py\n3\t1\tREADME.md\n"
        entries = _parse_numstat(output, "/home/user/repo")

        assert len(entries) == 2

        assert entries[0].relative_path == "src/main.py"
        assert entries[0].additions == 10
        assert entries[0].deletions == 5
        assert entries[0].file_path == "/home/user/repo/src/main.py"

        assert entries[1].relative_path == "README.md"
        assert entries[1].additions == 3
        assert entries[1].deletions == 1

    def test_binary_files(self) -> None:
        """Binary files show '-' for adds/dels."""
        output = "-\t-\tassets/image.png\n"
        entries = _parse_numstat(output, "/repo")

        assert len(entries) == 1
        assert entries[0].additions == 0
        assert entries[0].deletions == 0
        assert entries[0].relative_path == "assets/image.png"

    def test_empty_output(self) -> None:
        entries = _parse_numstat("", "/repo")
        assert entries == []

    def test_whitespace_only(self) -> None:
        entries = _parse_numstat("  \n  \n", "/repo")
        assert entries == []

    def test_malformed_lines_skipped(self) -> None:
        output = "10\t5\tgood_file.py\nbadline\n0\t0\talso_good.py\n"
        entries = _parse_numstat(output, "/repo")
        assert len(entries) == 2
        assert entries[0].relative_path == "good_file.py"
        assert entries[1].relative_path == "also_good.py"

    def test_file_names_with_spaces(self) -> None:
        """Numstat uses tab separators, file names may contain spaces."""
        output = "5\t2\tsrc/my file.py\n"
        entries = _parse_numstat(output, "/repo")
        assert len(entries) == 1
        assert entries[0].relative_path == "src/my file.py"

    def test_computed_fields_on_entries(self) -> None:
        output = "10\t5\tsrc/components/Button.tsx\n"
        entries = _parse_numstat(output, "/home/user/project")

        entry = entries[0]
        assert entry.file_name == "Button.tsx"
        assert entry.is_web_renderable is True

    def test_non_renderable_extension(self) -> None:
        output = "1\t0\tdata/model.bin\n"
        entries = _parse_numstat(output, "/repo")
        assert entries[0].is_web_renderable is False


# ---------- find_git_root (mocked) ----------


class TestFindGitRoot:
    """Tests for find_git_root() with mocked subprocess."""

    async def test_find_git_root_success(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"/home/user/myrepo\n",
            b"",
        )

        with patch("agent_hub.services.git_diff_service.asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = mock_proc
            result = await find_git_root("/home/user/myrepo/src")

        assert result == "/home/user/myrepo"

    async def test_find_git_root_not_a_repo(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"fatal: not a git repository")

        with patch("agent_hub.services.git_diff_service.asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = mock_proc
            with pytest.raises(GitDiffError, match="Not a git repository"):
                await find_git_root("/tmp/not-a-repo")


# ---------- detect_base_branch (mocked) ----------


class TestDetectBaseBranch:
    """Tests for detect_base_branch() with mocked subprocess."""

    async def test_detect_main_branch(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"abc123def\n",
            b"",
        )

        with patch("agent_hub.services.git_diff_service.asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = mock_proc
            result = await detect_base_branch("/repo")

        assert result == "main"

    async def test_detect_master_branch(self) -> None:
        call_count = 0

        async def mock_exec(*args: object, **kwargs: object) -> AsyncMock:
            nonlocal call_count
            proc = AsyncMock()
            if call_count == 0:
                # First call: checking "main" -> empty (not found)
                proc.communicate.return_value = (b"", b"")
                call_count += 1
            else:
                # Second call: checking "master" -> found
                proc.communicate.return_value = (b"def456\n", b"")
            return proc

        with patch(
            "agent_hub.services.git_diff_service.asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            result = await detect_base_branch("/repo")

        assert result == "master"

    async def test_detect_fallback_to_main(self) -> None:
        """When neither main nor master exists, default to 'main'."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")

        with patch("agent_hub.services.git_diff_service.asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = mock_proc
            result = await detect_base_branch("/repo")

        assert result == "main"
