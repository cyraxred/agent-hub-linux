"""Tests for agent_hub.services.path_utils module."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_hub.services.path_utils import (
    decode_project_path,
    encode_project_path,
    find_session_files,
    get_claude_projects_dir,
    get_codex_sessions_dir,
    get_history_file,
    get_stats_cache_file,
    project_path_from_session_dir,
    session_id_from_path,
)


# ---------- encode_project_path ----------


class TestEncodeProjectPath:
    """Tests for encode_project_path()."""

    def test_normal_path(self) -> None:
        assert encode_project_path("/home/user/myproject") == "-home-user-myproject"

    def test_trailing_slash(self) -> None:
        assert encode_project_path("/home/user/myproject/") == "-home-user-myproject"

    def test_root_path(self) -> None:
        assert encode_project_path("/") == ""

    def test_empty_string(self) -> None:
        assert encode_project_path("") == ""

    def test_deep_path(self) -> None:
        assert encode_project_path("/a/b/c/d") == "-a-b-c-d"


# ---------- decode_project_path ----------


class TestDecodeProjectPath:
    """Tests for decode_project_path()."""

    def test_normal_decode(self) -> None:
        assert decode_project_path("-home-user-myproject") == "/home/user/myproject"

    def test_empty_string(self) -> None:
        assert decode_project_path("") == "/"

    def test_single_dash(self) -> None:
        assert decode_project_path("-") == "/"

    def test_roundtrip(self) -> None:
        original = "/home/user/myproject"
        encoded = encode_project_path(original)
        decoded = decode_project_path(encoded)
        assert decoded == original


# ---------- Directory helpers ----------


class TestDirectoryHelpers:
    """Tests for get_claude_projects_dir, get_codex_sessions_dir, etc."""

    def test_get_claude_projects_dir(self, tmp_path: Path) -> None:
        result = get_claude_projects_dir(str(tmp_path))
        assert result == tmp_path / "projects"

    def test_get_codex_sessions_dir(self, tmp_path: Path) -> None:
        result = get_codex_sessions_dir(str(tmp_path))
        assert result == tmp_path / "sessions"

    def test_get_history_file(self, tmp_path: Path) -> None:
        result = get_history_file(str(tmp_path))
        assert result == tmp_path / "history.jsonl"

    def test_get_stats_cache_file(self, tmp_path: Path) -> None:
        result = get_stats_cache_file(str(tmp_path))
        assert result == tmp_path / "stats-cache.json"


# ---------- find_session_files ----------


class TestFindSessionFiles:
    """Tests for find_session_files()."""

    def test_finds_jsonl_files(self, tmp_path: Path) -> None:
        proj_dir = tmp_path / "-home-user-proj"
        proj_dir.mkdir(parents=True)
        conversation_line = '{"type":"assistant","message":{"role":"assistant","content":[]}}\n'
        (proj_dir / "session1.jsonl").write_text(conversation_line)
        (proj_dir / "session2.jsonl").write_text(conversation_line)
        (proj_dir / "not_a_session.txt").write_text("nope")

        result = find_session_files(proj_dir)
        assert len(result) == 2
        assert all(p.suffix == ".jsonl" for p in result)

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        result = find_session_files(tmp_path / "nonexistent")
        assert result == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        result = find_session_files(projects_dir)
        assert result == []

    def test_nested_directories_excluded(self, tmp_path: Path) -> None:
        proj_dir = tmp_path / "-proj"
        nested = proj_dir / "subdir"
        nested.mkdir(parents=True)
        conversation_line = '{"type":"assistant","message":{"role":"assistant","content":[]}}\n'
        (nested / "deep.jsonl").write_text(conversation_line)

        # find_session_files only returns top-level .jsonl files, not nested
        result = find_session_files(proj_dir)
        assert len(result) == 0


# ---------- session_id_from_path ----------


class TestSessionIdFromPath:
    """Tests for session_id_from_path()."""

    def test_normal_path(self) -> None:
        path = Path("/home/user/.claude/projects/-proj/abc123.jsonl")
        assert session_id_from_path(path) == "abc123"

    def test_uuid_style(self) -> None:
        path = Path("/data/sess-uuid-1234-5678.jsonl")
        assert session_id_from_path(path) == "sess-uuid-1234-5678"


# ---------- project_path_from_session_dir ----------


class TestProjectPathFromSessionDir:
    """Tests for project_path_from_session_dir()."""

    def test_normal(self, tmp_path: Path) -> None:
        projects_dir = tmp_path / "projects"
        session_dir = projects_dir / "-home-user-myproject"
        session_dir.mkdir(parents=True)

        result = project_path_from_session_dir(session_dir, projects_dir)
        assert result == "/home/user/myproject"

    def test_unrelated_path(self, tmp_path: Path) -> None:
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        session_dir = Path("/completely/different/path")

        result = project_path_from_session_dir(session_dir, projects_dir)
        assert result == "/completely/different/path"
