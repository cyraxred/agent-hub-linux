"""Tests for agent_hub.models.search module."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_hub.models.search import (
    SearchMatchField,
    SessionIndexEntry,
    SessionSearchResult,
)


# ---------- SearchMatchField ----------


class TestSearchMatchField:
    """Tests for the SearchMatchField enum and its properties."""

    def test_values(self) -> None:
        assert SearchMatchField.slug == "slug"
        assert SearchMatchField.summary == "summary"
        assert SearchMatchField.path == "path"
        assert SearchMatchField.git_branch == "git_branch"
        assert SearchMatchField.first_message == "first_message"

    def test_icon_name_slug(self) -> None:
        assert SearchMatchField.slug.icon_name == "tag"

    def test_icon_name_summary(self) -> None:
        assert SearchMatchField.summary.icon_name == "doc.text"

    def test_icon_name_path(self) -> None:
        assert SearchMatchField.path.icon_name == "folder"

    def test_icon_name_git_branch(self) -> None:
        assert SearchMatchField.git_branch.icon_name == "arrow.triangle.branch"

    def test_icon_name_first_message(self) -> None:
        assert SearchMatchField.first_message.icon_name == "text.bubble"

    def test_display_label_slug(self) -> None:
        assert SearchMatchField.slug.display_label == "Slug"

    def test_display_label_summary(self) -> None:
        assert SearchMatchField.summary.display_label == "Summary"

    def test_display_label_path(self) -> None:
        assert SearchMatchField.path.display_label == "Path"

    def test_display_label_git_branch(self) -> None:
        assert SearchMatchField.git_branch.display_label == "Branch"

    def test_display_label_first_message(self) -> None:
        assert SearchMatchField.first_message.display_label == "First Message"

    def test_all_fields_have_icon_and_label(self) -> None:
        """Ensure every field has non-empty icon_name and display_label."""
        for field in SearchMatchField:
            assert len(field.icon_name) > 0
            assert len(field.display_label) > 0


# ---------- SessionIndexEntry ----------


class TestSessionIndexEntry:
    """Tests for the SessionIndexEntry model."""

    def test_creation(self) -> None:
        now = datetime.now(tz=timezone.utc)
        entry = SessionIndexEntry(
            session_id="sess-001",
            project_path="/home/user/project",
            slug="fix-bug",
            git_branch="feature/auth",
            first_message="Help me fix this",
            summaries=["Fixed the auth bug", "Updated tests"],
            last_activity_at=now,
        )
        assert entry.session_id == "sess-001"
        assert entry.project_path == "/home/user/project"
        assert entry.slug == "fix-bug"
        assert entry.git_branch == "feature/auth"
        assert entry.first_message == "Help me fix this"
        assert len(entry.summaries) == 2

    def test_defaults(self) -> None:
        now = datetime.now(tz=timezone.utc)
        entry = SessionIndexEntry(
            session_id="s1",
            project_path="/p",
            last_activity_at=now,
        )
        assert entry.slug == ""
        assert entry.git_branch == ""
        assert entry.first_message == ""
        assert entry.summaries == []

    def test_serialization(self) -> None:
        now = datetime.now(tz=timezone.utc)
        entry = SessionIndexEntry(
            session_id="s1",
            project_path="/p",
            last_activity_at=now,
        )
        data = entry.model_dump()
        restored = SessionIndexEntry.model_validate(data)
        assert restored.session_id == "s1"


# ---------- SessionSearchResult ----------


class TestSessionSearchResult:
    """Tests for the SessionSearchResult model."""

    def test_creation(self) -> None:
        now = datetime.now(tz=timezone.utc)
        result = SessionSearchResult(
            id="sess-001",
            slug="fix-bug",
            project_path="/home/user/my-project",
            git_branch="main",
            first_message="Hello",
            summaries=["Summary"],
            last_activity_at=now,
            matched_field=SearchMatchField.slug,
            matched_text="fix-bug",
            relevance_score=95.0,
        )
        assert result.id == "sess-001"
        assert result.matched_field == SearchMatchField.slug
        assert result.relevance_score == 95.0

    def test_repository_name(self) -> None:
        now = datetime.now(tz=timezone.utc)
        result = SessionSearchResult(
            id="s1",
            project_path="/home/user/my-project",
            last_activity_at=now,
            matched_field=SearchMatchField.path,
        )
        assert result.repository_name == "my-project"

    def test_repository_name_root(self) -> None:
        now = datetime.now(tz=timezone.utc)
        result = SessionSearchResult(
            id="s1",
            project_path="/",
            last_activity_at=now,
            matched_field=SearchMatchField.path,
        )
        assert result.repository_name == ""

    def test_defaults(self) -> None:
        now = datetime.now(tz=timezone.utc)
        result = SessionSearchResult(
            id="s1",
            last_activity_at=now,
            matched_field=SearchMatchField.slug,
        )
        assert result.slug == ""
        assert result.project_path == ""
        assert result.git_branch == ""
        assert result.first_message == ""
        assert result.summaries == []
        assert result.matched_text == ""
        assert result.relevance_score == 0.0

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(tz=timezone.utc)
        result = SessionSearchResult(
            id="s1",
            project_path="/proj",
            last_activity_at=now,
            matched_field=SearchMatchField.summary,
            relevance_score=80.0,
        )
        data = result.model_dump()
        assert data["repository_name"] == "proj"

        restored = SessionSearchResult.model_validate(data)
        assert restored.repository_name == "proj"
        assert restored.relevance_score == 80.0
