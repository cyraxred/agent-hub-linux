"""Tests for the transcript registry and session transcript."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hub.services.session_jsonl_parser import ParseResult, parse_new_lines
from agent_hub.services.transcript_registry import TranscriptRegistry


class TestTranscriptRegistry:
    """Tests for TranscriptRegistry + SessionTranscript."""

    @pytest.fixture()
    def registry(self, tmp_path: Path) -> TranscriptRegistry:
        from agent_hub.services.file_watcher import FileWatcher

        fw = FileWatcher()
        fw.set_loop(asyncio.get_event_loop())
        reg = TranscriptRegistry(
            provider="claude",
            parse_fn=parse_new_lines,
            parse_result_factory=ParseResult,
            approval_timeout_seconds=5,
            file_watcher=fw,
        )
        self._fw = fw  # prevent GC
        return reg

    @pytest.fixture()
    def session_file(self, tmp_path: Path) -> Path:
        projects_dir = tmp_path / "projects" / "-home-user-my-project"
        projects_dir.mkdir(parents=True)
        file_path = projects_dir / "test-session-001.jsonl"
        file_path.write_text("")
        return file_path

    async def test_register_transcript_creates_state(
        self, registry: TranscriptRegistry, session_file: Path
    ) -> None:
        transcript = await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )

        assert transcript is not None
        assert transcript.state.status.kind == "idle"

        found = registry.get_transcript("test-session-001")
        assert found is transcript

        await registry.stop()
        self._fw.shutdown()

    async def test_get_transcript_unknown_session(self, registry: TranscriptRegistry) -> None:
        result = registry.get_transcript("nonexistent-session")
        assert result is None
        self._fw.shutdown()

    async def test_register_idempotent(
        self, registry: TranscriptRegistry, session_file: Path
    ) -> None:
        t1 = await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )
        t2 = await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )
        assert t1 is t2

        await registry.stop()
        self._fw.shutdown()

    async def test_reads_existing_content(
        self, registry: TranscriptRegistry, session_file: Path
    ) -> None:
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

        transcript = await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )

        assert transcript.state.message_count == 1

        await registry.stop()
        self._fw.shutdown()

    async def test_refresh_re_reads(
        self, registry: TranscriptRegistry, session_file: Path
    ) -> None:
        session_file.write_text("")

        transcript = await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )
        assert transcript.state.message_count == 0

        line = json.dumps(
            {
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "New"}],
                },
            }
        )
        session_file.write_text(line + "\n")

        await transcript.refresh()
        assert transcript.state.message_count >= 1

        await registry.stop()
        self._fw.shutdown()

    async def test_tracks_model(
        self, registry: TranscriptRegistry, session_file: Path
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

        transcript = await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )

        assert transcript.state.model == "claude-opus-4-20250514"
        assert transcript.state.input_tokens == 500
        assert transcript.state.output_tokens == 100

        await registry.stop()
        self._fw.shutdown()

    async def test_state_callback(
        self, registry: TranscriptRegistry, session_file: Path
    ) -> None:
        received_updates: list[tuple[str, object]] = []

        async def on_update(session_id: str, state: object) -> None:
            received_updates.append((session_id, state))

        registry.on_state_update(on_update)

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

        await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )

        assert len(received_updates) >= 1
        assert received_updates[0][0] == "test-session-001"

        await registry.stop()
        self._fw.shutdown()

    async def test_stop_clears_everything(
        self, registry: TranscriptRegistry, session_file: Path
    ) -> None:
        await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )

        await registry.stop()
        assert registry.get_transcript("test-session-001") is None
        self._fw.shutdown()

    async def test_set_monitored(
        self, registry: TranscriptRegistry, session_file: Path
    ) -> None:
        transcript = await registry.register_transcript(
            session_id="test-session-001",
            project_path="/home/user/my-project",
            file_path=str(session_file),
        )
        assert not transcript.is_monitored

        registry.set_monitored("test-session-001", True)
        assert transcript.is_monitored

        registry.set_monitored("test-session-001", False)
        assert not transcript.is_monitored

        await registry.stop()
        self._fw.shutdown()
