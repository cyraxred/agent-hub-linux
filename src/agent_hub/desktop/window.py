"""pywebview window lifecycle for AgentHub Linux."""

from __future__ import annotations

import logging

import webview  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Default dimensions
_DEFAULT_WIDTH = 1400
_DEFAULT_HEIGHT = 900
_MIN_WIDTH = 800
_MIN_HEIGHT = 600


def create_window(
    title: str,
    url: str,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> webview.Window:
    """Create a pywebview window pointing at *url*.

    The window is created but the event loop is **not** started — call
    :func:`start_webview` for the full lifecycle or use ``webview.start()``
    manually after this returns.

    Parameters
    ----------
    title:
        Window title.
    url:
        URL to load inside the webview.
    width:
        Initial window width in pixels.
    height:
        Initial window height in pixels.

    Returns
    -------
    webview.Window
        The newly created window handle.
    """
    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        resizable=True,
        min_size=(_MIN_WIDTH, _MIN_HEIGHT),
        text_select=True,
    )
    logger.info("Created webview window: %s (%dx%d) -> %s", title, width, height, url)
    return window


def start_webview(
    url: str,
    title: str = "AgentHub",
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> None:
    """Create a window and start the pywebview event loop.

    This function **blocks** until the user closes the window.

    Parameters
    ----------
    url:
        URL the webview should navigate to (typically the local API server).
    title:
        Window title bar text.
    width:
        Initial window width.
    height:
        Initial window height.
    """
    create_window(title=title, url=url, width=width, height=height)

    # ``webview.start()`` enters the platform GUI event loop and blocks until
    # all windows are closed.  On Linux this defaults to the GTK backend.
    webview.start(
        debug=False,
        http_server=False,
    )
    logger.info("Webview event loop exited.")
