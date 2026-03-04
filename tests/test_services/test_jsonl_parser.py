"""Tests for agent_hub.services.session_jsonl_parser module."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_hub.services.session_jsonl_parser import (
    ParseResult,
    parse_entry,
    parse_new_lines,
    parse_session_file,
)


# ---------- parse_entry ----------


class TestParseEntry:
    """Tests for the parse_entry() function."""

    def test_valid_json_dict(self) -> None:
        line = '{"type": "message", "timestamp": "2025-06-15T10:00:00Z"}'
        result = parse_entry(line)
        assert result is not None
        assert result["type"] == "message"

    def test_empty_line(self) -> None:
        assert parse_entry("") is None
        assert parse_entry("   ") is None
        assert parse_entry("\n") is None

    def test_invalid_json(self) -> None:
        assert parse_entry("not json at all") is None
        assert parse_entry("{incomplete") is None

    def test_non_dict_json(self) -> None:
        # Valid JSON but not a dict
        assert parse_entry("[1, 2, 3]") is None
        assert parse_entry('"just a string"') is None
        assert parse_entry("42") is None
        assert parse_entry("true") is None

    def test_whitespace_stripped(self) -> None:
        line = '  {"key": "value"}  \n'
        result = parse_entry(line)
        assert result is not None
        assert result["key"] == "value"


# ---------- parse_new_lines ----------


class TestParseNewLines:
    """Tests for parse_new_lines() with realistic Claude session data."""

    def test_user_message(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "Hello"}],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        assert result.message_count == 1
        assert result.session_started_at is not None
        assert result.last_activity_at is not None
        # Should have a user_message activity
        user_activities = [a for a in result.recent_activities if a.type.kind == "user_message"]
        assert len(user_activities) >= 1

    def test_assistant_message_with_usage(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-4-20250514",
                        "content": [{"type": "text", "text": "Hello!"}],
                        "usage": {
                            "inputTokens": 1500,
                            "outputTokens": 200,
                            "cacheReadInputTokens": 500,
                            "cacheCreationInputTokens": 100,
                        },
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        assert result.model == "claude-sonnet-4-20250514"
        assert result.last_input_tokens == 1500
        assert result.last_output_tokens == 200
        assert result.total_output_tokens == 200
        assert result.cache_read_tokens == 500
        assert result.cache_creation_tokens == 100

    def test_tool_use_and_tool_result(self) -> None:
        result = ParseResult()
        lines = [
            # Tool use
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool_123",
                                "name": "Bash",
                                "input": {"command": "ls -la"},
                            }
                        ],
                    },
                }
            ),
            # Tool result
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:05Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tool_123",
                                "content": "total 0\ndrwx...",
                                "is_error": False,
                            }
                        ],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        assert result.tool_calls.get("Bash", 0) == 1
        # After tool result, the pending tool use should be removed
        assert "tool_123" not in result.pending_tool_uses

        # Should have tool_use and tool_result activities
        tool_use_acts = [a for a in result.recent_activities if a.type.kind == "tool_use"]
        tool_result_acts = [a for a in result.recent_activities if a.type.kind == "tool_result"]
        assert len(tool_use_acts) >= 1
        assert len(tool_result_acts) >= 1

    def test_tool_result_error(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool_err",
                                "name": "Bash",
                                "input": {"command": "rm /"},
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:02Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tool_err",
                                "content": "Permission denied",
                                "is_error": True,
                            }
                        ],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        # Should have a tool_result activity marked as failure
        fail_acts = [
            a
            for a in result.recent_activities
            if a.type.kind == "tool_result" and not a.type.success  # type: ignore[union-attr]
        ]
        assert len(fail_acts) >= 1
        assert "failed" in fail_acts[0].description

    def test_edit_tool_creates_code_change_input(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool_edit",
                                "name": "Edit",
                                "input": {
                                    "file_path": "/src/main.py",
                                    "old_string": "hello",
                                    "new_string": "world",
                                },
                            }
                        ],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        assert "tool_edit" in result.pending_tool_uses
        pending = result.pending_tool_uses["tool_edit"]
        assert pending.code_change_input is not None
        assert pending.code_change_input.file_path == "/src/main.py"
        assert pending.code_change_input.old_string == "hello"
        assert pending.code_change_input.new_string == "world"

    def test_write_tool_creates_code_change_input(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool_write",
                                "name": "Write",
                                "input": {
                                    "file_path": "/src/new_file.py",
                                    "content": "print('new')",
                                },
                            }
                        ],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        pending = result.pending_tool_uses["tool_write"]
        assert pending.code_change_input is not None
        assert pending.code_change_input.tool_type.value == "write"

    def test_thinking_block(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "Let me think..."},
                        ],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        thinking_acts = [a for a in result.recent_activities if a.type.kind == "thinking"]
        assert len(thinking_acts) >= 1

    def test_usage_tracking_accumulates_output(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-4-20250514",
                        "content": [{"type": "text", "text": "First response"}],
                        "usage": {"inputTokens": 1000, "outputTokens": 200},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:31:00Z",
                    "message": {
                        "role": "assistant",
                        "model": "claude-sonnet-4-20250514",
                        "content": [{"type": "text", "text": "Second response"}],
                        "usage": {"inputTokens": 1500, "outputTokens": 300},
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        # last_input_tokens is the latest snapshot
        assert result.last_input_tokens == 1500
        # last_output_tokens is the latest snapshot
        assert result.last_output_tokens == 300
        # total_output_tokens accumulates
        assert result.total_output_tokens == 500  # 200 + 300

    def test_usage_with_snake_case_keys(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "resp"}],
                        "usage": {
                            "input_tokens": 800,
                            "output_tokens": 150,
                            "cache_read_input_tokens": 300,
                            "cache_creation_input_tokens": 50,
                        },
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)

        assert result.last_input_tokens == 800
        assert result.last_output_tokens == 150
        assert result.cache_read_tokens == 300
        assert result.cache_creation_tokens == 50

    def test_mermaid_detection_in_tool_input(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "t1",
                                "name": "Write",
                                "input": {
                                    "file_path": "/diagram.md",
                                    "content": "```mermaid\ngraph TD\nA-->B\n```",
                                },
                            }
                        ],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)
        assert result.has_mermaid_content is True
        assert len(result.mermaid_diagrams) == 1
        assert result.mermaid_diagrams[0].source == "graph TD\nA-->B"
        assert result.mermaid_diagrams[0].origin_tool == "Write"

    def test_mermaid_detection_in_text_block(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "Here is a diagram:\n```mermaid\nflowchart LR\n```",
                            }
                        ],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)
        assert result.has_mermaid_content is True
        assert len(result.mermaid_diagrams) == 1
        assert result.mermaid_diagrams[0].source == "flowchart LR"

    def test_plan_detection_appends_to_list(self) -> None:
        """Writing to .claude/plans/ twice produces two PlanEntry items."""
        result = ParseResult()
        for i, plan_name in enumerate(["plan-a.md", "plan-b.md"]):
            lines = [
                json.dumps(
                    {
                        "type": "message",
                        "timestamp": f"2025-06-15T10:{i:02d}:00Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": f"t{i}",
                                    "name": "Write",
                                    "input": {
                                        "file_path": f"/project/.claude/plans/{plan_name}",
                                        "content": f"Plan {i}",
                                    },
                                }
                            ],
                        },
                    }
                ),
            ]
            parse_new_lines(lines, result)

        assert len(result.plans) == 2
        assert result.plans[0].file_path.endswith("plan-a.md")
        assert result.plans[0].content == "Plan 0"
        assert result.plans[1].file_path.endswith("plan-b.md")
        assert result.plans[1].content == "Plan 1"
        # Backward-compat: latest plan
        assert result.plan_file_path.endswith("plan-b.md")
        assert result.plan_content == "Plan 1"

    def test_multiple_mermaid_diagrams(self) -> None:
        """Multiple mermaid blocks produce multiple MermaidDiagram entries."""
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:30:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "```mermaid\ngraph TD\nA-->B\n```\n"
                                    "And another:\n"
                                    "```mermaid\nsequenceDiagram\nA->>B: Hello\n```"
                                ),
                            }
                        ],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)
        assert len(result.mermaid_diagrams) == 2
        assert result.mermaid_diagrams[0].source == "graph TD\nA-->B"
        assert result.mermaid_diagrams[1].source == "sequenceDiagram\nA->>B: Hello"

    def test_empty_lines_ignored(self) -> None:
        result = ParseResult()
        lines = ["", "  ", "\n", "invalid json"]
        parse_new_lines(lines, result)
        assert result.message_count == 0
        assert len(result.recent_activities) == 0

    def test_entries_without_message_key_ignored(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps({"type": "system", "timestamp": "2025-06-15T10:30:00Z"}),
        ]
        parse_new_lines(lines, result)
        assert result.message_count == 0

    def test_incremental_parsing(self) -> None:
        """Parse some lines, then parse more, verifying accumulation."""
        result = ParseResult()

        # First batch
        batch1 = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:00:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "first"}],
                    },
                }
            ),
        ]
        parse_new_lines(batch1, result)
        assert result.message_count == 1

        # Second batch
        batch2 = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-15T10:05:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "second"}],
                    },
                }
            ),
        ]
        parse_new_lines(batch2, result)
        assert result.message_count == 2

    def test_full_session_flow(self, sample_jsonl_lines: list[str]) -> None:
        """Test parsing the full sample session from the fixture."""
        result = ParseResult()
        parse_new_lines(sample_jsonl_lines, result)

        # Only 1 real user message; tool_result user turns don't count
        assert result.message_count == 1
        assert result.model == "claude-sonnet-4-20250514"
        assert result.tool_calls.get("Edit", 0) == 1
        assert result.total_output_tokens > 0
        assert len(result.recent_activities) > 0
        assert result.session_started_at is not None

    def test_session_started_at_set_from_first_entry(self) -> None:
        result = ParseResult()
        lines = [
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-10T08:00:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "start"}],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "message",
                    "timestamp": "2025-06-10T09:00:00Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "later"}],
                    },
                }
            ),
        ]
        parse_new_lines(lines, result)
        # session_started_at should be the first timestamp
        assert result.session_started_at is not None
        assert result.session_started_at.hour == 8


# ---------- parse_session_file ----------


class TestParseSessionFile:
    """Tests for parse_session_file() with temporary files."""

    def test_parse_file(self, tmp_path: Path, sample_jsonl_lines: list[str]) -> None:
        session_file = tmp_path / "test_session.jsonl"
        session_file.write_text("\n".join(sample_jsonl_lines) + "\n")

        result = parse_session_file(str(session_file))

        assert result.model == "claude-sonnet-4-20250514"
        assert result.message_count >= 1
        assert result.total_output_tokens > 0
        assert result.tool_calls.get("Edit", 0) == 1

    def test_parse_nonexistent_file(self) -> None:
        result = parse_session_file("/nonexistent/path/session.jsonl")
        assert result.message_count == 0
        assert result.model == ""

    def test_parse_empty_file(self, tmp_path: Path) -> None:
        session_file = tmp_path / "empty.jsonl"
        session_file.write_text("")
        result = parse_session_file(str(session_file))
        assert result.message_count == 0

    def test_parse_file_with_invalid_lines(self, tmp_path: Path) -> None:
        session_file = tmp_path / "mixed.jsonl"
        content = (
            "not json\n"
            '{"type": "message", "timestamp": "2025-06-15T10:00:00Z", '
            '"message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}\n'
            "also not json\n"
        )
        session_file.write_text(content)
        result = parse_session_file(str(session_file))
        assert result.message_count == 1
