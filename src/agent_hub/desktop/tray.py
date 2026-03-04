"""Optional system tray icon using pystray.

pystray and Pillow are optional dependencies (``pip install agent-hub[tray]``).
If they are not installed the public functions silently return ``None`` so the
rest of the application can work without a tray icon.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Try to import optional dependencies.  If they are unavailable every
# public function in this module gracefully degrades to a no-op.
try:
    import pystray  # type: ignore[import-untyped]
    from PIL import Image, ImageDraw  # type: ignore[import-untyped]

    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False


def _generate_default_icon() -> Image.Image:
    """Generate a simple coloured circle as a fallback tray icon.

    We avoid shipping a separate image file by programmatically drawing a
    32x32 icon.
    """
    size = 32
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Filled circle with a slight gradient feel — solid blue
    draw.ellipse((2, 2, size - 2, size - 2), fill=(66, 133, 244, 255))
    return image


def _on_show_window(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # type: ignore[name-defined]
    """Callback for the 'Show Window' menu item.

    Re-focusing a pywebview window from pystray requires access to the
    webview API.  We import it lazily so this module does not hard-depend on
    a running webview event loop.
    """
    try:
        import webview  # type: ignore[import-untyped]

        windows = webview.windows
        if windows:
            windows[0].restore()
            windows[0].on_top = True
            # Immediately turn off always-on-top after bringing to front
            windows[0].on_top = False
    except Exception:
        logger.exception("Failed to show window from tray")


def _on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # type: ignore[name-defined]
    """Callback for the 'Quit' menu item."""
    try:
        import webview  # type: ignore[import-untyped]

        for window in webview.windows:
            window.destroy()
    except Exception:
        logger.debug("No webview windows to destroy")

    icon.stop()


def create_tray_icon() -> pystray.Icon | None:  # type: ignore[name-defined]
    """Create and return a system tray icon with a context menu.

    Returns ``None`` if ``pystray`` or ``Pillow`` are not installed.  The
    caller is responsible for calling ``icon.run()`` (which blocks) or
    ``icon.run_detached()`` to start the tray event loop.

    Menu items:
      * **Show Window** — brings the pywebview window to the foreground.
      * **Quit** — closes all windows and stops the tray icon.
    """
    if not _HAS_TRAY:
        logger.info(
            "pystray/Pillow not installed — system tray icon disabled. "
            "Install with: pip install agent-hub[tray]"
        )
        return None

    icon_image = _generate_default_icon()

    menu = pystray.Menu(
        pystray.MenuItem("Show Window", _on_show_window, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _on_quit),
    )

    icon = pystray.Icon(
        name="AgentHub",
        icon=icon_image,
        title="AgentHub",
        menu=menu,
    )

    logger.info("System tray icon created")
    return icon
