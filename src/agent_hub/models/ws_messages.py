"""WebSocket message models for client-server communication."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.search import SessionSearchResult
from agent_hub.models.session import SelectedRepository
from agent_hub.models.stats import GlobalStatsCache


# --- ServerMessage discriminated union ---


class ServerMessageSessionStateUpdate(BaseModel, frozen=True):
    """Server notifies client of session state change."""

    kind: Literal["session_state_update"] = "session_state_update"
    session_id: str
    state: SessionMonitorState


class ServerMessageSessionsUpdated(BaseModel, frozen=True):
    """Server notifies client of updated repository/session list."""

    kind: Literal["sessions_updated"] = "sessions_updated"
    repositories: list[SelectedRepository] = Field(default_factory=list)


class ServerMessageStatsUpdated(BaseModel, frozen=True):
    """Server notifies client of updated statistics."""

    kind: Literal["stats_updated"] = "stats_updated"
    provider: str
    stats: GlobalStatsCache


class ServerMessageSearchResults(BaseModel, frozen=True):
    """Server sends search results to client."""

    kind: Literal["search_results"] = "search_results"
    results: list[SessionSearchResult] = Field(default_factory=list)


class ServerMessageTerminalOutput(BaseModel, frozen=True):
    """Server sends terminal output data."""

    kind: Literal["terminal_output"] = "terminal_output"
    session_key: str
    data: str


class ServerMessageError(BaseModel, frozen=True):
    """Server sends an error message."""

    kind: Literal["error"] = "error"
    message: str


class SessionHistoryEntry(BaseModel, frozen=True):
    """A raw JSONL entry for the history view."""

    line: int
    type: str
    data: dict[str, object]


class ServerMessageSessionHistoryAppend(BaseModel, frozen=True):
    """Server pushes new JSONL entries parsed by the file watcher."""

    kind: Literal["session_history_append"] = "session_history_append"
    session_id: str
    entries: list[SessionHistoryEntry]
    total_lines: int


ServerMessage = Annotated[
    ServerMessageSessionStateUpdate
    | ServerMessageSessionsUpdated
    | ServerMessageStatsUpdated
    | ServerMessageSearchResults
    | ServerMessageTerminalOutput
    | ServerMessageSessionHistoryAppend
    | ServerMessageError,
    Field(discriminator="kind"),
]


# --- ClientMessage discriminated union ---


class ClientMessageSubscribeSession(BaseModel, frozen=True):
    """Client subscribes to a session's updates."""

    kind: Literal["subscribe_session"] = "subscribe_session"
    session_id: str
    project_path: str
    session_file_path: str


class ClientMessageUnsubscribeSession(BaseModel, frozen=True):
    """Client unsubscribes from a session's updates."""

    kind: Literal["unsubscribe_session"] = "unsubscribe_session"
    session_id: str


class ClientMessageTerminalInput(BaseModel, frozen=True):
    """Client sends terminal input."""

    kind: Literal["terminal_input"] = "terminal_input"
    session_key: str
    data: str


class ClientMessageTerminalResize(BaseModel, frozen=True):
    """Client resizes the terminal."""

    kind: Literal["terminal_resize"] = "terminal_resize"
    session_key: str
    cols: int
    rows: int


class ClientMessageRefreshSessions(BaseModel, frozen=True):
    """Client requests a session list refresh."""

    kind: Literal["refresh_sessions"] = "refresh_sessions"


ClientMessage = Annotated[
    ClientMessageSubscribeSession
    | ClientMessageUnsubscribeSession
    | ClientMessageTerminalInput
    | ClientMessageTerminalResize
    | ClientMessageRefreshSessions,
    Field(discriminator="kind"),
]
