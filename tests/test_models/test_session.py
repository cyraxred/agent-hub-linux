"""Tests for agent_hub.models.session module."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter

from agent_hub.models.session import (
    CLILoadingState,
    CLILoadingStateAddingRepository,
    CLILoadingStateDetectingWorktrees,
    CLILoadingStateIdle,
    CLILoadingStateRefreshing,
    CLILoadingStateRestoringMonitoredSessions,
    CLILoadingStateRestoringRepositories,
    CLILoadingStateScanningSessionsState,
    CLISession,
    CLISessionGroup,
    HistoryEntry,
    SelectedRepository,
    WorktreeBranch,
)


# ---------- CLISession ----------


class TestCLISession:
    """Tests for the CLISession model."""

    @pytest.fixture()
    def session(self) -> CLISession:
        return CLISession(
            id="abcdef1234567890abcdef1234567890",
            project_path="/home/user/projects/my-app",
            branch_name="feature/auth",
            is_worktree=False,
            last_activity_at=datetime(2025, 6, 15, 10, 30, tzinfo=timezone.utc),
            message_count=5,
            is_active=True,
            first_message="Help me fix a bug",
            last_message="Done!",
            slug="fix-auth-bug",
            session_file_path="/home/user/.claude/projects/-home-user-projects-my-app/abcdef12.jsonl",
        )

    def test_creation(self, session: CLISession) -> None:
        assert session.id == "abcdef1234567890abcdef1234567890"
        assert session.project_path == "/home/user/projects/my-app"
        assert session.branch_name == "feature/auth"
        assert session.is_active is True
        assert session.message_count == 5

    def test_short_id(self, session: CLISession) -> None:
        assert session.short_id == "abcdef12"

    def test_display_name_with_slug(self, session: CLISession) -> None:
        assert session.display_name == "fix-auth-bug"

    def test_display_name_without_slug(self) -> None:
        s = CLISession(
            id="abcdef1234567890",
            project_path="/tmp/proj",
            last_activity_at=datetime.now(tz=timezone.utc),
            slug="",
        )
        assert s.display_name == "abcdef12"

    def test_project_name(self, session: CLISession) -> None:
        assert session.project_name == "my-app"

    def test_project_name_root(self) -> None:
        s = CLISession(
            id="0000000000000000",
            project_path="/",
            last_activity_at=datetime.now(tz=timezone.utc),
        )
        # PurePosixPath("/").name returns ""
        assert s.project_name == ""

    def test_serialization_roundtrip(self, session: CLISession) -> None:
        data = session.model_dump()
        assert data["id"] == session.id
        assert data["short_id"] == "abcdef12"
        assert data["display_name"] == "fix-auth-bug"
        assert data["project_name"] == "my-app"

        restored = CLISession.model_validate(data)
        assert restored.id == session.id
        assert restored.project_path == session.project_path
        assert restored.short_id == session.short_id

    def test_frozen(self, session: CLISession) -> None:
        with pytest.raises(Exception):
            session.id = "new_id"  # type: ignore[misc]

    def test_defaults(self) -> None:
        s = CLISession(
            id="1234567890abcdef",
            project_path="/tmp/x",
            last_activity_at=datetime.now(tz=timezone.utc),
        )
        assert s.branch_name is None
        assert s.is_worktree is False
        assert s.message_count == 0
        assert s.is_active is False
        assert s.first_message == ""
        assert s.last_message == ""
        assert s.slug == ""
        assert s.session_file_path == ""


# ---------- WorktreeBranch ----------


class TestWorktreeBranch:
    """Tests for the WorktreeBranch model."""

    @pytest.fixture()
    def branch(self) -> WorktreeBranch:
        now = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
        sessions = [
            CLISession(
                id="sess_active",
                project_path="/repo",
                last_activity_at=now,
                is_active=True,
            ),
            CLISession(
                id="sess_inactive",
                project_path="/repo",
                last_activity_at=datetime(2025, 6, 14, 12, 0, tzinfo=timezone.utc),
                is_active=False,
            ),
        ]
        return WorktreeBranch(
            name="main",
            path="/repo",
            sessions=sessions,
            is_expanded=True,
        )

    def test_active_session_count(self, branch: WorktreeBranch) -> None:
        assert branch.active_session_count == 1

    def test_last_activity_at(self, branch: WorktreeBranch) -> None:
        assert branch.last_activity_at == datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)

    def test_last_activity_at_empty(self) -> None:
        b = WorktreeBranch(name="empty", path="/empty")
        assert b.last_activity_at is None

    def test_serialization(self, branch: WorktreeBranch) -> None:
        data = branch.model_dump()
        assert data["active_session_count"] == 1
        assert data["name"] == "main"
        assert len(data["sessions"]) == 2

        restored = WorktreeBranch.model_validate(data)
        assert restored.active_session_count == 1


# ---------- SelectedRepository ----------


class TestSelectedRepository:
    """Tests for the SelectedRepository model."""

    def test_total_and_active_counts(self) -> None:
        now = datetime.now(tz=timezone.utc)
        sessions1 = [
            CLISession(id="s1", project_path="/r", last_activity_at=now, is_active=True),
            CLISession(id="s2", project_path="/r", last_activity_at=now, is_active=False),
        ]
        sessions2 = [
            CLISession(id="s3", project_path="/r", last_activity_at=now, is_active=True),
        ]
        repo = SelectedRepository(
            path="/repo",
            name="repo",
            worktrees=[
                WorktreeBranch(name="main", path="/repo", sessions=sessions1),
                WorktreeBranch(name="feature", path="/repo/wt", sessions=sessions2),
            ],
        )
        assert repo.total_session_count == 3
        assert repo.active_session_count == 2

    def test_empty_repo(self) -> None:
        repo = SelectedRepository(path="/empty", name="empty")
        assert repo.total_session_count == 0
        assert repo.active_session_count == 0

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(tz=timezone.utc)
        repo = SelectedRepository(
            path="/repo",
            name="my-repo",
            worktrees=[
                WorktreeBranch(
                    name="main",
                    path="/repo",
                    sessions=[
                        CLISession(id="s1", project_path="/repo", last_activity_at=now),
                    ],
                ),
            ],
            is_expanded=True,
        )
        data = repo.model_dump()
        assert data["total_session_count"] == 1
        restored = SelectedRepository.model_validate(data)
        assert restored.total_session_count == 1
        assert restored.path == "/repo"


# ---------- CLISessionGroup ----------


class TestCLISessionGroup:
    """Tests for the CLISessionGroup model."""

    def test_computed_fields(self) -> None:
        now = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
        older = datetime(2025, 6, 14, 10, 0, tzinfo=timezone.utc)
        group = CLISessionGroup(
            project_path="/proj",
            project_name="proj",
            sessions=[
                CLISession(id="s1", project_path="/proj", last_activity_at=now, is_active=True),
                CLISession(id="s2", project_path="/proj", last_activity_at=older, is_active=False),
                CLISession(id="s3", project_path="/proj", last_activity_at=older, is_active=True),
            ],
        )
        assert group.active_session_count == 2
        assert group.total_session_count == 3
        assert group.last_activity_at == now

    def test_empty_group(self) -> None:
        group = CLISessionGroup(project_path="/x", project_name="x")
        assert group.active_session_count == 0
        assert group.total_session_count == 0
        assert group.last_activity_at is None


# ---------- HistoryEntry ----------


class TestHistoryEntry:
    """Tests for the HistoryEntry model."""

    def test_date_computation_from_ms_timestamp(self) -> None:
        # 1718444400000 ms = 2024-06-15 11:00:00 UTC
        entry = HistoryEntry(
            display="Fix the login bug",
            timestamp=1718444400000,
            project="/home/user/proj",
            session_id="sess-001",
        )
        d = entry.date
        assert d.year == 2024
        assert d.month == 6
        assert d.day == 15
        assert d.tzinfo is not None

    def test_date_computation_epoch(self) -> None:
        entry = HistoryEntry(
            display="test",
            timestamp=0,
            project="/x",
            session_id="s0",
        )
        assert entry.date == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_serialization(self) -> None:
        entry = HistoryEntry(
            display="hello",
            timestamp=1718444400000,
            project="/proj",
            session_id="s1",
        )
        data = entry.model_dump()
        assert data["display"] == "hello"
        assert data["timestamp"] == 1718444400000
        assert "date" in data

        restored = HistoryEntry.model_validate(data)
        assert restored.session_id == "s1"


# ---------- CLILoadingState ----------


class TestCLILoadingState:
    """Tests for the CLILoadingState discriminated union."""

    def test_idle(self) -> None:
        state = CLILoadingStateIdle()
        assert state.kind == "idle"
        assert state.is_loading is False
        assert state.message == ""

    def test_restoring_repositories(self) -> None:
        state = CLILoadingStateRestoringRepositories()
        assert state.kind == "restoring_repositories"
        assert state.is_loading is True
        assert state.message == "Restoring repositories..."

    def test_restoring_monitored_sessions(self) -> None:
        state = CLILoadingStateRestoringMonitoredSessions()
        assert state.kind == "restoring_monitored_sessions"
        assert state.is_loading is True
        assert state.message == "Restoring monitored sessions..."

    def test_adding_repository(self) -> None:
        state = CLILoadingStateAddingRepository(name="my-repo")
        assert state.kind == "adding_repository"
        assert state.is_loading is True
        assert state.message == "Adding my-repo..."

    def test_detecting_worktrees(self) -> None:
        state = CLILoadingStateDetectingWorktrees()
        assert state.kind == "detecting_worktrees"
        assert state.is_loading is True
        assert state.message == "Detecting worktrees..."

    def test_scanning_sessions(self) -> None:
        state = CLILoadingStateScanningSessionsState()
        assert state.kind == "scanning_sessions"
        assert state.is_loading is True
        assert state.message == "Scanning sessions..."

    def test_refreshing(self) -> None:
        state = CLILoadingStateRefreshing()
        assert state.kind == "refreshing"
        assert state.is_loading is True
        assert state.message == "Refreshing..."

    def test_discriminated_union_serialization(self) -> None:
        adapter = TypeAdapter(CLILoadingState)

        idle = CLILoadingStateIdle()
        data = adapter.dump_python(idle)
        restored = adapter.validate_python(data)
        assert restored.kind == "idle"
        assert restored.is_loading is False

        adding = CLILoadingStateAddingRepository(name="test-repo")
        data2 = adapter.dump_python(adding)
        restored2 = adapter.validate_python(data2)
        assert restored2.kind == "adding_repository"
        assert restored2.message == "Adding test-repo..."  # type: ignore[union-attr]

    def test_all_variants_via_discriminator(self) -> None:
        adapter = TypeAdapter(CLILoadingState)
        variants = [
            {"kind": "idle"},
            {"kind": "restoring_repositories"},
            {"kind": "restoring_monitored_sessions"},
            {"kind": "adding_repository", "name": "X"},
            {"kind": "detecting_worktrees"},
            {"kind": "scanning_sessions"},
            {"kind": "refreshing"},
        ]
        for v in variants:
            parsed = adapter.validate_python(v)
            assert parsed.kind == v["kind"]
