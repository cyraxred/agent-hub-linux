"""Tests for agent_hub.api.routes.settings module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_app(settings_file: Path | None = None) -> FastAPI:
    """Create a FastAPI app with settings routes.

    If settings_file is provided, the provider settings point to that file.
    Otherwise, no provider is configured, so the routes use the default path.
    """
    from agent_hub.api.routes.settings import router

    app = FastAPI()

    if settings_file is not None:
        provider = MagicMock()
        provider.settings.settings_file_path = settings_file
        app.state.provider = provider
    else:
        # No provider at all -- tests the fallback path
        app.state.provider = MagicMock(spec=[])

    app.include_router(router)
    return app


class TestGetSettings:
    """Tests for GET /api/settings."""

    def test_get_settings_empty(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        # File does not exist yet
        app = _create_test_app(settings_file)
        with TestClient(app) as client:
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["settings"] == {}

    def test_get_settings_with_data(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"theme": "dark", "port": 8080}))

        app = _create_test_app(settings_file)
        with TestClient(app) as client:
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["settings"]["theme"] == "dark"
        assert data["settings"]["port"] == 8080

    def test_get_settings_invalid_json(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not valid json {{{")

        app = _create_test_app(settings_file)
        with TestClient(app) as client:
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["settings"] == {}

    def test_get_settings_non_dict_json(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps([1, 2, 3]))

        app = _create_test_app(settings_file)
        with TestClient(app) as client:
            resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["settings"] == {}


class TestUpdateSettings:
    """Tests for PUT /api/settings."""

    def test_update_settings_new_file(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "subdir" / "settings.json"

        app = _create_test_app(settings_file)
        with TestClient(app) as client:
            resp = client.put(
                "/api/settings",
                json={"settings": {"theme": "dark", "port": 9090}},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["settings"]["theme"] == "dark"
        assert data["settings"]["port"] == 9090

        # Verify file was written
        saved = json.loads(settings_file.read_text())
        assert saved["theme"] == "dark"

    def test_update_settings_merge(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"existing_key": "value", "theme": "light"}))

        app = _create_test_app(settings_file)
        with TestClient(app) as client:
            resp = client.put(
                "/api/settings",
                json={"settings": {"theme": "dark"}},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["settings"]["theme"] == "dark"
        assert data["settings"]["existing_key"] == "value"

    def test_update_settings_empty_body(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"key": "val"}))

        app = _create_test_app(settings_file)
        with TestClient(app) as client:
            resp = client.put(
                "/api/settings",
                json={"settings": {}},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["settings"]["key"] == "val"
