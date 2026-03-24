"""WebSocket endpoint for bridging a PTY file descriptor to xterm.js.

Each terminal session gets its own WebSocket at ``/ws/terminal/{key}``.
The handler subscribes to the persistent PTY drain in ProcessRegistry
for output, and writes user input directly to the PTY fd.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import WebSocket, WebSocketDisconnect

from agent_hub.services.process_registry import ProcessRegistry
from agent_hub.services.terminal_launcher import resize_terminal

logger = logging.getLogger(__name__)


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


# DEC synchronized output markers (mode 2026).
# BSU = Begin Synchronized Update, ESU = End Synchronized Update.
_BSU = b"\x1b[?2026h"
_ESU = b"\x1b[?2026l"

# Max time to wait for ESU after seeing BSU before flushing anyway.
_SYNC_TIMEOUT = 0.2  # 200ms


async def _forward_output(
    queue: asyncio.Queue[bytes | None],
    ws: WebSocket,
    cancel_event: asyncio.Event,
) -> None:
    """Read from the registry's output queue and send to the WebSocket.

    Buffers output between synchronized update markers (DEC mode 2026)
    so that xterm.js receives complete redraws as single write() calls.
    """
    buf: list[bytes] = []
    in_sync = False

    async def _flush() -> bool:
        """Flush buffered data to the WS. Returns False on send failure."""
        nonlocal buf
        if not buf:
            return True
        payload = b"".join(buf)
        buf = []
        try:
            await ws.send_text(payload.decode("utf-8", errors="replace"))
            return True
        except Exception:
            return False

    while not cancel_event.is_set():
        timeout = _SYNC_TIMEOUT if in_sync else 0.5
        try:
            data = await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            if in_sync:
                # Timed out waiting for ESU — flush what we have
                in_sync = False
                if not await _flush():
                    break
            continue

        if data is None:
            await _flush()
            break  # Process exited

        buf.append(data)

        if _BSU in data:
            in_sync = True
        if _ESU in data:
            in_sync = False
            if not await _flush():
                break
        elif not in_sync:
            if not await _flush():
                break


async def _write_pty(
    fd: int,
    ws: WebSocket,
    cancel_event: asyncio.Event,
    registry: ProcessRegistry,
    key: str,
) -> None:
    """Read from the WebSocket and write to the PTY fd.

    Handles both plain text input and JSON-formatted resize messages.
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

        # Write raw input to the PTY and notify activity
        registry.notify_input_activity(key)
        try:
            os.write(fd, raw.encode("utf-8"))
        except OSError:
            logger.debug("PTY write failed for fd=%d", fd)
            break

    cancel_event.set()


async def terminal_websocket_endpoint(ws: WebSocket, key: str) -> None:
    """WebSocket endpoint at ``/ws/terminal/{key}``.

    Bridges the PTY output (via ProcessRegistry drain) and user input
    for the terminal identified by ``key`` with the xterm.js frontend.
    """
    registry = _get_registry(ws)
    proc = registry.get(key)

    if proc is None:
        await ws.close(code=4004, reason=f"Terminal not found: {key}")
        return

    await ws.accept()
    logger.info("Terminal WebSocket connected: key=%s fd=%d pid=%d", key, proc.fd, proc.pid)

    # Subscribe to the persistent drain loop's output.
    # The ring buffer snapshot is replayed immediately so the client
    # sees recent output; Claude's next TUI redraw fills in the rest.
    output_queue = registry.subscribe(key)
    cancel_event = asyncio.Event()

    reader_task = asyncio.create_task(_forward_output(output_queue, ws, cancel_event))
    writer_task = asyncio.create_task(
        _write_pty(proc.fd, ws, cancel_event, registry, key)
    )

    try:
        done, pending = await asyncio.wait(
            [reader_task, writer_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        cancel_event.set()

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
        registry.unsubscribe(key)
        logger.info("Terminal WebSocket disconnected: key=%s", key)
        try:
            await ws.close()
        except Exception:
            pass
