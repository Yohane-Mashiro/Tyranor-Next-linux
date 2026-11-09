from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .paths import secrets_path


class SecretStore:
    def __init__(self, path: Path | None = None):
        self.path = path or secrets_path()
        self.key_path = self.path.with_suffix(".key")
        self._key = self._load_key()

    def _load_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.is_file():
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(key)
        return key

    def set(self, key: str, value: str) -> None:
        values = self._load()
        values[key] = Fernet(self._key).encrypt(value.encode("utf-8")).decode("ascii")
        self._save(values)

    def get(self, key: str, default: str = "") -> str:
        token = self._load().get(key)
        if not token:
            return default
        try:
            return Fernet(self._key).decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return default

    def delete(self, key: str) -> None:
        values = self._load()
        values.pop(key, None)
        self._save(values)

    def _load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save(self, values: dict[str, str]) -> None:
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(values, stream)
        os.replace(temporary, self.path)
