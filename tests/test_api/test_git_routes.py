"""Tests for agent_hub.api.routes.git module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_hub.models.git_diff import DiffMode, GitDiffFileEntry, GitDiffState


def _create_test_app() -> FastAPI:
    """Create a FastAPI app with git routes registered."""
    from agent_hub.api.routes.git import router

    app = FastAPI()
    app.state.provider = MagicMock()
    app.include_router(router)
    return app


class TestGetDiffRoute:
    """Tests for GET /api/git/diff."""

    @patch("agent_hub.services.git_diff_service.get_changes", new_callable=AsyncMock)
    def test_get_diff_success(self, mock_get_changes: AsyncMock) -> None:
        mock_get_changes.return_value = GitDiffState(
            files=[
                GitDiffFileEntry(
                    file_path="/repo/src/main.py",
                    relative_path="src/main.py",
                    additions=10,
                    deletions=5,
                ),
            ]
        )

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/git/diff",
                params={"repo_path": "/repo", "mode": "unstaged"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo_path"] == "/repo"
        assert data["mode"] == "unstaged"
        assert data["diff"]["file_count"] == 1

    @patch("agent_hub.services.git_diff_service.get_changes", new_callable=AsyncMock)
    def test_get_diff_with_file_filter(self, mock_get_changes: AsyncMock) -> None:
        mock_get_changes.return_value = GitDiffState(
            files=[
                GitDiffFileEntry(
                    file_path="/repo/a.py",
                    relative_path="a.py",
                ),
                GitDiffFileEntry(
                    file_path="/repo/b.py",
                    relative_path="b.py",
                ),
            ]
        )

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/git/diff",
                params={"repo_path": "/repo", "file_path": "/repo/a.py"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["diff"]["file_count"] == 1

    @patch("agent_hub.services.git_diff_service.get_changes", new_callable=AsyncMock)
    def test_get_diff_error(self, mock_get_changes: AsyncMock) -> None:
        from agent_hub.services.git_diff_service import GitDiffError

        mock_get_changes.side_effect = GitDiffError("Not a git repo")

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/git/diff",
                params={"repo_path": "/bad"},
            )
        assert resp.status_code == 400


class TestGetUnifiedDiffRoute:
    """Tests for GET /api/git/diff/unified."""

    @patch("agent_hub.services.git_diff_service.get_unified_diff_output", new_callable=AsyncMock)
    def test_success(self, mock_get_unified: AsyncMock) -> None:
        mock_get_unified.return_value = "diff --git a/file.py b/file.py\n+new line\n"

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/git/diff/unified",
                params={"repo_path": "/repo"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "diff_text" in data
        assert "new line" in data["diff_text"]

    @patch("agent_hub.services.git_diff_service.get_unified_diff_output", new_callable=AsyncMock)
    def test_error(self, mock_get_unified: AsyncMock) -> None:
        from agent_hub.services.git_diff_service import GitDiffError

        mock_get_unified.side_effect = GitDiffError("fail")

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/git/diff/unified",
                params={"repo_path": "/bad"},
            )
        assert resp.status_code == 400


class TestGetFileDiffRoute:
    """Tests for GET /api/git/diff/file."""

    @patch("agent_hub.services.git_diff_service.get_file_diff", new_callable=AsyncMock)
    def test_success(self, mock_file_diff: AsyncMock) -> None:
        mock_file_diff.return_value = ("old content", "new content")

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/git/diff/file",
                params={"file_path": "/repo/main.py", "repo_path": "/repo"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_path"] == "/repo/main.py"
        assert data["old_content"] == "old content"
        assert data["new_content"] == "new content"


class TestGetGitRootRoute:
    """Tests for GET /api/git/root."""

    @patch("agent_hub.services.git_diff_service.find_git_root", new_callable=AsyncMock)
    def test_success(self, mock_find_root: AsyncMock) -> None:
        mock_find_root.return_value = "/home/user/repo"

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/git/root",
                params={"path": "/home/user/repo/src"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["git_root"] == "/home/user/repo"

    @patch("agent_hub.services.git_diff_service.find_git_root", new_callable=AsyncMock)
    def test_not_a_repo(self, mock_find_root: AsyncMock) -> None:
        from agent_hub.services.git_diff_service import GitDiffError

        mock_find_root.side_effect = GitDiffError("Not a git repository")

        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/git/root",
                params={"path": "/tmp/nope"},
            )
        assert resp.status_code == 400
