"""Orchestration models for multi-session task management."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class OrchestrationStatus(StrEnum):
    """Status of an orchestration session."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class OrchestrationSession(BaseModel, frozen=True):
    """A single session within an orchestration plan."""

    id: UUID = Field(default_factory=uuid4)
    worktree_path: str
    prompt: str
    status: OrchestrationStatus = OrchestrationStatus.pending


class OrchestrationPlan(BaseModel, frozen=True):
    """A plan coordinating multiple orchestration sessions."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    sessions: list[OrchestrationSession] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
