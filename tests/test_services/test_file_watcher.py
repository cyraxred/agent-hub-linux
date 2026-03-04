"""Tests for agent_hub.services.session_file_watcher module."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hub.services.session_file_watcher import SessionFileWatcher


class TestSessionFileWatcher:
    """Tests for the SessionFileWatcher class."""

    @pytest.fixture()
    def watcher(self, tmp_path: Path) -> SessionFileWatcher:
        return SessionFileWatcher(
            claude_path=str(tmp_path),
            approval_timeout_seconds=5,
        )

    @pytest.fixture()
    def session_file(self, tmp_path: Path) -> Path:
        """Create a session JSONL file in a realistic directory structure."""
        projects_dir = tmp_path / "projects" / "-home-user-my-project"
        projects_dir.mkdir(parents=True)
        file_path = projects_dir / "test-session-001.jsonl"
        file_path.write_text("")
        return file_path

    async def test_start_monitoring_creates_internal_state(
        self, watcher: SessionFileWatcher, session_file: Path
    ) -> None:
        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )

        state = await watcher.get_state("test-session-001")
        assert state is not None
        assert state.status.kind == "idle"

        await watcher.shutdown()

    async def test_stop_monitoring_removes_state(
        self, watcher: SessionFileWatcher, session_file: Path
    ) -> None:
        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )
        assert await watcher.get_state("test-session-001") is not None

        await watcher.stop_monitoring("test-session-001")
        assert await watcher.get_state("test-session-001") is None

    async def test_get_state_unknown_session(self, watcher: SessionFileWatcher) -> None:
        state = await watcher.get_state("nonexistent-session")
        assert state is None

    async def test_start_monitoring_idempotent(
        self, watcher: SessionFileWatcher, session_file: Path
    ) -> None:
        """Starting monitoring twice for the same session should not error."""
        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )
        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )
        state = await watcher.get_state("test-session-001")
        assert state is not None

        await watcher.shutdown()

    async def test_watcher_reads_existing_content(
        self, watcher: SessionFileWatcher, session_file: Path
    ) -> None:
        """Watcher should parse existing file content on start_monitoring."""
        # Write content before starting the watcher
        line = json.dumps(
            {
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hello from existing content"}],
                },
            }
        )
        session_file.write_text(line + "\n")

        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )

        state = await watcher.get_state("test-session-001")
        assert state is not None
        assert state.message_count == 1

        await watcher.shutdown()

    async def test_watcher_reads_new_content_via_refresh(
        self, watcher: SessionFileWatcher, session_file: Path
    ) -> None:
        """Test that refresh_state re-reads the full file."""
        session_file.write_text("")

        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )

        state = await watcher.get_state("test-session-001")
        assert state is not None
        assert state.message_count == 0

        # Write new content
        line = json.dumps(
            {
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "New message"}],
                },
            }
        )
        session_file.write_text(line + "\n")

        # Refresh forces re-read from scratch
        await watcher.refresh_state("test-session-001")

        state = await watcher.get_state("test-session-001")
        assert state is not None
        # Parser counts user messages (may count at content and role level)
        assert state.message_count >= 1

        await watcher.shutdown()

    async def test_watcher_tracks_model(
        self, watcher: SessionFileWatcher, session_file: Path
    ) -> None:
        line = json.dumps(
            {
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-20250514",
                    "content": [{"type": "text", "text": "Hi"}],
                    "usage": {"inputTokens": 500, "outputTokens": 100},
                },
            }
        )
        session_file.write_text(line + "\n")

        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )

        state = await watcher.get_state("test-session-001")
        assert state is not None
        assert state.model == "claude-opus-4-20250514"
        assert state.input_tokens == 500
        assert state.output_tokens == 100

        await watcher.shutdown()

    async def test_state_callback(
        self, watcher: SessionFileWatcher, session_file: Path
    ) -> None:
        """Verify that state update callbacks are invoked."""
        received_updates: list[tuple[str, object]] = []

        async def on_update(session_id: str, state: object) -> None:
            received_updates.append((session_id, state))

        watcher.on_state_update(on_update)

        line = json.dumps(
            {
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hello"}],
                },
            }
        )
        session_file.write_text(line + "\n")

        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )

        # The initial parse should have triggered a callback
        assert len(received_updates) >= 1
        assert received_updates[0][0] == "test-session-001"

        await watcher.shutdown()

    async def test_shutdown_clears_everything(
        self, watcher: SessionFileWatcher, session_file: Path
    ) -> None:
        await watcher.start_monitoring(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            session_file_path=str(session_file),
        )

        await watcher.shutdown()

        assert await watcher.get_state("test-session-001") is None

    async def test_set_approval_timeout(self, watcher: SessionFileWatcher) -> None:
        await watcher.set_approval_timeout(10)
        assert watcher._approval_timeout_seconds == 10
