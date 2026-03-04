"""Pending session models for sessions being initialized."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from agent_hub.models.session import WorktreeBranch


class PendingHubSession(BaseModel, frozen=True):
    """A session that is being set up but not yet active."""

    id: UUID = Field(default_factory=uuid4)
    worktree: WorktreeBranch
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    initial_prompt: str = ""
    initial_input_text: str = ""
    dangerously_skip_permissions: bool = False
    worktree_name: str = ""
