"""Diff comment models for inline code review annotations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field


class DiffComment(BaseModel, frozen=True):
    """A comment attached to a specific line in a diff."""

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime
    file_path: str
    line_number: int
    side: Literal["left", "right", "unified"]
    line_content: str = ""
    text: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def location_key(self) -> str:
        """Unique key identifying the comment location."""
        return f"{self.file_path}:{self.line_number}:{self.side}"
