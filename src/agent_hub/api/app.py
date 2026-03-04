"""FastAPI application factory for AgentHub Linux."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agent_hub.config.settings import Settings
from agent_hub.provider import AgentHubProvider

logger = logging.getLogger(__name__)

# Path to the built frontend assets (relative to project root)
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: initialise services on startup, tear down on shutdown."""
    settings = Settings()
    settings.ensure_dirs()

    if settings.enable_debug_logging:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    provider = AgentHubProvider(settings)
    await provider.init()

    # Stash on app.state so route handlers can access them
    app.state.settings = settings
    app.state.provider = provider
    app.state.process_registry = provider.process_registry

    # Wire WebSocket manager into provider callbacks so state changes
    # are automatically broadcast to connected clients.
    from agent_hub.api.websocket.handler import register_provider_callbacks

    register_provider_callbacks(provider)

    logger.info(
        "AgentHub started — API at http://%s:%s",
        settings.api_host,
        settings.api_port,
    )

    yield

    # --- Shutdown ---
    logger.info("AgentHub shutting down...")
    await provider.shutdown()
    logger.info("AgentHub shutdown complete.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AgentHub",
        version="0.1.0",
        description="Linux desktop app for monitoring Claude Code and Codex CLI sessions",
        lifespan=_lifespan,
    )

    # ---- CORS (dev mode) ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:18080",
            "http://127.0.0.1:18080",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Health check ----
    @app.get("/api/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # ---- Register API route routers ----
    _register_route_routers(app)

    # ---- Register WebSocket endpoints ----
    _register_websocket_endpoints(app)

    # ---- Serve frontend static files if built ----
    if _FRONTEND_DIST.is_dir():
        # Mount at root so the SPA index.html is served for all non-API paths.
        # The html=True flag makes StaticFiles serve index.html for directory
        # requests, which is what a single-page app needs.
        app.mount(
            "/",
            StaticFiles(directory=str(_FRONTEND_DIST), html=True),
            name="frontend",
        )
        logger.info("Serving frontend from %s", _FRONTEND_DIST)
    else:
        logger.info(
            "No frontend build found at %s — API-only mode", _FRONTEND_DIST
        )

    return app


def _register_websocket_endpoints(app: FastAPI) -> None:
    """Register WebSocket endpoints on the FastAPI app."""
    from agent_hub.api.websocket.handler import websocket_endpoint
    from agent_hub.api.websocket.terminal_handler import terminal_websocket_endpoint

    app.websocket("/ws")(websocket_endpoint)
    app.websocket("/ws/terminal/{key}")(terminal_websocket_endpoint)
    logger.debug("Registered WebSocket endpoints: /ws, /ws/terminal/{key}")


def _register_route_routers(app: FastAPI) -> None:
    """Discover and include all APIRouter instances from agent_hub.api.routes.

    Each module in the ``api/routes`` package that exposes a module-level
    ``router`` attribute (an ``APIRouter``) will be included automatically.
    """
    import importlib
    import pkgutil

    import agent_hub.api.routes as routes_pkg

    routes_dir = Path(routes_pkg.__file__).resolve().parent if routes_pkg.__file__ else None
    if routes_dir is None:
        return

    for module_info in pkgutil.iter_modules([str(routes_dir)]):
        if module_info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"agent_hub.api.routes.{module_info.name}")
            router = getattr(mod, "router", None)
            if router is not None:
                app.include_router(router)
                logger.debug("Registered route module: %s", module_info.name)
        except Exception:
            logger.exception("Failed to load route module: %s", module_info.name)
