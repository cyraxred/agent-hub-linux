"""Git diff models for file change tracking."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field

_WEB_RENDERABLE_EXTENSIONS: frozenset[str] = frozenset({
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".xml",
    ".svg",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".py",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
    ".bash",
    ".zsh",
    ".txt",
    ".cfg",
    ".ini",
    ".conf",
    ".env",
    ".gitignore",
    ".dockerfile",
    ".vue",
    ".svelte",
    ".astro",
})


class DiffMode(StrEnum):
    """Mode for diff display."""

    unstaged = "unstaged"
    staged = "staged"
    branch = "branch"

    @property
    def icon(self) -> str:
        """Icon for the diff mode."""
        match self:
            case DiffMode.unstaged:
                return "pencil.circle"
            case DiffMode.staged:
                return "checkmark.circle"
            case DiffMode.branch:
                return "arrow.triangle.branch"

    @property
    def empty_state_title(self) -> str:
        """Title when no diffs are found."""
        match self:
            case DiffMode.unstaged:
                return "No Unstaged Changes"
            case DiffMode.staged:
                return "No Staged Changes"
            case DiffMode.branch:
                return "No Branch Changes"

    @property
    def empty_state_description(self) -> str:
        """Description when no diffs are found."""
        match self:
            case DiffMode.unstaged:
                return "There are no unstaged changes in the working directory."
            case DiffMode.staged:
                return "There are no staged changes ready to commit."
            case DiffMode.branch:
                return "There are no changes compared to the base branch."

    @property
    def loading_message(self) -> str:
        """Message shown while loading diffs."""
        match self:
            case DiffMode.unstaged:
                return "Loading unstaged changes..."
            case DiffMode.staged:
                return "Loading staged changes..."
            case DiffMode.branch:
                return "Loading branch changes..."


class GitDiffFileEntry(BaseModel, frozen=True):
    """A single file entry in a git diff."""

    id: UUID = Field(default_factory=uuid4)
    file_path: str
    relative_path: str
    additions: int = 0
    deletions: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_name(self) -> str:
        """Extract the file name from the path."""
        return PurePosixPath(self.file_path).name

    @computed_field  # type: ignore[prop-decorator]
    @property
    def directory_path(self) -> str:
        """Extract the directory path from the file path."""
        parent = str(PurePosixPath(self.file_path).parent)
        return parent if parent != "." else ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_web_renderable(self) -> bool:
        """Whether the file can be rendered in a web view."""
        suffix = PurePosixPath(self.file_path).suffix.lower()
        return suffix in _WEB_RENDERABLE_EXTENSIONS


class GitDiffState(BaseModel, frozen=True):
    """State of git diff results."""

    files: list[GitDiffFileEntry] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_count(self) -> int:
        """Number of files in the diff."""
        return len(self.files)

    @classmethod
    def empty(cls) -> GitDiffState:
        """Create an empty diff state."""
        return cls(files=[])


class ParsedFileDiff(BaseModel, frozen=True):
    """A parsed file diff with old and new content."""

    file_path: str
    old_content: str = ""
    new_content: str = ""
