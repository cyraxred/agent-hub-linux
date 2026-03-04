"""API route modules -- each exposes a FastAPI ``router``."""

from agent_hub.api.routes.git import router as git_router
from agent_hub.api.routes.repositories import router as repositories_router
from agent_hub.api.routes.search import router as search_router
from agent_hub.api.routes.sessions import router as sessions_router
from agent_hub.api.routes.settings import router as settings_router
from agent_hub.api.routes.stats import router as stats_router
from agent_hub.api.routes.terminal import router as terminal_router

all_routers = [
    sessions_router,
    repositories_router,
    stats_router,
    search_router,
    settings_router,
    git_router,
    terminal_router,
]

__all__ = [
    "all_routers",
    "git_router",
    "repositories_router",
    "search_router",
    "sessions_router",
    "settings_router",
    "stats_router",
    "terminal_router",
]
