"""SQLAlchemy async ORM models for session metadata persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class SessionMetadataRow(Base):
    """Persistent metadata for a session (custom name, timestamps)."""

    __tablename__ = "session_metadata"

    session_id: Mapped[str] = mapped_column(
        String, primary_key=True, nullable=False
    )
    custom_name: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
        onupdate=lambda: datetime.now(tz=timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"SessionMetadataRow(session_id={self.session_id!r}, "
            f"custom_name={self.custom_name!r})"
        )


class SessionRepoMappingRow(Base):
    """Maps a session to its parent repository and optional worktree path."""

    __tablename__ = "session_repo_mapping"

    session_id: Mapped[str] = mapped_column(
        String, primary_key=True, nullable=False
    )
    parent_repo_path: Mapped[str] = mapped_column(
        String, nullable=False
    )
    worktree_path: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"SessionRepoMappingRow(session_id={self.session_id!r}, "
            f"parent_repo_path={self.parent_repo_path!r}, "
            f"worktree_path={self.worktree_path!r})"
        )
