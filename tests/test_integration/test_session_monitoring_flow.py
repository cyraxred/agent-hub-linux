"""Integration test: session monitoring end-to-end flow.

Creates a temporary directory structure mimicking ~/.claude/,
starts a transcript registry, appends JSONL lines,
and verifies that state updates propagate correctly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.services.path_utils import encode_project_path
from agent_hub.services.session_jsonl_parser import ParseResult, parse_new_lines
from agent_hub.services.transcript_registry import TranscriptRegistry
from agent_hub.services.file_watcher import FileWatcher


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


def _make_registry(tmp_path: Path) -> tuple[TranscriptRegistry, FileWatcher]:
    """Create a TranscriptRegistry with its own FileWatcher."""
    fw = FileWatcher()
    fw.set_loop(asyncio.get_event_loop())
    registry = TranscriptRegistry(
        provider="claude",
        parse_fn=parse_new_lines,
        parse_result_factory=ParseResult,
        approval_timeout_seconds=5,
        file_watcher=fw,
    )
    return registry, fw


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

    async def test_registry_reads_initial_content(
        self, claude_dir: Path, repo_dir: Path, tmp_path: Path
    ) -> None:
        """Register a transcript and verify it reads existing content."""
        repo_path = str(repo_dir)
        session_id = "watcher-init-test"

        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("First message") + "\n"
            + _jsonl_assistant_message("Response", model="claude-opus-4-20250514") + "\n"
        )

        registry, fw = _make_registry(tmp_path)

        transcript = await registry.register_transcript(
            session_id=session_id,
            project_path=repo_path,
            file_path=str(session_file),
        )

        assert transcript.state.message_count == 1
        assert transcript.state.model == "claude-opus-4-20250514"
        assert transcript.state.output_tokens == 200

        await registry.stop()
        fw.shutdown()

    async def test_append_lines_and_verify_state_updates(
        self, claude_dir: Path, repo_dir: Path, tmp_path: Path
    ) -> None:
        """Register transcript, append new lines, refresh and verify."""
        repo_path = str(repo_dir)
        session_id = "append-test-session"

        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("Initial message", "2025-06-15T10:00:00Z") + "\n"
        )

        received_updates: list[tuple[str, SessionMonitorState]] = []

        async def on_state_update(sid: str, state: SessionMonitorState) -> None:
            received_updates.append((sid, state))

        registry, fw = _make_registry(tmp_path)
        registry.on_state_update(on_state_update)

        transcript = await registry.register_transcript(
            session_id=session_id,
            project_path=repo_path,
            file_path=str(session_file),
        )

        assert transcript.state.message_count == 1

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

        await transcript.refresh()

        assert transcript.state.message_count >= 1
        assert transcript.state.model == "claude-sonnet-4-20250514"
        assert transcript.state.total_output_tokens >= 300
        assert transcript.state.tool_calls.get("Edit", 0) >= 1

        tool_use_acts = [
            a for a in transcript.state.recent_activities if a.type.kind == "tool_use"
        ]
        assert len(tool_use_acts) >= 1

        await registry.stop()
        fw.shutdown()

    async def test_full_flow_registry(
        self, claude_dir: Path, repo_dir: Path, tmp_path: Path
    ) -> None:
        """Full integration: registry discovers and tracks sessions."""
        repo_path = str(repo_dir)
        session_id = "full-flow-session"

        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("Start coding", "2025-06-15T09:00:00Z") + "\n"
            + _jsonl_assistant_message(
                "Ready to help!", "2025-06-15T09:00:05Z", model="claude-sonnet-4-20250514"
            ) + "\n"
        )

        # Register transcript
        registry, fw = _make_registry(tmp_path)
        transcript = await registry.register_transcript(
            session_id=session_id,
            project_path=repo_path,
            file_path=str(session_file),
        )

        assert transcript.state.model == "claude-sonnet-4-20250514"
        assert transcript.state.message_count == 1

        # Append more data and refresh
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

        await transcript.refresh()
        assert transcript.state.message_count == 2
        assert transcript.state.total_output_tokens == 700  # 200 + 500

        await registry.stop()
        fw.shutdown()

    async def test_registry_stop_and_cleanup(
        self, claude_dir: Path, repo_dir: Path, tmp_path: Path
    ) -> None:
        """Stop registry and verify state is cleaned up."""
        repo_path = str(repo_dir)
        session_id = "cleanup-test"
        session_file = self._setup_session_file(claude_dir, repo_path, session_id)
        session_file.write_text(
            _jsonl_user_message("test") + "\n"
        )

        registry, fw = _make_registry(tmp_path)
        await registry.register_transcript(
            session_id=session_id,
            project_path=repo_path,
            file_path=str(session_file),
        )

        assert registry.get_transcript(session_id) is not None

        await registry.stop()
        assert registry.get_transcript(session_id) is None

        fw.shutdown()
