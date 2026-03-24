"""WebSocket connection manager and message handler.

Handles the main ``/ws`` endpoint used by the frontend to subscribe to
session state updates, request session refreshes, and bridge terminal I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from agent_hub.models.search import SessionSearchResult
from agent_hub.models.stats import GlobalStatsCache
from agent_hub.models.ws_messages import (
    AttentionNotification,
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
    ServerMessageSessionUpdate,
    ServerMessageStatsUpdated,
    ServerMessageTerminalOutput,
)
from agent_hub.services.terminal_launcher import resize_terminal

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts server messages."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
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
            subscribed_sessions = self._subscriptions.pop(id(ws), set())

        # Clear manual monitoring for sessions this connection was subscribed to
        if subscribed_sessions:
            try:
                sm = ws.app.state.provider.session_manager
                for session_id in subscribed_sessions:
                    # Only clear if no other connections are subscribed
                    async with self._lock:
                        still_subscribed = any(
                            session_id in self._subscriptions.get(id(other_ws), set())
                            for other_ws in self._connections
                        )
                    if not still_subscribed:
                        await sm.set_manual_monitoring(session_id, False)
            except Exception:
                logger.debug("Could not clear manual monitoring on disconnect", exc_info=True)

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

    async def broadcast_stats_updated(
        self, provider: str, stats: GlobalStatsCache
    ) -> None:
        msg = ServerMessageStatsUpdated(provider=provider, stats=stats)
        await self.broadcast(msg.model_dump(mode="json"))

    async def broadcast_search_results(
        self, results: list[SessionSearchResult]
    ) -> None:
        msg = ServerMessageSearchResults(results=results)
        await self.broadcast(msg.model_dump(mode="json"))

    async def broadcast_session_history_append(
        self,
        session_id: str,
        entries: list[dict[str, object]],
        total_lines: int,
    ) -> None:
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
        msg = ServerMessageTerminalOutput(session_key=session_key, data=data)
        await self.broadcast(msg.model_dump(mode="json"))

    async def send_error(self, ws: WebSocket, message: str) -> None:
        msg = ServerMessageError(message=message)
        await self._safe_send(ws, msg.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Singleton manager
# ---------------------------------------------------------------------------

manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Provider callbacks -- wired up during app startup
# ---------------------------------------------------------------------------


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


def _build_session_update_msg(
    sm: Any, session_id: str,
) -> ServerMessageSessionUpdate | None:
    """Build a ``session_update`` message for a session, or None if unknown."""
    session = sm.get_session(session_id)
    if session is None:
        return None

    needs_attention = sm.get_needs_attention(session_id)
    effective_status = sm.get_effective_status(session_id)
    pending = sm.get_pending_attention(session_id)

    notifications: list[AttentionNotification] = []
    for a in pending:
        notifications.append(
            AttentionNotification(
                id=f"{a.session_id}:{a.tool_use_id}",
                session_id=a.session_id,
                attention_kind=a.attention_kind,  # type: ignore[arg-type]
                tool_name=a.tool_name,
                timestamp=datetime.fromtimestamp(a.ts, tz=timezone.utc) if a.ts else datetime.now(tz=timezone.utc),
            )
        )

    return ServerMessageSessionUpdate(
        session_id=session_id,
        is_connectable=session.is_connectable,
        needs_attention=needs_attention,
        effective_status=effective_status,
        last_activity_at=session.last_activity_at,
        process_category=session.process.category if session.process else None,
        process_pid=session.process.pid if session.process else None,
        monitor_state=session.monitor_state,
        notifications=notifications,
    )


async def _on_unified_session_update(session_id: str) -> None:
    """Broadcast a unified ``session_update`` from the SessionManager."""
    try:
        sm = _on_unified_session_update._provider.session_manager  # type: ignore[attr-defined]
        msg = _build_session_update_msg(sm, session_id)
        if msg is not None:
            await manager.broadcast(msg.model_dump(mode="json"))
    except Exception:
        logger.exception("Error broadcasting unified session update for %s", session_id)


def register_provider_callbacks(provider: Any) -> None:
    """Wire the WebSocket manager into provider services so that state
    changes are automatically broadcast to connected clients.

    Call this once during FastAPI app startup.
    """
    async def _on_tool_result(session_id: str, tool_use_id: str) -> None:
        try:
            provider.process_tracker.resolve_attention(session_id, tool_use_id)
        except Exception:
            logger.exception("Error resolving attention from tool_result")

    # --- Transcript registry → WS broadcast wiring ---
    # Core callbacks (state_update, transcript_added/removed) are wired
    # in provider.init() so they fire during initial discovery.
    # Here we add WS-specific callbacks: history append and tool_result.
    try:
        for registry in (provider.claude_transcript_registry, provider.codex_transcript_registry):
            registry.on_history_append(_on_session_history_append)
            registry.on_tool_result(_on_tool_result)
    except Exception:
        logger.exception("Failed to wire transcript registry callbacks")

    # --- SessionManager wiring ---
    try:
        sm = provider.session_manager

        # Process tracker -> SessionManager
        provider.process_tracker.on_update(sm.handle_process_update)

        # Attention callbacks — just trigger a broadcast, no data copy.
        # The tracker owns the attention state; SessionManager queries it.
        async def _on_attention(entry: object) -> None:
            await sm.handle_attention_changed(entry.session_id)  # type: ignore[attr-defined]

        async def _on_attention_resolved(session_id: str, tool_use_id: str) -> None:
            await sm.handle_attention_changed(session_id)

        provider.process_tracker.on_attention(_on_attention)
        provider.process_tracker.on_attention_resolved(_on_attention_resolved)

        # Unified broadcast
        _on_unified_session_update._provider = provider  # type: ignore[attr-defined]
        sm.on_session_update(_on_unified_session_update)

        # Initial sync — the tracker already ran start() before callbacks
        # were wired, so we must pull current state explicitly.
        asyncio.ensure_future(sm.handle_process_update())
    except Exception:
        logger.exception("Failed to wire SessionManager callbacks")

    # Stats services
    try:
        provider.stats_service.on_stats_update(_on_claude_stats_update)
    except AttributeError:
        pass
    try:
        provider.codex_stats_service.on_stats_update(_on_codex_stats_update)
    except AttributeError:
        pass


# ---------------------------------------------------------------------------
# WebSocket endpoint handler
# ---------------------------------------------------------------------------


async def _send_initial_session_states(ws: WebSocket) -> None:
    """Send session_update for all known sessions to a newly connected client."""
    sm = ws.app.state.provider.session_manager
    for session in sm.get_all_sessions():
        msg = _build_session_update_msg(sm, session.session_id)
        if msg is not None:
            await manager._safe_send(ws, msg.model_dump(mode="json"))


async def websocket_endpoint(ws: WebSocket) -> None:
    """Main ``/ws`` endpoint handler."""
    await manager.connect(ws)

    # Send current session state for all known sessions so the frontend
    # renders process/attention state immediately after connecting.
    try:
        await _send_initial_session_states(ws)
    except Exception:
        logger.debug("Could not send initial session states", exc_info=True)

    try:
        while True:
            raw = await ws.receive_text()

            try:
                data = json.loads(raw)
                from pydantic import TypeAdapter
                adapter = TypeAdapter(ClientMessage)
                message = adapter.validate_python(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                await manager.send_error(ws, f"Invalid message: {exc}")
                continue

            if isinstance(message, ClientMessageSubscribeSession):
                await _handle_subscribe(ws, message, ws.app.state.provider)

            elif isinstance(message, ClientMessageUnsubscribeSession):
                await _handle_unsubscribe(ws, message, ws.app.state.provider)

            elif isinstance(message, ClientMessageTerminalInput):
                await _handle_terminal_input(message, ws.app.state.provider)

            elif isinstance(message, ClientMessageTerminalResize):
                await _handle_terminal_resize(message, ws.app.state.provider)

            elif isinstance(message, ClientMessageRefreshSessions):
                await _handle_refresh_sessions(ws.app.state.provider)

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

    # If the transcript isn't already tracked by the registry, register it.
    registry = provider.claude_transcript_registry
    if msg.session_file_path and ".codex" in msg.session_file_path:
        registry = provider.codex_transcript_registry

    transcript = registry.get_transcript(msg.session_id)
    if transcript is None and msg.session_file_path:
        try:
            await registry.register_transcript(
                session_id=msg.session_id,
                project_path=msg.project_path,
                file_path=msg.session_file_path,
            )
        except Exception:
            logger.exception("Failed to register transcript for %s", msg.session_id)
            await manager.send_error(ws, f"Failed to start monitoring {msg.session_id}")
            return

    # Set manual monitoring — tells the registry to watch per-file for
    # instant notification.
    try:
        await provider.session_manager.set_manual_monitoring(msg.session_id, True)
    except Exception:
        logger.debug("Could not set manual monitoring for %s", msg.session_id)

    # Trigger an immediate unified broadcast so the subscriber gets current state.
    try:
        provider.session_manager._schedule_notify(msg.session_id)
    except Exception:
        logger.debug("Could not trigger immediate session update for %s", msg.session_id)


async def _handle_unsubscribe(
    ws: WebSocket,
    msg: ClientMessageUnsubscribeSession,
    provider: Any,
) -> None:
    await manager.unsubscribe(ws, msg.session_id)

    # Clear manual monitoring — auto_monitoring may keep the transcript
    # watched if there's pending attention.
    try:
        await provider.session_manager.set_manual_monitoring(msg.session_id, False)
    except Exception:
        logger.debug("Could not clear manual monitoring for %s", msg.session_id)


async def _handle_terminal_input(
    msg: ClientMessageTerminalInput,
    provider: Any,
) -> None:
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
    # Broadcast current session state for all known sessions so the frontend
    # gets process/attention state immediately.
    try:
        sm = provider.session_manager
        for session in sm.get_all_sessions():
            sm._schedule_notify(session.session_id)
    except Exception:
        logger.debug("Could not broadcast session states after refresh", exc_info=True)
