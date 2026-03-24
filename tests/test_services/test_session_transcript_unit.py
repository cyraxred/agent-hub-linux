"""Unit tests for SessionTranscript."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.services.session_jsonl_parser import ParseResult, parse_new_lines
from agent_hub.services.session_transcript import SessionTranscript


def _make_transcript(file_path: str, **kwargs) -> SessionTranscript:
    """Create a SessionTranscript with Claude defaults."""
    return SessionTranscript(
        session_id=kwargs.pop("session_id", "test-session-001"),
        file_path=file_path,
        project_path=kwargs.pop("project_path", "/home/user/project"),
        parse_fn=parse_new_lines,
        parse_result_factory=ParseResult,
        provider="claude",
        **kwargs,
    )


def _user_msg(text: str = "Hello") -> str:
    return json.dumps({
        "type": "message",
        "timestamp": "2025-06-15T10:30:00Z",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    })


def _assistant_msg(text: str = "Hi", model: str = "claude-sonnet-4-20250514") -> str:
    return json.dumps({
        "type": "message",
        "timestamp": "2025-06-15T10:30:01Z",
        "message": {
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": text}],
            "usage": {"inputTokens": 100, "outputTokens": 50},
        },
    })


class TestSessionTranscriptInitialParse:
    async def test_initial_parse_reads_full_file(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text(_user_msg() + "\n" + _assistant_msg() + "\n")

        t = _make_transcript(str(f))
        await t.do_initial_parse()

        assert t.byte_offset == f.stat().st_size
        assert t.state.message_count >= 1

    async def test_empty_file_no_crash(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text("")

        t = _make_transcript(str(f))
        await t.do_initial_parse()

        assert t.byte_offset == 0
        assert t.state.message_count == 0

    async def test_file_not_found(self, tmp_path: Path):
        f = tmp_path / "nonexistent.jsonl"

        t = _make_transcript(str(f))
        await t.notify_file_modified()  # should not raise

        assert t.byte_offset == 0


class TestSessionTranscriptDelta:
    async def test_notify_file_modified_reads_delta(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text(_user_msg() + "\n")

        t = _make_transcript(str(f))
        await t.do_initial_parse()
        initial_offset = t.byte_offset
        initial_line_count = t.line_count

        # Append more data (another user message to bump message_count)
        with open(f, "a") as fh:
            fh.write(_user_msg("Second question") + "\n")

        await t.notify_file_modified()
        assert t.byte_offset > initial_offset
        assert t.line_count > initial_line_count

    async def test_truncated_file_resets_offset(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        long_content = _user_msg() + "\n" + _assistant_msg() + "\n"
        f.write_text(long_content)

        t = _make_transcript(str(f))
        await t.do_initial_parse()
        assert t.byte_offset > 0

        # Truncate the file
        f.write_text(_user_msg("short") + "\n")

        await t.notify_file_modified()
        # offset should be reset and re-parsed
        assert t.byte_offset == f.stat().st_size

    async def test_partial_line_handling(self, tmp_path: Path):
        """File ends mid-JSON line — delta reads see the remainder.

        SessionTranscript reads bytes from byte_offset forward without
        buffering partial lines.  The partial first read and partial second
        read each fail JSON parsing individually.  A new complete line
        appended afterwards will be parsed successfully.
        """
        f = tmp_path / "session.jsonl"
        full_line = _user_msg()
        partial = full_line[:20].encode()
        f.write_bytes(partial)

        t = _make_transcript(str(f))
        await t.do_initial_parse()
        assert t.state.message_count == 0
        assert t.byte_offset == len(partial)

        # Append a new, complete line
        with open(f, "ab") as fh:
            fh.write(b"\n" + full_line.encode() + b"\n")

        await t.notify_file_modified()
        # The new complete line is parsed successfully
        assert t.state.message_count >= 1


class TestSessionTranscriptCallbacks:
    async def test_state_update_callback_fires(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text(_user_msg() + "\n")

        received: list[tuple[str, object]] = []

        async def on_update(session_id: str, state: object) -> None:
            received.append((session_id, state))

        t = _make_transcript(str(f))
        t.on_state_update(on_update)
        await t.do_initial_parse()

        assert len(received) >= 1
        assert received[0][0] == "test-session-001"

    async def test_history_append_callback_fires(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text(_user_msg() + "\n")

        received: list[tuple[str, list, int]] = []

        async def on_history(session_id: str, entries: list, total: int) -> None:
            received.append((session_id, entries, total))

        t = _make_transcript(str(f))
        t.on_history_append(on_history)
        await t.do_initial_parse()

        assert len(received) >= 1
        assert received[0][0] == "test-session-001"
        assert received[0][2] >= 1  # total_lines

    async def test_tool_result_callback_fires(self, tmp_path: Path):
        """Pending tool_use resolved → on_tool_result fires."""
        # Write assistant message with a tool_use block
        tool_msg = json.dumps({
            "type": "message",
            "timestamp": "2025-06-15T10:30:01Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-20250514",
                "content": [{
                    "type": "tool_use",
                    "id": "tu_123",
                    "name": "Bash",
                    "input": {"command": "ls"},
                }],
                "usage": {"inputTokens": 100, "outputTokens": 50},
            },
        })
        # Tool result that resolves it
        result_msg = json.dumps({
            "type": "message",
            "timestamp": "2025-06-15T10:30:02Z",
            "message": {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tu_123",
                    "content": [{"type": "text", "text": "file.txt"}],
                }],
            },
        })

        f = tmp_path / "session.jsonl"
        f.write_text(tool_msg + "\n")

        resolved: list[tuple[str, str]] = []

        async def on_tool(session_id: str, tool_use_id: str) -> None:
            resolved.append((session_id, tool_use_id))

        t = _make_transcript(str(f))
        t.on_tool_result(on_tool)
        await t.do_initial_parse()

        # Now append the result
        with open(f, "a") as fh:
            fh.write(result_msg + "\n")

        await t.notify_file_modified()

        assert any(tid == "tu_123" for _, tid in resolved)


class TestSessionTranscriptStatusTimeout:
    async def test_check_status_timeout(self, tmp_path: Path):
        from agent_hub.models.monitor_state import SessionStatusThinking

        f = tmp_path / "session.jsonl"
        f.write_text(_user_msg() + "\n")

        t = _make_transcript(str(f))
        await t.do_initial_parse()

        # Manually set to non-idle so timeout can trigger the transition
        t.state.status = SessionStatusThinking()

        from datetime import timedelta
        future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        changed = t.check_status_timeout(future)
        # With recent activities and far-future time, should transition to idle
        if t.parse_result.recent_activities:
            assert changed is True
            assert t.state.status.kind == "idle"
