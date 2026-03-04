"""Worktree creation and remote branch models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field


# --- WorktreeCreationProgress tagged union ---


class WorktreeCreationProgressIdle(BaseModel, frozen=True):
    """Worktree creation is idle."""

    kind: Literal["idle"] = "idle"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_value(self) -> float:
        return 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_message(self) -> str:
        return ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_in_progress(self) -> bool:
        return False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "circle"


class WorktreeCreationProgressPreparing(BaseModel, frozen=True):
    """Worktree creation is preparing."""

    kind: Literal["preparing"] = "preparing"
    message: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_value(self) -> float:
        return 0.1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_message(self) -> str:
        return self.message if self.message else "Preparing..."

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_in_progress(self) -> bool:
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "gear"


class WorktreeCreationProgressUpdatingFiles(BaseModel, frozen=True):
    """Worktree creation is updating files."""

    kind: Literal["updating_files"] = "updating_files"
    current: int
    total: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_value(self) -> float:
        if self.total <= 0:
            return 0.5
        return 0.1 + (self.current / self.total) * 0.8

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_message(self) -> str:
        return f"Updating files ({self.current}/{self.total})..."

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_in_progress(self) -> bool:
        return True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "doc.on.doc"


class WorktreeCreationProgressCompleted(BaseModel, frozen=True):
    """Worktree creation completed."""

    kind: Literal["completed"] = "completed"
    path: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_value(self) -> float:
        return 1.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_message(self) -> str:
        return "Completed"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_in_progress(self) -> bool:
        return False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "checkmark.circle"


class WorktreeCreationProgressFailed(BaseModel, frozen=True):
    """Worktree creation failed."""

    kind: Literal["failed"] = "failed"
    error: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_value(self) -> float:
        return 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_message(self) -> str:
        return f"Failed: {self.error}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_in_progress(self) -> bool:
        return False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return "xmark.circle"


WorktreeCreationProgress = Annotated[
    WorktreeCreationProgressIdle
    | WorktreeCreationProgressPreparing
    | WorktreeCreationProgressUpdatingFiles
    | WorktreeCreationProgressCompleted
    | WorktreeCreationProgressFailed,
    Field(discriminator="kind"),
]


class RemoteBranch(BaseModel, frozen=True):
    """A remote git branch reference."""

    name: str
    remote: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        """Display name without the remote prefix."""
        prefix = f"{self.remote}/"
        if self.name.startswith(prefix):
            return self.name[len(prefix) :]
        return self.name
