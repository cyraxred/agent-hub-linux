"""Integration test: session monitoring end-to-end flow.

Creates a temporary directory structure mimicking ~/.claude/,
discovers sessions, starts a file watcher, appends JSONL lines,
and verifies that state updates propagate correctly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.services.cli_session_monitor import CLISessionMonitorService
from agent_hub.services.path_utils import encode_project_path
from agent_hub.services.session_file_watcher import SessionFileWatcher


def _jsonl_user_message(text: str, ts: str = "2025-06-15T10:30:00Z") -> str:
    """Create a JSONL line for a user message."""
    return json.dumps(
        {
            "type": "user",
            "timestamp": ts,
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        }
    )


def _jsonl_assistant_message(
    text: str,
    ts: str = "2025-06-15T10:30:05Z",
    model: str = "claude-sonnet-4-20250514",
    input_tokens: int = 1000,
    output_tokens: int = 200,
) -> str:
    """Create a JSONL line for an assistant message with usage."""
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts,
            "message": {
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": text}],
                "usage": {
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                },
            },
        }
    )


def _jsonl_tool_use(
    tool_name: str,
    tool_id: str,
    input_data: dict,
    ts: str = "2025-06-15T10:30:10Z",
) -> str:
    """Create a JSONL line for a tool use."""
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts,
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": input_data,
                    }
                ],
            },
        }
    )


def _jsonl_tool_result(
    tool_use_id: str,
    content: str = "OK",
    is_error: bool = False,
    ts: str = "2025-06-15T10:30:15Z",
) -> str:
    """Create a JSONL line for a tool result."""
    return json.dumps(
        {
            "type": "user",
            "timestamp": ts,
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": content,
                        "is_error": is_error,
                    }
                ],
            },
        }
    )


class TestSessionMonitoringFlow:
    """Integration test for the full session monitoring pipeline."""

    @pytest.fixture()
    def claude_dir(self, tmp_path: Path) -> Path:
        """Create a fake ~/.claude directory."""
        d = tmp_path / "claude-data"
        d.mkdir()
        (d / "projects").mkdir()
        return d

    @pytest.fixture()
    def repo_dir(self, tmp_path: Path) -> Path:
        """Create a fake repository directory."""
        d = tmp_path / "my-project"
        d.mkdir()
        return d

    def _setup_session_file(
        self, claude_dir: Path, repo_path: str, session_id: str
    ) -> Path:
        """Create the Claude project directory and empty session file."""
        encoded = encode_project_path(repo_path)
        project_dir = claude_dir / "projects" / encoded
        project_dir.mkdir(parents=True, exist_ok=True)
        session_file = project_dir / f"{session_id}.jsonl"
        session_file.write_text("")
        return session_file

    async def test_discover_sessions_in_repository(
        self, claude_dir: Path, repo_dir: Path
    ) -> None:
        """Add a repository and verify sessions are discovered."""
        repo_path = str(repo_dir)
        session_id = "integration-test-session"

        # Create session file with initial content
        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("Hello world") + "\n"
            + _jsonl_assistant_message("Hi there!") + "\n"
        )

        # Initialize the monitor service
        monitor = CLISessionMonitorService(claude_data_path=str(claude_dir))
        repo = await monitor.add_repository(repo_path)

        assert repo is not None
        assert repo.path == repo_path
        assert repo.total_session_count >= 1

        # Find the session
        all_sessions = []
        for wt in repo.worktrees:
            all_sessions.extend(wt.sessions)

        found = [s for s in all_sessions if s.id == session_id]
        assert len(found) == 1
        assert found[0].project_path == repo_path

    async def test_file_watcher_reads_initial_content(
        self, claude_dir: Path, repo_dir: Path
    ) -> None:
        """Start a file watcher and verify it reads existing content."""
        repo_path = str(repo_dir)
        session_id = "watcher-init-test"

        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("First message") + "\n"
            + _jsonl_assistant_message("Response", model="claude-opus-4-20250514") + "\n"
        )

        watcher = SessionFileWatcher(
            claude_path=str(claude_dir),
            approval_timeout_seconds=5,
        )

        await watcher.start_monitoring(
            session_id=session_id,
            project_path=repo_path,
            session_file_path=str(session_file),
        )

        state = await watcher.get_state(session_id)
        assert state is not None
        assert state.message_count == 1  # one user message
        assert state.model == "claude-opus-4-20250514"
        assert state.output_tokens == 200

        await watcher.shutdown()

    async def test_append_lines_and_verify_state_updates(
        self, claude_dir: Path, repo_dir: Path
    ) -> None:
        """Start watcher, append new lines to the JSONL, then refresh and verify updates."""
        repo_path = str(repo_dir)
        session_id = "append-test-session"

        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("Initial message", "2025-06-15T10:00:00Z") + "\n"
        )

        # Track state update callbacks
        received_updates: list[tuple[str, SessionMonitorState]] = []

        async def on_state_update(
            sid: str, state: SessionMonitorState
        ) -> None:
            received_updates.append((sid, state))

        watcher = SessionFileWatcher(
            claude_path=str(claude_dir),
            approval_timeout_seconds=5,
        )
        watcher.on_state_update(on_state_update)

        await watcher.start_monitoring(
            session_id=session_id,
            project_path=repo_path,
            session_file_path=str(session_file),
        )

        # Verify initial state
        state = await watcher.get_state(session_id)
        assert state is not None
        assert state.message_count == 1

        # Append new lines to the file
        with open(session_file, "a") as f:
            f.write(
                _jsonl_assistant_message(
                    "First response",
                    ts="2025-06-15T10:01:00Z",
                    input_tokens=1500,
                    output_tokens=300,
                ) + "\n"
            )
            f.write(
                _jsonl_tool_use(
                    "Edit",
                    "tool_int_001",
                    {
                        "file_path": "/home/user/project/main.py",
                        "old_string": "old",
                        "new_string": "new",
                    },
                    ts="2025-06-15T10:02:00Z",
                ) + "\n"
            )
            f.write(
                _jsonl_tool_result(
                    "tool_int_001",
                    "File edited successfully",
                    ts="2025-06-15T10:02:05Z",
                ) + "\n"
            )

        # Force refresh (since filesystem events may not fire in test environment)
        await watcher.refresh_state(session_id)

        state = await watcher.get_state(session_id)
        assert state is not None
        # After refresh: only real user text messages count (tool-result turns excluded)
        assert state.message_count >= 1
        assert state.model == "claude-sonnet-4-20250514"
        assert state.total_output_tokens >= 300
        assert state.tool_calls.get("Edit", 0) >= 1

        # Verify activities include tool operations
        tool_use_acts = [
            a for a in state.recent_activities if a.type.kind == "tool_use"
        ]
        assert len(tool_use_acts) >= 1

        await watcher.shutdown()

    async def test_full_flow_monitor_and_watcher(
        self, claude_dir: Path, repo_dir: Path
    ) -> None:
        """Full integration: monitor discovers sessions, watcher monitors them."""
        repo_path = str(repo_dir)
        session_id = "full-flow-session"

        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("Start coding", "2025-06-15T09:00:00Z") + "\n"
            + _jsonl_assistant_message(
                "Ready to help!", "2025-06-15T09:00:05Z", model="claude-sonnet-4-20250514"
            ) + "\n"
        )

        # Step 1: Discover sessions with the monitor
        monitor = CLISessionMonitorService(claude_data_path=str(claude_dir))
        repo = await monitor.add_repository(repo_path)
        assert repo is not None

        all_sessions = []
        for wt in repo.worktrees:
            all_sessions.extend(wt.sessions)
        found = [s for s in all_sessions if s.id == session_id]
        assert len(found) == 1
        session = found[0]

        # Step 2: Start watcher on the discovered session
        watcher = SessionFileWatcher(
            claude_path=str(claude_dir),
            approval_timeout_seconds=5,
        )
        await watcher.start_monitoring(
            session_id=session.id,
            project_path=session.project_path,
            session_file_path=str(session_file),
        )

        state = await watcher.get_state(session.id)
        assert state is not None
        assert state.model == "claude-sonnet-4-20250514"
        assert state.message_count == 1

        # Step 3: Stop monitoring, append more data, then re-start to avoid
        # observer race conditions in the test environment.
        await watcher.stop_monitoring(session.id)

        with open(session_file, "a") as f:
            f.write(
                _jsonl_user_message("Now fix the tests", "2025-06-15T09:05:00Z") + "\n"
            )
            f.write(
                _jsonl_assistant_message(
                    "On it!", "2025-06-15T09:05:05Z",
                    input_tokens=3000, output_tokens=500
                ) + "\n"
            )

        # Step 4: Re-start monitoring (reads from scratch) and verify
        await watcher.start_monitoring(
            session_id=session.id,
            project_path=session.project_path,
            session_file_path=str(session_file),
        )
        state = await watcher.get_state(session.id)
        assert state is not None
        assert state.message_count == 2
        assert state.total_output_tokens == 700  # 200 + 500

        await watcher.shutdown()

    async def test_multiple_sessions_in_repo(
        self, claude_dir: Path, repo_dir: Path
    ) -> None:
        """Verify that multiple sessions in the same repo are all discovered."""
        repo_path = str(repo_dir)

        for i in range(3):
            sid = f"multi-session-{i:03d}"
            sf = self._setup_session_file(claude_dir, repo_path, sid)
            sf.write_text(
                _jsonl_user_message(f"Message from session {i}") + "\n"
                + _jsonl_assistant_message(f"Response {i}") + "\n"
            )

        monitor = CLISessionMonitorService(claude_data_path=str(claude_dir))
        repo = await monitor.add_repository(repo_path)
        assert repo is not None

        all_sessions = []
        for wt in repo.worktrees:
            all_sessions.extend(wt.sessions)

        session_ids = {s.id for s in all_sessions}
        for i in range(3):
            assert f"multi-session-{i:03d}" in session_ids

    async def test_add_duplicate_repository_returns_none(
        self, claude_dir: Path, repo_dir: Path
    ) -> None:
        """Adding the same repository twice should return None the second time."""
        repo_path = str(repo_dir)
        self._setup_session_file(claude_dir, repo_path, "dup-test")

        monitor = CLISessionMonitorService(claude_data_path=str(claude_dir))
        repo1 = await monitor.add_repository(repo_path)
        assert repo1 is not None

        repo2 = await monitor.add_repository(repo_path)
        assert repo2 is None

    async def test_watcher_stop_and_cleanup(
        self, claude_dir: Path, repo_dir: Path
    ) -> None:
        """Stop monitoring and verify state is cleaned up."""
        repo_path = str(repo_dir)
        session_id = "cleanup-test"
        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("test") + "\n"
        )

        watcher = SessionFileWatcher(
            claude_path=str(claude_dir),
            approval_timeout_seconds=5,
        )
        await watcher.start_monitoring(
            session_id=session_id,
            project_path=repo_path,
            session_file_path=str(session_file),
        )

        assert await watcher.get_state(session_id) is not None

        await watcher.stop_monitoring(session_id)
        assert await watcher.get_state(session_id) is None

        # Ensure shutdown after stop doesn't error
        await watcher.shutdown()
