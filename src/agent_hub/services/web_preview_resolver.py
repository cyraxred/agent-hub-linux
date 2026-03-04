"""Framework detection from package.json for web preview."""

from __future__ import annotations

from agent_hub.services.dev_server_manager import detect_framework

# Re-export
__all__ = ["detect_framework"]
