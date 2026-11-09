from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import settings_path


DEFAULT_COVER_ORDER = ["nextmoe", "vndb", "bangumi", "steam"]
COVER_SOURCES = {
    "nextmoe": "NextMoe",
    "vndb": "VNDB",
    "bangumi": "Bangumi",
    "steam": "Steam",
    "hikarinagi": "Hikarinagi",
}

DEFAULTS: dict[str, Any] = {
    "language": "zh_CN",
    "appearance_style": "default",
    "appearance_mode": "system",
    "accent": "#5B8DEF",
    "corner_radius": 15,
    "particles": True,
    "scan_depth": 3,
    "card_style": "grid",
    "sort_mode": "title",
    "sort_ignore_tags": False,
    "hide_title_tags": False,
    "home_mode": "native",
    "home_url": "https://www.letmoe.co/",
    "cover_order": DEFAULT_COVER_ORDER,
    "cover_enabled": {key: key != "hikarinagi" for key in COVER_SOURCES},
    "cover_only_missing": True,
    "vndb_large_cover": True,
    "hikarinagi_client_id": "",
    "hikarinagi_token_expires_at": 0,
    "save_sync_enabled": False,
    "save_sync_url": "",
    "save_sync_username": "",
    "save_sync_mode": "bidirectional",
    "save_sync_retention": 10,
    "save_sync_feedback": True,
    "minimize_on_launch": False,
    "close_after_launch": False,
    "launch_prefix": "",
    "runtime_overrides": {},
    "recent_limit": 20,
    "quick_limit": 3,
    "last_page": "home",
    "onboarding_done": False,
    "window_geometry": "",
    "window_state": "",
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or settings_path()
        self._data = deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._data = _merge(DEFAULTS, loaded)
        except (OSError, ValueError):
            backup = self.path.with_suffix(".json.bad")
            try:
                self.path.replace(backup)
            except OSError:
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(self._data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        self._data[key] = value
        if persist:
            self.save()

    def update(self, values: dict[str, Any]) -> None:
        self._data.update(values)
        self.save()

    def pop(self, key: str, default: Any = None) -> Any:
        value = self._data.pop(key, default)
        self.save()
        return value

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def runtime_override(self, runtime_key: str) -> dict[str, Any]:
        overrides = self.get("runtime_overrides", {})
        value = overrides.get(runtime_key, {}) if isinstance(overrides, dict) else {}
        return value if isinstance(value, dict) else {}


def _merge(defaults: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result
