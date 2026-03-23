"""Data models for Claude process tracking."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ClaudeProcessCategory(StrEnum):
    hub = "hub"
    tmux = "tmux"
    user = "user"
    third_party = "third_party"


class ClaudeProcessInfo(BaseModel, frozen=True):
    """Information about a running claude process linked to a session."""

    pid: int
    session_id: str
    category: ClaudeProcessCategory
    monitored: bool = False
    terminal_connected: bool = False
    cwd: str = ""
    model: str = ""
    started_at: float = 0


class UnmatchedClaudeProcess(BaseModel, frozen=True):
    """A running claude process that could not be matched to a session."""

    pid: int
    cwd: str = ""


class SessionProcessState(BaseModel, frozen=True):
    """Process state for a known session."""

    session_id: str
    process: ClaudeProcessInfo | None = None
