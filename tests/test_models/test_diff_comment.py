"""Tests for agent_hub.models.diff_comment module."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from agent_hub.models.diff_comment import DiffComment


# ---------- DiffComment ----------


class TestDiffComment:
    """Tests for the DiffComment model."""

    def test_creation(self) -> None:
        now = datetime.now(tz=timezone.utc)
        comment = DiffComment(
            timestamp=now,
            file_path="/src/main.py",
            line_number=42,
            side="right",
            line_content="    return result",
            text="This should handle None",
        )
        assert comment.file_path == "/src/main.py"
        assert comment.line_number == 42
        assert comment.side == "right"
        assert comment.line_content == "    return result"
        assert comment.text == "This should handle None"
        assert isinstance(comment.id, UUID)
        assert isinstance(comment.timestamp, datetime)

    def test_location_key(self) -> None:
        now = datetime.now(tz=timezone.utc)
        comment = DiffComment(
            timestamp=now,
            file_path="/src/main.py",
            line_number=42,
            side="right",
        )
        assert comment.location_key == "/src/main.py:42:right"

    def test_location_key_left_side(self) -> None:
        now = datetime.now(tz=timezone.utc)
        comment = DiffComment(
            timestamp=now,
            file_path="/test.py",
            line_number=1,
            side="left",
        )
        assert comment.location_key == "/test.py:1:left"

    def test_location_key_unified(self) -> None:
        now = datetime.now(tz=timezone.utc)
        comment = DiffComment(
            timestamp=now,
            file_path="/a.py",
            line_number=100,
            side="unified",
        )
        assert comment.location_key == "/a.py:100:unified"

    def test_defaults(self) -> None:
        now = datetime.now(tz=timezone.utc)
        comment = DiffComment(
            timestamp=now,
            file_path="/test.py",
            line_number=1,
            side="right",
        )
        assert comment.line_content == ""
        assert comment.text == ""

    def test_frozen(self) -> None:
        now = datetime.now(tz=timezone.utc)
        comment = DiffComment(
            timestamp=now,
            file_path="/test.py",
            line_number=1,
            side="right",
        )
        with pytest.raises(Exception):
            comment.text = "new text"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(tz=timezone.utc)
        comment = DiffComment(
            timestamp=now,
            file_path="/src/main.py",
            line_number=42,
            side="right",
            text="Review this",
        )
        data = comment.model_dump()
        assert data["location_key"] == "/src/main.py:42:right"

        restored = DiffComment.model_validate(data)
        assert restored.file_path == "/src/main.py"
        assert restored.location_key == "/src/main.py:42:right"

    def test_side_literal_values(self) -> None:
        now = datetime.now(tz=timezone.utc)
        for side in ["left", "right", "unified"]:
            comment = DiffComment(
                timestamp=now,
                file_path="/f.py",
                line_number=1,
                side=side,  # type: ignore[arg-type]
            )
            assert comment.side == side
