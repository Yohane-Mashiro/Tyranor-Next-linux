from __future__ import annotations

import os
from pathlib import Path

from . import APP_NAME


def data_home() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "tyranor-next-linux"


def config_home() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "tyranor-next-linux"


def cache_home() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "tyranor-next-linux"


def ensure_dirs() -> None:
    for path in (data_home(), config_home(), cache_home(), data_home() / "covers", data_home() / "saves"):
        path.mkdir(parents=True, exist_ok=True)


def database_path() -> Path:
    ensure_dirs()
    return data_home() / "library.db"


def settings_path() -> Path:
    ensure_dirs()
    return config_home() / "settings.json"


def secrets_path() -> Path:
    ensure_dirs()
    return config_home() / "secrets.json"


def log_path() -> Path:
    ensure_dirs()
    return data_home() / "launcher.log"


def asset_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "assets" / name


def desktop_file() -> str:
    return f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Multi-engine visual novel launcher
Exec=tyranor-next
Icon=tyranor-next
Terminal=false
Categories=Game;AdventureGame;
StartupWMClass=tyranor-next-linux
"""
