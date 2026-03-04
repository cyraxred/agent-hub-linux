"""Tests for agent_hub.services.codex_jsonl_parser module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_hub.services.codex_jsonl_parser import (
    GlobalStatsParseResult,
    ParseResult,
    parse_for_global_stats,
    parse_new_lines,
    parse_session_file,
)


# ---------- parse_new_lines ----------


class TestParseNewLines:
    """Tests for parse_new_lines() with Codex-format JSONL."""

    def test_user_message(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hello"}],
                },
            }),
        ]
        parse_new_lines(lines, result)
        assert result.message_count == 1
        assert result.session_started_at is not None

    def test_assistant_message_with_usage(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "assistant",
                    "model": "o4-mini",
                    "content": [{"type": "text", "text": "Hi!"}],
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 200,
                        "cache_read_input_tokens": 300,
                        "cache_creation_input_tokens": 50,
                    },
                },
            }),
        ]
        parse_new_lines(lines, result)
        assert result.model == "o4-mini"
        assert result.last_input_tokens == 1000
        assert result.last_output_tokens == 200
        assert result.total_input_tokens == 1000
        assert result.total_output_tokens == 200
        assert result.cache_read_tokens == 300
        assert result.cache_creation_tokens == 50

    def test_tool_use_and_result(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "shell",
                            "input": {"command": "ls"},
                        }
                    ],
                },
            }),
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:05Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": "file1.py\nfile2.py",
                            "is_error": False,
                        }
                    ],
                },
            }),
        ]
        parse_new_lines(lines, result)
        assert result.tool_calls.get("shell", 0) == 1
        assert "t1" not in result.pending_tool_uses

    def test_tool_result_error(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t_err",
                            "name": "shell",
                            "input": {"command": "bad_cmd"},
                        }
                    ],
                },
            }),
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:02Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t_err",
                            "content": "command not found",
                            "is_error": True,
                        }
                    ],
                },
            }),
        ]
        parse_new_lines(lines, result)
        fail_acts = [
            a for a in result.recent_activities
            if a.type.kind == "tool_result" and not a.type.success  # type: ignore[union-attr]
        ]
        assert len(fail_acts) >= 1

    def test_thinking_block(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Let me think..."},
                    ],
                },
            }),
        ]
        parse_new_lines(lines, result)
        thinking_acts = [a for a in result.recent_activities if a.type.kind == "thinking"]
        assert len(thinking_acts) >= 1

    def test_empty_lines_ignored(self) -> None:
        result = ParseResult()
        lines = ["", "  ", "\n", "invalid json"]
        parse_new_lines(lines, result)
        assert result.message_count == 0

    def test_non_dict_entry_ignored(self) -> None:
        result = ParseResult()
        lines = ["[1, 2, 3]", '"just a string"']
        parse_new_lines(lines, result)
        assert result.message_count == 0

    def test_entry_without_message_ignored(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({"type": "system", "timestamp": "2025-06-15T10:30:00Z"}),
        ]
        parse_new_lines(lines, result)
        assert result.message_count == 0

    def test_user_message_without_content_list(self) -> None:
        """User message where content is not a list."""
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "user",
                    "content": "plain text",
                },
            }),
        ]
        parse_new_lines(lines, result)
        assert result.message_count == 1

    def test_assistant_message_without_content_list(self) -> None:
        """Assistant message where content is not a list."""
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "assistant",
                    "content": "plain text",
                },
            }),
        ]
        parse_new_lines(lines, result)
        assistant_acts = [
            a for a in result.recent_activities if a.type.kind == "assistant_message"
        ]
        assert len(assistant_acts) >= 1

    def test_camelcase_usage_keys(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "resp"}],
                    "usage": {
                        "inputTokens": 800,
                        "outputTokens": 150,
                        "cacheReadInputTokens": 300,
                        "cacheCreationInputTokens": 50,
                    },
                },
            }),
        ]
        parse_new_lines(lines, result)
        assert result.last_input_tokens == 800
        assert result.last_output_tokens == 150

    def test_session_started_at_set_once(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-10T08:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "first"}]},
            }),
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-10T09:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "second"}]},
            }),
        ]
        parse_new_lines(lines, result)
        assert result.session_started_at is not None
        assert result.session_started_at.hour == 8

    def test_accumulates_output_tokens(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "r1"}],
                    "usage": {"input_tokens": 500, "output_tokens": 100},
                },
            }),
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:31:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "r2"}],
                    "usage": {"input_tokens": 600, "output_tokens": 200},
                },
            }),
        ]
        parse_new_lines(lines, result)
        assert result.total_output_tokens == 300
        assert result.total_input_tokens == 1100
        assert result.last_input_tokens == 600


# ---------- parse_session_file ----------


class TestParseSessionFile:
    """Tests for parse_session_file()."""

    def test_parse_file(self, tmp_path: Path) -> None:
        session_file = tmp_path / "test_session.jsonl"
        content = json.dumps({
            "type": "message",
            "timestamp": "2025-06-15T10:30:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            },
        })
        session_file.write_text(content + "\n")
        result = parse_session_file(str(session_file))
        assert result.message_count == 1

    def test_parse_nonexistent_file(self) -> None:
        result = parse_session_file("/nonexistent/path.jsonl")
        assert result.message_count == 0
        assert result.model == ""

    def test_parse_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        result = parse_session_file(str(f))
        assert result.message_count == 0


# ---------- parse_for_global_stats ----------


class TestParseForGlobalStats:
    """Tests for parse_for_global_stats()."""

    def test_counts_messages_and_tokens(self, tmp_path: Path) -> None:
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:30:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hello"}],
                },
            }),
            json.dumps({
                "type": "message",
                "timestamp": "2025-06-15T10:31:00Z",
                "message": {
                    "role": "assistant",
                    "model": "o4-mini",
                    "content": [{"type": "text", "text": "Hi"}],
                    "usage": {
                        "input_tokens": 500,
                        "output_tokens": 100,
                        "cache_read_input_tokens": 50,
                    },
                },
            }),
        ]
        f.write_text("\n".join(lines) + "\n")

        result = parse_for_global_stats(str(f))
        assert result.message_count == 1  # only user messages
        assert result.model == "o4-mini"
        assert result.total_input_tokens == 500
        assert result.total_output_tokens == 100
        assert result.cache_read_tokens == 50

    def test_nonexistent_file(self) -> None:
        result = parse_for_global_stats("/nonexistent.jsonl")
        assert result.message_count == 0
        assert result.model == ""

    def test_invalid_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text("not json\n{}\n[1,2,3]\n")
        result = parse_for_global_stats(str(f))
        assert result.message_count == 0
