"""AgentHub Linux entry point — uvicorn + pywebview."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from types import FrameType

import uvicorn

from agent_hub.config.settings import Settings
from agent_hub.desktop.window import start_webview

logger = logging.getLogger(__name__)

# Global handle so the signal handler can request a clean stop
_uvicorn_server: uvicorn.Server | None = None


def _signal_handler(sig: int, _frame: FrameType | None) -> None:
    """Gracefully shut down uvicorn when the process receives SIGINT/SIGTERM."""
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True


def _run_uvicorn(host: str, port: int) -> None:
    """Run uvicorn in the calling thread (intended for a background thread)."""
    global _uvicorn_server  # noqa: PLW0603

    config = uvicorn.Config(
        app="agent_hub.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
        # Disable the access log noise in desktop mode
        access_log=False,
    )
    _uvicorn_server = uvicorn.Server(config)
    _uvicorn_server.run()


def _wait_for_server(host: str, port: int, timeout: float = 15.0) -> bool:
    """Block until the HTTP server is accepting connections or *timeout* expires."""
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def main() -> None:
    """Launch the AgentHub desktop application."""
    settings = Settings()

    host = settings.api_host
    port = settings.api_port

    # Register signal handlers so Ctrl-C in the terminal propagates cleanly
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Start uvicorn on a daemon thread so it dies with the main thread
    server_thread = threading.Thread(
        target=_run_uvicorn,
        args=(host, port),
        daemon=True,
        name="uvicorn-server",
    )
    server_thread.start()

    # Block until the server is ready before opening the window
    url = f"http://{host}:{port}"
    if not _wait_for_server(host, port):
        logger.error("Timed out waiting for the API server on %s", url)
        sys.exit(1)

    logger.info("API server ready at %s", url)

    # Try to open pywebview window; fall back to headless mode if no GUI available
    try:
        start_webview(url)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.warning(
            "Could not open desktop window (%s). Running in headless/API-only mode. "
            "Open %s in a browser.",
            exc,
            url,
        )
        # Block on the server thread in headless mode
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass
    finally:
        # Ask uvicorn to shut down
        if _uvicorn_server is not None:
            _uvicorn_server.should_exit = True
        # Give the server thread a moment to flush and close
        server_thread.join(timeout=5.0)

    logger.info("AgentHub exited.")


if __name__ == "__main__":
    main()
