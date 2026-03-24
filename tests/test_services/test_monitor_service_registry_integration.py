"""Integration tests: TranscriptRegistry + SessionManager working together.

Verifies that transcript registration flows metadata (first_message, slug)
through to SessionManager sessions, and that repository management works.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_hub.services.file_watcher import FileWatcher
from agent_hub.services.session_jsonl_parser import ParseResult, parse_new_lines
from agent_hub.services.session_manager import Session, SessionManager
from agent_hub.services.transcript_registry import TranscriptRegistry


def _conversation_line(role: str = "assistant", text: str = "Hello") -> str:
    if role == "assistant":
        return json.dumps({
            "type": "assistant",
            "timestamp": "2025-06-15T10:30:00Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-20250514",
                "content": [{"type": "text", "text": text}],
                "usage": {"inputTokens": 100, "outputTokens": 50},
            },
        })
    return json.dumps({
        "type": "user",
        "timestamp": "2025-06-15T10:30:00Z",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    })


def _encode_project_path(path: str) -> str:
    from agent_hub.services.path_utils import encode_project_path
    return encode_project_path(path)


@pytest.fixture()
def file_watcher():
    fw = FileWatcher()
    fw.set_loop(asyncio.get_event_loop())
    yield fw
    fw.shutdown()


@pytest.fixture()
def claude_registry(file_watcher: FileWatcher) -> TranscriptRegistry:
    return TranscriptRegistry(
        provider="claude",
        parse_fn=parse_new_lines,
        parse_result_factory=ParseResult,
        approval_timeout_seconds=5,
        file_watcher=file_watcher,
    )


@pytest.fixture()
def session_manager() -> SessionManager:
    tracker = MagicMock()
    tracker.get_needs_attention = MagicMock(return_value=False)
    tracker.get_effective_status = MagicMock(return_value="idle")
    tracker.get_pending_attention = MagicMock(return_value=[])
    process_registry = MagicMock()
    sm = SessionManager()
    sm.set_tracker(tracker)
    sm.set_process_registry(process_registry)
    return sm


class TestRegistryToSessionManager:
    """Transcript registration propagates metadata to SessionManager."""

    async def test_transcript_added_creates_session(
        self, claude_registry: TranscriptRegistry, session_manager: SessionManager, tmp_path: Path
    ):
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        repo_path = str(repo_dir.resolve())

        claude_path = tmp_path / ".claude"
        encoded = _encode_project_path(repo_path)
        projects_dir = claude_path / "projects" / encoded
        projects_dir.mkdir(parents=True)

        session_file = projects_dir / "session-001.jsonl"
        session_file.write_text(
            _conversation_line("user", "Fix the login bug") + "\n"
            + _conversation_line("assistant", "On it!") + "\n"
        )

        # Wire registry -> session manager
        claude_registry.on_transcript_added(session_manager.handle_transcript_added)
        claude_registry.on_transcript_removed(session_manager.handle_transcript_removed)

        await claude_registry.register_transcript(
            session_id="session-001",
            project_path=repo_path,
            file_path=str(session_file),
        )

        session = session_manager.get_session("session-001")
        assert session is not None
        assert session.project_path == repo_path
        assert session.session_file_path == str(session_file)

    async def test_transcript_first_message_propagates(
        self, claude_registry: TranscriptRegistry, session_manager: SessionManager, tmp_path: Path
    ):
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        repo_path = str(repo_dir.resolve())

        claude_path = tmp_path / ".claude"
        encoded = _encode_project_path(repo_path)
        projects_dir = claude_path / "projects" / encoded
        projects_dir.mkdir(parents=True)

        session_file = projects_dir / "session-002.jsonl"
        session_file.write_text(
            _conversation_line("user", "Refactor the parser module") + "\n"
            + _conversation_line("assistant", "Sure!") + "\n"
        )

        claude_registry.on_transcript_added(session_manager.handle_transcript_added)

        await claude_registry.register_transcript(
            session_id="session-002",
            project_path=repo_path,
            file_path=str(session_file),
        )

        session = session_manager.get_session("session-002")
        assert session is not None
        assert session.first_message == "Refactor the parser module"

    async def test_transcript_removed_cleans_session(
        self, claude_registry: TranscriptRegistry, session_manager: SessionManager, tmp_path: Path
    ):
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        repo_path = str(repo_dir.resolve())

        claude_path = tmp_path / ".claude"
        encoded = _encode_project_path(repo_path)
        projects_dir = claude_path / "projects" / encoded
        projects_dir.mkdir(parents=True)

        session_file = projects_dir / "session-003.jsonl"
        session_file.write_text(_conversation_line("user") + "\n")

        claude_registry.on_transcript_added(session_manager.handle_transcript_added)
        claude_registry.on_transcript_removed(session_manager.handle_transcript_removed)

        await claude_registry.register_transcript(
            session_id="session-003",
            project_path=repo_path,
            file_path=str(session_file),
        )
        assert session_manager.get_session("session-003") is not None

        # Directly call handle_transcript_removed (simulating file deletion)
        await session_manager.handle_transcript_removed("session-003")
        assert session_manager.get_session("session-003") is None

        await claude_registry.stop()


class TestRepositoryManagement:
    """SessionManager repository add/remove/list."""

    async def test_add_and_list_repositories(self, session_manager: SessionManager):
        added = await session_manager.add_repository("/home/user/project-a", "claude")
        assert added is True

        repos = session_manager.get_repositories()
        assert "/home/user/project-a" in repos

    async def test_add_duplicate_repository(self, session_manager: SessionManager):
        await session_manager.add_repository("/home/user/project-b", "claude")
        added_again = await session_manager.add_repository("/home/user/project-b", "claude")
        assert added_again is False

    async def test_remove_repository(self, session_manager: SessionManager):
        await session_manager.add_repository("/home/user/project-c", "claude")
        await session_manager.remove_repository("/home/user/project-c", "claude")
        repos = session_manager.get_repositories()
        assert "/home/user/project-c" not in repos
