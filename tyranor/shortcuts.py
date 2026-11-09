from __future__ import annotations

import hashlib
import os
import shlex
import sys
from pathlib import Path

from .models import Game
from .paths import asset_path


def create_shortcut(game: Game, executable: str | None = None) -> Path:
    applications = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ) / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(game.uri.encode("utf-8")).hexdigest()[:12]
    path = applications / f"tyranor-next-{key}.desktop"
    installed = executable or _find_executable()
    command = shlex.quote(installed) if installed else f"{shlex.quote(sys.executable)} -m tyranor"
    quote = lambda value: shlex.quote(value)
    icon = str(asset_path("icon.png"))
    project_root = Path(__file__).resolve().parent.parent
    body = f"""[Desktop Entry]
Type=Application
Version=1.0
Name={_escape(game.title)}
Comment=Launch with Tyranor Next Linux
Exec={command} --launch-uri {quote(game.uri)}
Icon={icon}
Path={project_root}
Terminal=false
Categories=Game;
"""
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _find_executable() -> str | None:
    import shutil

    return shutil.which("tyranor-next")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", " ")
