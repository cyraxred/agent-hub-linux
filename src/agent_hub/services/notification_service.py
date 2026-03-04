"""Desktop notification service using notify-send (freedesktop)."""

from __future__ import annotations

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)


async def send_notification(
    title: str,
    body: str,
    urgency: str = "normal",
    icon: str = "dialog-information",
) -> None:
    """Send a desktop notification via notify-send.

    Args:
        title: Notification title.
        body: Notification body text.
        urgency: One of 'low', 'normal', 'critical'.
        icon: Icon name or path.
    """
    notify_send = shutil.which("notify-send")
    if notify_send is None:
        logger.debug("notify-send not found, skipping notification")
        return

    try:
        proc = await asyncio.create_subprocess_exec(
            notify_send,
            "--urgency", urgency,
            "--icon", icon,
            "--app-name", "AgentHub",
            title,
            body,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (asyncio.TimeoutError, OSError):
        logger.debug("Failed to send notification", exc_info=True)


async def notify_approval_needed(session_id: str, tool_name: str) -> None:
    """Send a notification that a session needs tool approval."""
    await send_notification(
        title="Approval Needed",
        body=f"Session {session_id[:8]} needs approval for {tool_name}",
        urgency="critical",
        icon="dialog-warning",
    )
