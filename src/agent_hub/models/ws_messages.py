"""WebSocket message models for client-server communication."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.process_info import SessionProcessState, UnmatchedClaudeProcess
from agent_hub.models.search import SessionSearchResult
from agent_hub.models.session import SelectedRepository
from agent_hub.models.stats import GlobalStatsCache


# --- Notification models ---


class AttentionNotification(BaseModel, frozen=True):
    """An in-memory notification for a session needing attention."""

    id: str
    session_id: str
    attention_kind: Literal["awaiting_approval", "awaiting_question"]
    tool_name: str = ""
    timestamp: datetime
    resolved: bool = False


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


    # --- Legacy message types (kept for backward compat, will be removed) ---


class ServerMessageNotification(BaseModel, frozen=True):
    """Server sends a new attention notification. (Legacy — use session_update)"""

    kind: Literal["notification"] = "notification"
    notification: AttentionNotification


class ServerMessageNotificationResolved(BaseModel, frozen=True):
    """Server notifies that a notification has been resolved. (Legacy — use session_update)"""

    kind: Literal["notification_resolved"] = "notification_resolved"
    notification_id: str
    session_id: str


class ServerMessageNotificationList(BaseModel, frozen=True):
    """Server sends the full list of active notifications (on connect). (Legacy — use session_update)"""

    kind: Literal["notification_list"] = "notification_list"
    notifications: list[AttentionNotification] = Field(default_factory=list)


class ServerMessageProcessStateUpdate(BaseModel, frozen=True):
    """Server notifies client of process state changes. (Legacy — use session_update)"""

    kind: Literal["process_state_update"] = "process_state_update"
    process_states: dict[str, SessionProcessState] = Field(default_factory=dict)
    unmatched_processes: list[UnmatchedClaudeProcess] = Field(default_factory=list)


class ServerMessageSessionUpdate(BaseModel, frozen=True):
    """Unified session state update — replaces process_state_update + notification messages."""

    kind: Literal["session_update"] = "session_update"
    session_id: str
    is_active: bool = False
    is_connectable: bool = False
    is_resumable: bool = True
    needs_attention: bool = False
    effective_status: str = "idle"
    process_category: str | None = None
    process_pid: int | None = None
    terminal_key: str | None = None
    monitor_state: SessionMonitorState | None = None
    notifications: list[AttentionNotification] = Field(default_factory=list)


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
    | ServerMessageSessionUpdate
    | ServerMessageProcessStateUpdate
    | ServerMessageNotification
    | ServerMessageNotificationResolved
    | ServerMessageNotificationList
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
