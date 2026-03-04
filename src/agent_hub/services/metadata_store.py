"""SQLAlchemy async metadata store for session metadata and repo mappings."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class SessionMetadataRow(Base):
    """Persistent metadata for a session (custom name, timestamps)."""

    __tablename__ = "session_metadata"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    custom_name: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(tz=timezone.utc),
    )


class SessionRepoMappingRow(Base):
    """Maps a session to its parent repo and worktree path (anti-collision)."""

    __tablename__ = "session_repo_mapping"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_repo_path: Mapped[str] = mapped_column(String)
    worktree_path: Mapped[str] = mapped_column(String)
    assigned_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(tz=timezone.utc),
    )


class MetadataStore:
    """Async CRUD for session metadata and repo mappings."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def init_db(self) -> None:
        """Create tables if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Dispose of the engine."""
        await self._engine.dispose()

    # --- Session Metadata ---

    async def get_metadata(self, session_id: str) -> SessionMetadataRow | None:
        """Get metadata for a session."""
        async with self._session_factory() as session:
            return await session.get(SessionMetadataRow, session_id)

    async def upsert_metadata(
        self, session_id: str, custom_name: str | None = None
    ) -> SessionMetadataRow:
        """Insert or update session metadata."""
        async with self._session_factory() as session:
            row = await session.get(SessionMetadataRow, session_id)
            now = datetime.now(tz=timezone.utc)
            if row is None:
                row = SessionMetadataRow(
                    session_id=session_id,
                    custom_name=custom_name,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.custom_name = custom_name
                row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return row

    async def delete_metadata(self, session_id: str) -> None:
        """Delete session metadata."""
        async with self._session_factory() as session:
            row = await session.get(SessionMetadataRow, session_id)
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def get_all_custom_names(self) -> dict[str, str]:
        """Return all session custom names as {session_id: custom_name}."""
        async with self._session_factory() as session:
            stmt = select(SessionMetadataRow).where(
                SessionMetadataRow.custom_name.isnot(None),
                SessionMetadataRow.custom_name != "",
            )
            result = await session.execute(stmt)
            return {
                row.session_id: row.custom_name
                for row in result.scalars().all()
                if row.custom_name
            }

    # --- Session Repo Mapping ---

    async def get_repo_mapping(self, session_id: str) -> SessionRepoMappingRow | None:
        """Get repo mapping for a session."""
        async with self._session_factory() as session:
            return await session.get(SessionRepoMappingRow, session_id)

    async def upsert_repo_mapping(
        self,
        session_id: str,
        parent_repo_path: str,
        worktree_path: str,
    ) -> SessionRepoMappingRow:
        """Insert or update a session-repo mapping."""
        async with self._session_factory() as session:
            row = await session.get(SessionRepoMappingRow, session_id)
            now = datetime.now(tz=timezone.utc)
            if row is None:
                row = SessionRepoMappingRow(
                    session_id=session_id,
                    parent_repo_path=parent_repo_path,
                    worktree_path=worktree_path,
                    assigned_at=now,
                )
                session.add(row)
            else:
                row.parent_repo_path = parent_repo_path
                row.worktree_path = worktree_path
                row.assigned_at = now
            await session.commit()
            await session.refresh(row)
            return row

    async def get_mappings_for_repo(
        self, parent_repo_path: str
    ) -> list[SessionRepoMappingRow]:
        """Get all mappings for a parent repo."""
        async with self._session_factory() as session:
            stmt = select(SessionRepoMappingRow).where(
                SessionRepoMappingRow.parent_repo_path == parent_repo_path
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_repo_mapping(self, session_id: str) -> None:
        """Delete a session-repo mapping."""
        async with self._session_factory() as session:
            row = await session.get(SessionRepoMappingRow, session_id)
            if row is not None:
                await session.delete(row)
                await session.commit()
