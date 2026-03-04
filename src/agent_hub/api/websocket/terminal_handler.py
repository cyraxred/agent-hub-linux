"""WebSocket endpoint for bridging a PTY file descriptor to xterm.js.

Each terminal session gets its own WebSocket at ``/ws/terminal/{key}``.
The handler reads from the PTY fd using ``asyncio`` and forwards bytes to
the WebSocket, while also writing WebSocket input back to the PTY.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from agent_hub.services.process_registry import ProcessRegistry
from agent_hub.services.terminal_launcher import resize_terminal

logger = logging.getLogger(__name__)

# Maximum bytes to read per PTY read cycle.
_READ_CHUNK_SIZE = 4096


def _get_registry(ws: WebSocket) -> ProcessRegistry:
    """Retrieve the process registry from app state."""
    try:
        return ws.app.state.process_registry
    except AttributeError:
        pass
    try:
        return ws.app.state.provider.process_registry
    except AttributeError:
        pass
    raise RuntimeError("No ProcessRegistry found in app state")


async def _read_pty(fd: int, ws: WebSocket, cancel_event: asyncio.Event) -> None:
    """Continuously read from the PTY fd and send data to the WebSocket.

    Uses ``asyncio.get_event_loop().add_reader`` to avoid blocking the loop.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _on_readable() -> None:
        """Called by the event loop when the fd has data available."""
        try:
            data = os.read(fd, _READ_CHUNK_SIZE)
            if data:
                queue.put_nowait(data)
            else:
                # EOF -- process exited
                queue.put_nowait(None)
        except OSError:
            queue.put_nowait(None)

    try:
        loop.add_reader(fd, _on_readable)

        while not cancel_event.is_set():
            try:
                data = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if data is None:
                # Process exited
                break

            try:
                # xterm.js expects text frames for terminal output
                text = data.decode("utf-8", errors="replace")
                await ws.send_text(text)
            except Exception:
                break

    finally:
        try:
            loop.remove_reader(fd)
        except Exception:
            pass


async def _write_pty(
    fd: int, ws: WebSocket, cancel_event: asyncio.Event
) -> None:
    """Continuously read from the WebSocket and write to the PTY fd.

    Handles both plain text input and JSON-formatted resize messages.
    A resize message is a JSON object: ``{"type": "resize", "rows": N, "cols": N}``.
    """
    while not cancel_event.is_set():
        try:
            raw = await ws.receive_text()
        except WebSocketDisconnect:
            break
        except Exception:
            break

        if not raw:
            continue

        # Check if this is a resize command
        if raw.startswith("{"):
            try:
                msg = json.loads(raw)
                if isinstance(msg, dict) and msg.get("type") == "resize":
                    rows = int(msg.get("rows", 24))
                    cols = int(msg.get("cols", 80))
                    try:
                        resize_terminal(fd, rows, cols)
                    except Exception:
                        logger.debug("Failed to resize terminal fd=%d", fd)
                    continue
            except (json.JSONDecodeError, ValueError, TypeError):
                pass  # Not a JSON message -- treat as terminal input

        # Write raw input to the PTY
        try:
            os.write(fd, raw.encode("utf-8"))
        except OSError:
            logger.debug("PTY write failed for fd=%d", fd)
            break

    cancel_event.set()


async def terminal_websocket_endpoint(ws: WebSocket, key: str) -> None:
    """WebSocket endpoint at ``/ws/terminal/{key}``.

    Bridges the PTY file descriptor for the terminal identified by ``key``
    with the xterm.js frontend via a WebSocket.
    """
    registry = _get_registry(ws)
    proc = registry.get(key)

    if proc is None:
        await ws.close(code=4004, reason=f"Terminal not found: {key}")
        return

    await ws.accept()
    logger.info("Terminal WebSocket connected: key=%s fd=%d pid=%d", key, proc.fd, proc.pid)

    cancel_event = asyncio.Event()

    # Run the reader and writer concurrently
    reader_task = asyncio.create_task(_read_pty(proc.fd, ws, cancel_event))
    writer_task = asyncio.create_task(_write_pty(proc.fd, ws, cancel_event))

    try:
        # Wait for either task to finish (which means the connection or
        # process has ended)
        done, pending = await asyncio.wait(
            [reader_task, writer_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Signal the other task to stop
        cancel_event.set()

        # Give the pending task a moment to finish cleanly
        for task in pending:
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    except Exception:
        logger.exception("Terminal WebSocket error for key=%s", key)
        cancel_event.set()
        reader_task.cancel()
        writer_task.cancel()

    finally:
        logger.info("Terminal WebSocket disconnected: key=%s", key)
        try:
            await ws.close()
        except Exception:
            pass
