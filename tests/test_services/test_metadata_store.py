"""Tests for agent_hub.services.metadata_store module."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_hub.services.metadata_store import MetadataStore


# ---------- MetadataStore ----------


class TestMetadataStore:
    """Tests for the MetadataStore async CRUD operations."""

    @pytest.fixture()
    async def store(self, tmp_path: Path) -> MetadataStore:
        db_path = tmp_path / "test.db"
        s = MetadataStore(db_path)
        await s.init_db()
        return s

    async def test_init_db_creates_tables(self, store: MetadataStore) -> None:
        # If init_db didn't raise, tables exist
        # Verify by doing a read
        result = await store.get_metadata("nonexistent")
        assert result is None

    async def test_upsert_and_get_metadata(self, store: MetadataStore) -> None:
        row = await store.upsert_metadata("sess-001", custom_name="My Session")
        assert row.session_id == "sess-001"
        assert row.custom_name == "My Session"

        fetched = await store.get_metadata("sess-001")
        assert fetched is not None
        assert fetched.custom_name == "My Session"

    async def test_upsert_metadata_update(self, store: MetadataStore) -> None:
        await store.upsert_metadata("sess-001", custom_name="Original")
        await store.upsert_metadata("sess-001", custom_name="Updated")

        fetched = await store.get_metadata("sess-001")
        assert fetched is not None
        assert fetched.custom_name == "Updated"

    async def test_delete_metadata(self, store: MetadataStore) -> None:
        await store.upsert_metadata("sess-001", custom_name="Test")
        await store.delete_metadata("sess-001")

        fetched = await store.get_metadata("sess-001")
        assert fetched is None

    async def test_delete_nonexistent_metadata(self, store: MetadataStore) -> None:
        # Should not raise
        await store.delete_metadata("nonexistent")

    async def test_get_metadata_nonexistent(self, store: MetadataStore) -> None:
        result = await store.get_metadata("nonexistent")
        assert result is None

    async def test_upsert_and_get_repo_mapping(self, store: MetadataStore) -> None:
        row = await store.upsert_repo_mapping(
            "sess-001", "/home/user/repo", "/home/user/repo/wt"
        )
        assert row.session_id == "sess-001"
        assert row.parent_repo_path == "/home/user/repo"
        assert row.worktree_path == "/home/user/repo/wt"

        fetched = await store.get_repo_mapping("sess-001")
        assert fetched is not None
        assert fetched.parent_repo_path == "/home/user/repo"

    async def test_upsert_repo_mapping_update(self, store: MetadataStore) -> None:
        await store.upsert_repo_mapping("sess-001", "/repo", "/repo/wt1")
        await store.upsert_repo_mapping("sess-001", "/repo", "/repo/wt2")

        fetched = await store.get_repo_mapping("sess-001")
        assert fetched is not None
        assert fetched.worktree_path == "/repo/wt2"

    async def test_get_mappings_for_repo(self, store: MetadataStore) -> None:
        await store.upsert_repo_mapping("s1", "/repo", "/repo/wt1")
        await store.upsert_repo_mapping("s2", "/repo", "/repo/wt2")
        await store.upsert_repo_mapping("s3", "/other-repo", "/other-repo/wt")

        mappings = await store.get_mappings_for_repo("/repo")
        assert len(mappings) == 2
        session_ids = {m.session_id for m in mappings}
        assert session_ids == {"s1", "s2"}

    async def test_delete_repo_mapping(self, store: MetadataStore) -> None:
        await store.upsert_repo_mapping("sess-001", "/repo", "/repo/wt")
        await store.delete_repo_mapping("sess-001")

        fetched = await store.get_repo_mapping("sess-001")
        assert fetched is None

    async def test_delete_nonexistent_repo_mapping(self, store: MetadataStore) -> None:
        # Should not raise
        await store.delete_repo_mapping("nonexistent")

    async def test_close(self, store: MetadataStore) -> None:
        await store.close()
        # Calling close multiple times should be safe
        await store.close()
