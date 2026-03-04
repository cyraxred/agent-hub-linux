"""WebSocket connection manager and message handler.

Handles the main ``/ws`` endpoint used by the frontend to subscribe to
session state updates, request session refreshes, and bridge terminal I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from agent_hub.models.monitor_state import SessionMonitorState
from agent_hub.models.search import SessionSearchResult
from agent_hub.models.session import SelectedRepository
from agent_hub.models.stats import GlobalStatsCache
from agent_hub.models.ws_messages import (
    ClientMessage,
    ClientMessageRefreshSessions,
    ClientMessageSubscribeSession,
    ClientMessageTerminalInput,
    ClientMessageTerminalResize,
    ClientMessageUnsubscribeSession,
    SessionHistoryEntry,
    ServerMessageError,
    ServerMessageSearchResults,
    ServerMessageSessionHistoryAppend,
    ServerMessageSessionsUpdated,
    ServerMessageSessionStateUpdate,
    ServerMessageStatsUpdated,
    ServerMessageTerminalOutput,
)
from agent_hub.services.terminal_launcher import resize_terminal

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts server messages."""

    def __init__(self) -> None:
        # All active connections
        self._connections: list[WebSocket] = []
        # Per-connection session subscriptions: ws -> set of session_ids
        self._subscriptions: dict[int, set[str]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
            self._subscriptions[id(ws)] = set()
        logger.info("WebSocket connected: %s", id(ws))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
            self._subscriptions.pop(id(ws), None)
        logger.info("WebSocket disconnected: %s", id(ws))

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def subscribe(self, ws: WebSocket, session_id: str) -> None:
        async with self._lock:
            subs = self._subscriptions.get(id(ws))
            if subs is not None:
                subs.add(session_id)

    async def unsubscribe(self, ws: WebSocket, session_id: str) -> None:
        async with self._lock:
            subs = self._subscriptions.get(id(ws))
            if subs is not None:
                subs.discard(session_id)

    def _is_subscribed(self, ws: WebSocket, session_id: str) -> bool:
        subs = self._subscriptions.get(id(ws))
        return subs is not None and session_id in subs

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    async def _safe_send(self, ws: WebSocket, data: dict[str, Any]) -> None:
        """Send JSON to a single WebSocket, silently handling send errors."""
        try:
            await ws.send_json(data)
        except Exception:
            logger.debug("Failed to send to WebSocket %s", id(ws), exc_info=True)

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Broadcast a message to **all** connected clients."""
        async with self._lock:
            targets = list(self._connections)
        await asyncio.gather(
            *(self._safe_send(ws, data) for ws in targets),
            return_exceptions=True,
        )

    async def broadcast_to_subscribers(
        self, session_id: str, data: dict[str, Any]
    ) -> None:
        """Broadcast a message only to clients subscribed to ``session_id``."""
        async with self._lock:
            targets = [
                ws for ws in self._connections
                if self._is_subscribed(ws, session_id)
            ]
        await asyncio.gather(
            *(self._safe_send(ws, data) for ws in targets),
            return_exceptions=True,
        )

    # ------------------------------------------------------------------
    # High-level broadcast helpers
    # ------------------------------------------------------------------

    async def broadcast_session_state(
        self, session_id: str, state: SessionMonitorState
    ) -> None:
        """Broadcast a ``session_state_update`` to subscribers."""
        msg = ServerMessageSessionStateUpdate(
            session_id=session_id,
            state=state,
        )
        await self.broadcast_to_subscribers(
            session_id, msg.model_dump(mode="json")
        )

    async def broadcast_sessions_updated(
        self, repositories: list[SelectedRepository]
    ) -> None:
        """Broadcast a ``sessions_updated`` to all clients."""
        msg = ServerMessageSessionsUpdated(repositories=repositories)
        await self.broadcast(msg.model_dump(mode="json"))

    async def broadcast_stats_updated(
        self, provider: str, stats: GlobalStatsCache
    ) -> None:
        """Broadcast a ``stats_updated`` to all clients."""
        msg = ServerMessageStatsUpdated(provider=provider, stats=stats)
        await self.broadcast(msg.model_dump(mode="json"))

    async def broadcast_search_results(
        self, results: list[SessionSearchResult]
    ) -> None:
        """Broadcast ``search_results`` to all clients."""
        msg = ServerMessageSearchResults(results=results)
        await self.broadcast(msg.model_dump(mode="json"))

    async def broadcast_session_history_append(
        self,
        session_id: str,
        entries: list[dict[str, object]],
        total_lines: int,
    ) -> None:
        """Broadcast new raw JSONL entries to subscribers."""
        msg = ServerMessageSessionHistoryAppend(
            session_id=session_id,
            entries=[
                SessionHistoryEntry(
                    line=int(e.get("line", 0)),  # type: ignore[arg-type]
                    type=str(e.get("type", "")),
                    data=e.get("data", {}),  # type: ignore[arg-type]
                )
                for e in entries
            ],
            total_lines=total_lines,
        )
        await self.broadcast_to_subscribers(
            session_id, msg.model_dump(mode="json")
        )

    async def broadcast_terminal_output(
        self, session_key: str, data: str
    ) -> None:
        """Broadcast ``terminal_output`` to all clients."""
        msg = ServerMessageTerminalOutput(session_key=session_key, data=data)
        await self.broadcast(msg.model_dump(mode="json"))

    async def send_error(self, ws: WebSocket, message: str) -> None:
        """Send an ``error`` message to a single client."""
        msg = ServerMessageError(message=message)
        await self._safe_send(ws, msg.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Singleton manager
# ---------------------------------------------------------------------------

manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Provider callbacks -- wired up during app startup
# ---------------------------------------------------------------------------


async def _on_session_state_update(
    session_id: str, state: SessionMonitorState
) -> None:
    """Callback invoked by file watchers when a session state changes."""
    await manager.broadcast_session_state(session_id, state)


async def _on_session_history_append(
    session_id: str, entries: list[dict[str, object]], total_lines: int
) -> None:
    """Callback invoked by file watchers when new JSONL entries are parsed."""
    await manager.broadcast_session_history_append(session_id, entries, total_lines)


async def _on_claude_stats_update(stats: GlobalStatsCache | None) -> None:
    if stats is not None:
        await manager.broadcast_stats_updated("claude", stats)


async def _on_codex_stats_update(stats: GlobalStatsCache | None) -> None:
    if stats is not None:
        await manager.broadcast_stats_updated("codex", stats)


def register_provider_callbacks(provider: Any) -> None:
    """Wire the WebSocket manager into provider services so that state
    changes are automatically broadcast to connected clients.

    Call this once during FastAPI app startup.
    """
    # Session file watchers
    provider.claude_watcher.on_state_update(_on_session_state_update)
    provider.codex_watcher.on_state_update(_on_session_state_update)
    provider.claude_watcher.on_history_append(_on_session_history_append)
    provider.codex_watcher.on_history_append(_on_session_history_append)

    # Stats services
    try:
        provider.stats_service.on_stats_update(_on_claude_stats_update)
    except AttributeError:
        pass
    try:
        # CodexGlobalStatsService does not have a file-watcher callback,
        # so this is a no-op if the method does not exist.
        provider.codex_stats_service.on_stats_update(_on_codex_stats_update)
    except AttributeError:
        pass


# ---------------------------------------------------------------------------
# WebSocket endpoint handler
# ---------------------------------------------------------------------------


async def websocket_endpoint(ws: WebSocket) -> None:
    """Main ``/ws`` endpoint handler.

    Accepts a WebSocket connection and processes ``ClientMessage`` frames
    until the connection is closed.
    """
    provider = ws.app.state.provider
    await manager.connect(ws)

    try:
        while True:
            raw = await ws.receive_text()

            # Parse the incoming ClientMessage
            try:
                data = json.loads(raw)
                # Use Pydantic's discriminated-union parsing
                from pydantic import TypeAdapter
                adapter = TypeAdapter(ClientMessage)
                message = adapter.validate_python(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                await manager.send_error(ws, f"Invalid message: {exc}")
                continue

            # Dispatch by message kind
            if isinstance(message, ClientMessageSubscribeSession):
                await _handle_subscribe(ws, message, provider)

            elif isinstance(message, ClientMessageUnsubscribeSession):
                await _handle_unsubscribe(ws, message, provider)

            elif isinstance(message, ClientMessageTerminalInput):
                await _handle_terminal_input(message, provider)

            elif isinstance(message, ClientMessageTerminalResize):
                await _handle_terminal_resize(message, provider)

            elif isinstance(message, ClientMessageRefreshSessions):
                await _handle_refresh_sessions(provider)

            else:
                await manager.send_error(ws, f"Unknown message kind: {data.get('kind')}")

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        await manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------


async def _handle_subscribe(
    ws: WebSocket,
    msg: ClientMessageSubscribeSession,
    provider: Any,
) -> None:
    """Subscribe to a session and start monitoring its file."""
    await manager.subscribe(ws, msg.session_id)

    # Start monitoring via the appropriate watcher.
    # We try Claude first; if the session file path hints at Codex we use that.
    watcher = provider.claude_watcher
    if msg.session_file_path and ".codex" in msg.session_file_path:
        watcher = provider.codex_watcher

    try:
        await watcher.start_monitoring(
            session_id=msg.session_id,
            project_path=msg.project_path,
            session_file_path=msg.session_file_path or None,
        )
    except Exception:
        logger.exception("Failed to start monitoring %s", msg.session_id)
        await manager.send_error(ws, f"Failed to start monitoring {msg.session_id}")
        return

    # Send the current state immediately
    state = await watcher.get_state(msg.session_id)
    if state is not None:
        await manager.broadcast_session_state(msg.session_id, state)


async def _handle_unsubscribe(
    ws: WebSocket,
    msg: ClientMessageUnsubscribeSession,
    provider: Any,
) -> None:
    """Unsubscribe from a session.

    The file watcher is **not** stopped here because other clients may still
    be subscribed. Stopping the watcher is handled by the REST DELETE
    endpoint or during application shutdown.
    """
    await manager.unsubscribe(ws, msg.session_id)


async def _handle_terminal_input(
    msg: ClientMessageTerminalInput,
    provider: Any,
) -> None:
    """Write data to a terminal's PTY."""
    import os

    try:
        registry = provider.process_registry
    except AttributeError:
        logger.warning("No process registry available for terminal input")
        return

    proc = registry.get(msg.session_key)
    if proc is None:
        logger.warning("Terminal not found for key %s", msg.session_key)
        return

    try:
        os.write(proc.fd, msg.data.encode("utf-8"))
    except OSError:
        logger.exception("Failed to write to terminal %s", msg.session_key)


async def _handle_terminal_resize(
    msg: ClientMessageTerminalResize,
    provider: Any,
) -> None:
    """Resize a terminal's PTY."""
    try:
        registry = provider.process_registry
    except AttributeError:
        logger.warning("No process registry available for terminal resize")
        return

    proc = registry.get(msg.session_key)
    if proc is None:
        logger.warning("Terminal not found for key %s", msg.session_key)
        return

    try:
        resize_terminal(proc.fd, msg.rows, msg.cols)
    except Exception:
        logger.exception("Failed to resize terminal %s", msg.session_key)


async def _handle_refresh_sessions(provider: Any) -> None:
    """Refresh all sessions and broadcast the updated list."""
    try:
        await provider.claude_monitor.refresh_sessions()
        await provider.codex_monitor.refresh_sessions()
    except Exception:
        logger.exception("Failed to refresh sessions")
        return

    repositories: list[SelectedRepository] = []
    repositories.extend(provider.claude_monitor.repositories)
    repositories.extend(provider.codex_monitor.repositories)
    await manager.broadcast_sessions_updated(repositories)
