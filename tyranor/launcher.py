from __future__ import annotations

import logging
import os
import signal
import shlex
import subprocess
import sys
import threading
import time
import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from .database import Library
from .models import EngineType, GAME_DIR, Game
from .runtimes import RuntimeManager, RuntimeStatus
from .paths import data_home
from .saves import migrate_legacy_saves


class LaunchStatus(str, Enum):
    STARTED = "started"
    MISSING_GAME = "missing_game"
    MISSING_ENTRY = "missing_entry"
    RUNTIME_MISSING = "runtime_missing"
    RUNTIME_NOT_EXECUTABLE = "runtime_not_executable"
    ALREADY_RUNNING = "already_running"
    FAILED = "failed"


@dataclass(slots=True)
class LaunchResult:
    status: LaunchStatus
    message: str
    command: list[str] | None = None
    process: subprocess.Popen | None = None
    history_id: int | None = None

    @property
    def ok(self) -> bool:
        return self.status is LaunchStatus.STARTED


@dataclass(slots=True)
class RunningGame:
    game_uri: str
    process: subprocess.Popen
    started_at: float
    history_id: int
    command: list[str]
    log_file: object | None = None


class Launcher:
    def __init__(
        self,
        library: Library,
        runtimes: RuntimeManager,
        on_started: Callable[[Game, RunningGame], None] | None = None,
        on_exited: Callable[[Game, RunningGame, int], None] | None = None,
    ):
        self.library = library
        self.runtimes = runtimes
        self.on_started = on_started or (lambda *_: None)
        self.on_exited = on_exited or (lambda *_: None)
        self.running: dict[str, RunningGame] = {}
        self._lock = threading.Lock()
        self._closed = False

    def launch(self, game: Game, preview: bool = False) -> LaunchResult:
        with self._lock:
            if game.uri in self.running:
                active = self.running[game.uri]
                if active.process.poll() is None:
                    return LaunchResult(
                        LaunchStatus.ALREADY_RUNNING,
                        f"{game.title} is already running.",
                    )
                self.running.pop(game.uri, None)

        target = self.resolve_target(game)
        if not target:
            return LaunchResult(LaunchStatus.MISSING_GAME, f"Game path no longer exists:\n{game.uri}")
        if game.engine in {EngineType.PSP, EngineType.NINTENDO_SWITCH, EngineType.RUFFLE}:
            if not target.is_file():
                return LaunchResult(LaunchStatus.MISSING_ENTRY, f"Missing entry file:\n{target}")
        if game.launch_file:
            manual = target / game.launch_file if target.is_dir() else target.parent / game.launch_file
            if not manual.exists():
                return LaunchResult(LaunchStatus.MISSING_ENTRY, f"Missing launch file:\n{manual}")
            target = manual

        runtime = self._runtime_for(game)
        if runtime is not None and not runtime.available and game.engine not in {
            EngineType.RENPY,
            EngineType.TYRANO,
            EngineType.RPG_MV,
            EngineType.RPG_MZ,
            EngineType.VN,
            EngineType.WEB_OTHER,
        }:
            wine = self.runtimes.statuses().get("wine")
            game_dir = target if target.is_dir() else target.parent
            exe = _first_windows_executable(game_dir)
            if wine is not None and wine.available and exe is not None:
                runtime = wine
                target = exe
        if runtime is None:
            return LaunchResult(
                LaunchStatus.RUNTIME_MISSING,
                f"No Linux runtime is configured for {game.engine.display_name}.",
            )
        bundled_renpy = (
            game.engine is EngineType.RENPY
            and _renpy_launcher(target if target.is_dir() else target.parent) is not None
        )
        if (not runtime.available or not runtime.executable) and not bundled_renpy:
            status = self.runtimes.resolve(runtime.key)
            return LaunchResult(
                LaunchStatus.RUNTIME_MISSING,
                f"{status.name} is not installed. Configure its executable in Engine settings.",
            )

        if preview:
            command = self.build_command(game, target, runtime)
            return LaunchResult(LaunchStatus.STARTED, "Launch preview", command=command)

        try:
            command = self.build_command(game, target, runtime)
            env = os.environ.copy()
            env.update(runtime.env)
            game_env = game.overrides.get("env", "") if game.overrides else ""
            if game_env:
                for line in str(game_env).splitlines():
                    if "=" in line:
                        key, value = line.split("=", 1)
                        if key.strip():
                            env[key.strip()] = os.path.expandvars(value.strip())
            env.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
            save_path = (
                Path(game.save_dir).expanduser()
                if game.save_dir
                else migrate_legacy_saves(game)
            )
            env["TYRANOR_SAVE_DIR"] = str(save_path)
            if game.engine is EngineType.RENPY:
                env.setdefault("RENPY_LESS_UPDATES", "1")
            log_dir = data_home() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(game.uri.encode("utf-8")).hexdigest()[:16]
            log_file = (log_dir / f"game-{digest}.log").open("ab")
            log_file.write(
                (
                    f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
                    f"{shlex.join(command)}\n"
                ).encode("utf-8")
            )
            log_file.flush()
            process = subprocess.Popen(
                command,
                cwd=str(target.parent if target.is_file() else target),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            if "log_file" in locals():
                log_file.close()
            logging.exception("Launch failed for %s", game.title)
            return LaunchResult(LaunchStatus.FAILED, str(exc))

        history_id = self.library.mark_opened(game.uri)
        running = RunningGame(
            game_uri=game.uri,
            process=process,
            started_at=time.monotonic(),
            history_id=history_id,
            command=command,
            log_file=log_file,
        )
        with self._lock:
            self.running[game.uri] = running
        self.on_started(game, running)
        threading.Thread(
            target=self._watch,
            args=(game, running),
            name=f"launch-watch-{process.pid}",
            daemon=True,
        ).start()
        return LaunchResult(
            LaunchStatus.STARTED,
            f"Launched {game.title}",
            command=command,
            process=process,
            history_id=history_id,
        )

    def resolve_target(self, game: Game) -> Path | None:
        path = Path(game.uri)
        if path.is_dir():
            if game.engine is EngineType.RUFFLE and game.launch_target:
                candidate = path / game.launch_target
                return candidate if candidate.exists() else None
            return path
        if path.is_file():
            return path
        return None

    def stop(self, game: Game) -> bool:
        with self._lock:
            running = self.running.get(game.uri)
        if running is None or running.process.poll() is not None:
            return False
        try:
            os.killpg(os.getpgid(running.process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return False

        def force_after_timeout() -> None:
            try:
                running.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(running.process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

        threading.Thread(target=force_after_timeout, name="launch-stop", daemon=True).start()
        return True

    def log_path(self, game: Game) -> Path:
        digest = hashlib.sha256(game.uri.encode("utf-8")).hexdigest()[:16]
        return data_home() / "logs" / f"game-{digest}.log"

    def detach_tracking(self) -> None:
        """Allow launched games to outlive the launcher without touching a closed DB."""
        self._closed = True

    def build_command(self, game: Game, target: Path, runtime: RuntimeStatus) -> list[str]:
        command = self._build_runtime_command(game, target, runtime)
        prefix = split_args(str(self.runtimes.settings.get("launch_prefix", "")))
        return [*prefix, *command]

    def _build_runtime_command(self, game: Game, target: Path, runtime: RuntimeStatus) -> list[str]:
        save_path = (
            Path(game.save_dir).expanduser()
            if game.save_dir
            else migrate_legacy_saves(game)
        )
        if runtime.key == "web":
            return [
                sys.executable,
                "-m",
                "tyranor.web_host",
                "--root",
                str(target if target.is_dir() else target.parent),
                "--title",
                game.title,
                "--savedata-dir",
                str(save_path),
            ] + (["--entry", game.launch_file] if game.launch_file else [])
        if runtime.key == "renpy":
            bundled = _renpy_launcher(target if target.is_dir() else target.parent)
            if bundled:
                return [str(bundled), "--savedir", str(save_path)]
        executable = runtime.executable or runtime.key
        args = game.custom_args or runtime.args
        if not args:
            args = ["{path}"]
        replacements = {
            "path": str(target),
            "target": str(target if target.is_file() else target / game.launch_target),
            "game_dir": str(target if target.is_dir() else target.parent),
            "title": game.title,
            "launch_file": game.launch_file or "",
        }
        rendered = [_expand_arg(arg, replacements) for arg in args]
        if "{path}" not in " ".join(args) and "{target}" not in " ".join(args) and runtime.key != "renpy":
            rendered.append(str(target))
        return [executable, *rendered]

    def _runtime_for(self, game: Game) -> RuntimeStatus | None:
        statuses = self.runtimes.statuses()
        if game.runtime_id and game.runtime_id in statuses:
            return statuses[game.runtime_id]
        preferred = statuses.get(game.engine.runtime_key)
        if preferred:
            return preferred
        candidates = self.runtimes.candidates_for_engine(game.engine)
        available = [candidate for candidate in candidates if candidate.available]
        return available[0] if available else (candidates[0] if candidates else None)

    def _watch(self, game: Game, running: RunningGame) -> None:
        code = running.process.wait()
        if self._closed:
            with self._lock:
                self.running.pop(game.uri, None)
            return
        if running.log_file is not None:
            try:
                running.log_file.close()
            except OSError:
                pass
        elapsed_ms = int((time.monotonic() - running.started_at) * 1000)
        self.library.mark_closed(running.history_id, code)
        row = self.library.get_game(game.uri)
        if row:
            row.play_time += elapsed_ms
            self.library.save_game(row)
        with self._lock:
            current = self.running.get(game.uri)
            if current is running:
                self.running.pop(game.uri, None)
        self.on_exited(game, running, code)


def _renpy_launcher(directory: Path) -> Path | None:
    preferred = [directory / "renpy.sh"]
    preferred.extend(sorted(directory.glob("*.sh")))
    for path in preferred:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def _first_windows_executable(directory: Path) -> Path | None:
    ignored = ("unins", "uninstall", "setup", "install", "update", "config", "crash")
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.casefold() == ".exe"
        and not any(word in path.name.casefold() for word in ignored)
    ]
    candidates.sort(key=lambda path: (len(path.name), path.name.casefold()))
    return candidates[0] if candidates else None


def _expand_arg(value: str, replacements: dict[str, str]) -> str:
    expanded = value
    for key, replacement in replacements.items():
        expanded = expanded.replace("{" + key + "}", replacement)
    return os.path.expandvars(os.path.expanduser(expanded))


def split_args(value: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError:
        return value.split()
