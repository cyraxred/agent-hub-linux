"""Search models for session indexing and search results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, computed_field


class SearchMatchField(StrEnum):
    """Fields that can be matched in a search."""

    slug = "slug"
    summary = "summary"
    path = "path"
    git_branch = "git_branch"
    first_message = "first_message"

    @property
    def icon_name(self) -> str:
        """Icon name for display."""
        match self:
            case SearchMatchField.slug:
                return "tag"
            case SearchMatchField.summary:
                return "doc.text"
            case SearchMatchField.path:
                return "folder"
            case SearchMatchField.git_branch:
                return "arrow.triangle.branch"
            case SearchMatchField.first_message:
                return "text.bubble"

    @property
    def display_label(self) -> str:
        """Human-readable label for the field."""
        match self:
            case SearchMatchField.slug:
                return "Slug"
            case SearchMatchField.summary:
                return "Summary"
            case SearchMatchField.path:
                return "Path"
            case SearchMatchField.git_branch:
                return "Branch"
            case SearchMatchField.first_message:
                return "First Message"


class SessionIndexEntry(BaseModel, frozen=True):
    """An indexed session entry for search."""

    session_id: str
    project_path: str
    slug: str = ""
    git_branch: str = ""
    first_message: str = ""
    summaries: list[str] = Field(default_factory=list)
    last_activity_at: datetime


class SessionSearchResult(BaseModel, frozen=True):
    """A search result with match metadata."""

    id: str
    slug: str = ""
    project_path: str = ""
    git_branch: str = ""
    first_message: str = ""
    summaries: list[str] = Field(default_factory=list)
    last_activity_at: datetime
    matched_field: SearchMatchField
    matched_text: str = ""
    relevance_score: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def repository_name(self) -> str:
        """Extract repository name from project path."""
        return PurePosixPath(self.project_path).name
