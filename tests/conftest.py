"""Shared pytest fixtures for agent-hub tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture()
def claude_dir(tmp_path: Path) -> Path:
    """Create a fake ~/.claude directory structure."""
    projects = tmp_path / "projects"
    projects.mkdir()
    return tmp_path


@pytest.fixture()
def sample_jsonl_lines() -> list[str]:
    """Return realistic Claude session JSONL lines for parsing tests."""
    ts = "2025-06-15T10:30:00Z"
    ts2 = "2025-06-15T10:30:05Z"
    ts3 = "2025-06-15T10:30:10Z"
    ts4 = "2025-06-15T10:30:15Z"
    ts5 = "2025-06-15T10:30:20Z"

    lines = [
        # User message
        json.dumps(
            {
                "type": "message",
                "timestamp": ts,
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Hello, please help me fix a bug."}],
                },
            }
        ),
        # Assistant response with thinking + text
        json.dumps(
            {
                "type": "message",
                "timestamp": ts2,
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-20250514",
                    "content": [
                        {"type": "thinking", "thinking": "Let me analyze this..."},
                        {"type": "text", "text": "I'll look into the bug."},
                    ],
                    "usage": {
                        "inputTokens": 1500,
                        "outputTokens": 200,
                        "cacheReadInputTokens": 500,
                        "cacheCreationInputTokens": 100,
                    },
                },
            }
        ),
        # Assistant with tool_use (Edit)
        json.dumps(
            {
                "type": "message",
                "timestamp": ts3,
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-20250514",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_001",
                            "name": "Edit",
                            "input": {
                                "file_path": "/home/user/project/main.py",
                                "old_string": "print('old')",
                                "new_string": "print('new')",
                            },
                        }
                    ],
                    "usage": {
                        "inputTokens": 2000,
                        "outputTokens": 150,
                        "cacheReadInputTokens": 800,
                        "cacheCreationInputTokens": 50,
                    },
                },
            }
        ),
        # Tool result
        json.dumps(
            {
                "type": "message",
                "timestamp": ts4,
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_001",
                            "content": "File edited successfully.",
                            "is_error": False,
                        }
                    ],
                },
            }
        ),
        # Assistant final message
        json.dumps(
            {
                "type": "message",
                "timestamp": ts5,
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-20250514",
                    "content": [
                        {"type": "text", "text": "I've fixed the bug. The change was applied."}
                    ],
                    "usage": {
                        "inputTokens": 2500,
                        "outputTokens": 100,
                        "cacheReadInputTokens": 1200,
                        "cacheCreationInputTokens": 0,
                    },
                },
            }
        ),
    ]
    return lines
