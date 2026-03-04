"""Session models ported from Swift CLISession.swift."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field


class CLISessionSourceType(StrEnum):
    """Source type for CLI sessions."""

    claw = "Claw"
    cli = "CLI"


class CLISession(BaseModel, frozen=True):
    """Represents a single CLI session."""

    id: str
    project_path: str
    branch_name: str | None = None
    is_worktree: bool = False
    last_activity_at: datetime
    message_count: int = 0
    is_active: bool = False
    first_message: str = ""
    last_message: str = ""
    slug: str = ""
    session_file_path: str = ""
    needs_attention: str | None = None
    """None, 'approval' (pending tool permission), or 'question' (agent asked a question)."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def short_id(self) -> str:
        """First 8 characters of the session ID."""
        return self.id[:8]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        """Display name: slug if available, otherwise short_id."""
        return self.slug if self.slug else self.short_id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def project_name(self) -> str:
        """Last path component of the project path."""
        return PurePosixPath(self.project_path).name


class WorktreeBranch(BaseModel, frozen=True):
    """Represents a worktree branch with its sessions."""

    name: str
    path: str
    is_worktree: bool = False
    sessions: list[CLISession] = Field(default_factory=list)
    is_expanded: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_session_count(self) -> int:
        """Number of active sessions in this branch."""
        return sum(1 for s in self.sessions if s.is_active)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def last_activity_at(self) -> datetime | None:
        """Most recent activity across all sessions."""
        if not self.sessions:
            return None
        return max(s.last_activity_at for s in self.sessions)


class SelectedRepository(BaseModel, frozen=True):
    """Represents a selected repository with its worktrees."""

    path: str
    name: str
    worktrees: list[WorktreeBranch] = Field(default_factory=list)
    is_expanded: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_session_count(self) -> int:
        """Total number of sessions across all worktrees."""
        return sum(len(w.sessions) for w in self.worktrees)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_session_count(self) -> int:
        """Number of active sessions across all worktrees."""
        return sum(w.active_session_count for w in self.worktrees)


class CLISessionGroup(BaseModel, frozen=True):
    """Group of sessions for a project."""

    project_path: str
    project_name: str
    sessions: list[CLISession] = Field(default_factory=list)
    is_worktree: bool = False
    main_repo_path: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_session_count(self) -> int:
        """Number of active sessions in this group."""
        return sum(1 for s in self.sessions if s.is_active)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_session_count(self) -> int:
        """Total number of sessions in this group."""
        return len(self.sessions)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def last_activity_at(self) -> datetime | None:
        """Most recent activity across all sessions."""
        if not self.sessions:
            return None
        return max(s.last_activity_at for s in self.sessions)


class HistoryEntry(BaseModel, frozen=True):
    """A single history entry."""

    display: str
    timestamp: int
    project: str
    session_id: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def date(self) -> datetime:
        """Convert millisecond timestamp to datetime."""
        return datetime.fromtimestamp(self.timestamp / 1000.0, tz=timezone.utc)


# --- CLILoadingState tagged union ---


class CLILoadingStateIdle(BaseModel, frozen=True):
    """Loading state: idle."""

    kind: Literal["idle"] = "idle"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_loading(self) -> bool:
        return False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        return ""


class CLILoadingStateRestoringRepositories(BaseModel, frozen=True):
    """Loading state: restoring repositories."""

    kind: Literal["restoring_repositories"] = "restoring_repositories"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_loading(self) -> bool:
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        return "Restoring repositories..."


class CLILoadingStateRestoringMonitoredSessions(BaseModel, frozen=True):
    """Loading state: restoring monitored sessions."""

    kind: Literal["restoring_monitored_sessions"] = "restoring_monitored_sessions"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_loading(self) -> bool:
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        return "Restoring monitored sessions..."


class CLILoadingStateAddingRepository(BaseModel, frozen=True):
    """Loading state: adding a repository."""

    kind: Literal["adding_repository"] = "adding_repository"
    name: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_loading(self) -> bool:
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        return f"Adding {self.name}..."


class CLILoadingStateDetectingWorktrees(BaseModel, frozen=True):
    """Loading state: detecting worktrees."""

    kind: Literal["detecting_worktrees"] = "detecting_worktrees"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_loading(self) -> bool:
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        return "Detecting worktrees..."


class CLILoadingStateScanningSessionsState(BaseModel, frozen=True):
    """Loading state: scanning sessions."""

    kind: Literal["scanning_sessions"] = "scanning_sessions"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_loading(self) -> bool:
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        return "Scanning sessions..."


class CLILoadingStateRefreshing(BaseModel, frozen=True):
    """Loading state: refreshing."""

    kind: Literal["refreshing"] = "refreshing"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_loading(self) -> bool:
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        return "Refreshing..."


CLILoadingState = Annotated[
    CLILoadingStateIdle
    | CLILoadingStateRestoringRepositories
    | CLILoadingStateRestoringMonitoredSessions
    | CLILoadingStateAddingRepository
    | CLILoadingStateDetectingWorktrees
    | CLILoadingStateScanningSessionsState
    | CLILoadingStateRefreshing,
    Field(discriminator="kind"),
]
