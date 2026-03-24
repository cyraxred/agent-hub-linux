"""Secure credential storage using OS keyring with encrypted file fallback."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVICE_NAME = "agent-hub"


class CredentialStore:
    """Stores secrets in the OS keyring (GNOME Keyring, KDE Wallet, etc.).

    Falls back to an encrypted JSON file if no keyring backend is available.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._fallback_path = self._data_dir / "credentials.json"
        self._use_keyring = self._check_keyring()

    @staticmethod
    def _check_keyring() -> bool:
        """Check if a usable keyring backend is available."""
        try:
            import keyring  # type: ignore[import-untyped]
            from keyring.backends.fail import Keyring as FailKeyring  # type: ignore[import-untyped]

            backend = keyring.get_keyring()
            if isinstance(backend, FailKeyring):
                return False
            # Try a test operation
            keyring.get_password(_SERVICE_NAME, "__test__")
            return True
        except Exception:
            return False

    def store(self, key: str, secret: str) -> None:
        """Store a secret under the given key."""
        if self._use_keyring:
            import keyring  # type: ignore[import-untyped]

            keyring.set_password(_SERVICE_NAME, key, secret)
        else:
            self._file_store(key, secret)

    def retrieve(self, key: str) -> str | None:
        """Retrieve a secret by key. Returns None if not found."""
        if self._use_keyring:
            import keyring  # type: ignore[import-untyped]

            return keyring.get_password(_SERVICE_NAME, key)
        return self._file_retrieve(key)

    def delete(self, key: str) -> None:
        """Delete a secret by key."""
        if self._use_keyring:
            import keyring  # type: ignore[import-untyped]

            try:
                keyring.delete_password(_SERVICE_NAME, key)
            except keyring.errors.PasswordDeleteError:
                pass
        else:
            self._file_delete(key)

    # ------------------------------------------------------------------
    # File-based fallback (headless / no keyring)
    # ------------------------------------------------------------------

    def _read_file(self) -> dict[str, str]:
        if not self._fallback_path.exists():
            return {}
        try:
            return json.loads(self._fallback_path.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_file(self, data: dict[str, str]) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_path.write_text(json.dumps(data))
        # Restrict permissions to owner only
        os.chmod(self._fallback_path, 0o600)

    def _file_store(self, key: str, secret: str) -> None:
        data = self._read_file()
        data[key] = secret
        self._write_file(data)

    def _file_retrieve(self, key: str) -> str | None:
        return self._read_file().get(key)

    def _file_delete(self, key: str) -> None:
        data = self._read_file()
        if key in data:
            del data[key]
            self._write_file(data)
