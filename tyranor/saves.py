from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .database import Library
from .models import EngineType, Game
from .paths import data_home


MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 64 * 1024 * 1024


class SaveError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class SaveLocation:
    path: Path
    kind: str


@dataclass(slots=True)
class SaveVersion:
    version_id: str
    uri: str
    archive_path: Path
    content_hash: str
    created_at: int
    source: str


class SaveManager:
    def __init__(
        self,
        library: Library,
        is_running: Callable[[str], bool] | None = None,
        root: Path | None = None,
    ):
        self.library = library
        self.is_running = is_running or (lambda _: False)
        self.root = root or data_home() / "saves"
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def resolve(self, game: Game) -> SaveLocation | None:
        if game.save_dir:
            custom = Path(game.save_dir).expanduser()
            return SaveLocation(custom, "custom")
        migrate_legacy_saves(game, self.root)
        return SaveLocation(game_data_dir(game, self.root), "managed")

    def managed_dir(self, game: Game) -> Path:
        path = game_managed_dir(game, self.root)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def versions(self, game: Game) -> list[SaveVersion]:
        rows = self.library.save_versions(game.uri)
        output: list[SaveVersion] = []
        for row in rows:
            path = Path(row["archive_path"])
            if not path.is_file():
                continue
            output.append(
                SaveVersion(
                    version_id=row["id"],
                    uri=row["uri"],
                    archive_path=path,
                    content_hash=row["content_hash"],
                    created_at=int(row["created_at"]),
                    source=row["source"],
                )
            )
        return output

    def export_zip(self, game: Game, destination: Path, create_version: bool = True) -> Path:
        self._guard_running(game)
        location = self.resolve(game)
        if location is None:
            raise SaveError("NO_SAVE_DIRECTORY", "No save directory was found for this game.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_handle, temp_name = tempfile.mkstemp(prefix=".save-export-", suffix=".zip", dir=destination.parent)
        os.close(temp_handle)
        temp = Path(temp_name)
        try:
            with self._game_lock(game):
                _write_zip(location.path, temp)
            os.replace(temp, destination)
            if create_version:
                self._register_version(game, destination)
            return destination
        finally:
            temp.unlink(missing_ok=True)

    def create_version(self, game: Game) -> SaveVersion:
        location = self.resolve(game)
        if location is None:
            raise SaveError("NO_SAVE_DIRECTORY", "No save directory was found for this game.")
        version_dir = self.managed_dir(game) / "versions"
        version_dir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        temp = version_dir / f".{stamp}.tmp.zip"
        _write_zip(location.path, temp)
        digest = archive_hash(temp)
        latest = self.versions(game)
        if latest and latest[0].content_hash == digest and latest[0].archive_path.is_file():
            temp.unlink(missing_ok=True)
            return latest[0]
        version_id = f"{stamp}-{digest[:12]}.zip"
        target = version_dir / version_id
        os.replace(temp, target)
        self.library.add_save_version(version_id, game.uri, str(target), digest, "local")
        return SaveVersion(version_id, game.uri, target, digest, stamp, "local")

    def _register_version(self, game: Game, source: Path) -> SaveVersion:
        version_dir = self.managed_dir(game) / "versions"
        version_dir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        digest = archive_hash(source)
        latest = self.versions(game)
        if latest and latest[0].content_hash == digest and latest[0].archive_path.is_file():
            return latest[0]
        version_id = f"{stamp}-{digest[:12]}.zip"
        target = version_dir / version_id
        shutil.copyfile(source, target)
        self.library.add_save_version(version_id, game.uri, str(target), digest, "local")
        return SaveVersion(version_id, game.uri, target, digest, stamp, "local")

    def import_zip(self, game: Game, archive: Path) -> None:
        self._guard_running(game)
        location = self.resolve(game)
        if location is None:
            raise SaveError("NO_SAVE_DIRECTORY", "No save directory was found for this game.")
        destination = location.path
        temporary = Path(tempfile.mkdtemp(prefix=".save-import-", dir=destination.parent))
        backup = destination.with_name(destination.name + ".import_orphan_" + str(os.getpid()))
        try:
            with self._game_lock(game):
                _extract_zip(archive, temporary)
                if destination.exists():
                    os.replace(destination, backup)
                os.replace(temporary, destination)
                temporary = destination
                if backup.exists():
                    shutil.rmtree(backup)
        except Exception:
            if backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise
        finally:
            if temporary != destination:
                shutil.rmtree(temporary, ignore_errors=True)
            if backup.exists() and destination.exists():
                shutil.rmtree(backup, ignore_errors=True)

    def restore_version(self, game: Game, version_id: str) -> None:
        version = next((item for item in self.versions(game) if item.version_id == version_id), None)
        if version is None:
            raise SaveError("VERSION_MISSING", "The selected save version is missing.")
        if not verify_archive(version.archive_path, version.content_hash):
            raise SaveError("CORRUPT_ARCHIVE", "The selected save version failed integrity verification.")
        self.create_version(game)
        self.import_zip(game, version.archive_path)

    def delete_version(self, game: Game, version_id: str) -> None:
        version = next((item for item in self.versions(game) if item.version_id == version_id), None)
        if version:
            version.archive_path.unlink(missing_ok=True)
            self.library.delete_save_version(version_id)

    def clear_saves(self, game: Game) -> None:
        self._guard_running(game)
        location = self.resolve(game)
        if location is None:
            return
        with self._game_lock(game):
            for child in location.path.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)

    def configure(self, game: Game, path: Path) -> None:
        game.save_dir = str(path.expanduser().resolve())
        self.library.save_game(game)

    def _guard_running(self, game: Game) -> None:
        if self.is_running(game.uri):
            raise SaveError("GAME_RUNNING", "Close the game before changing its saves.")

    @contextmanager
    def _game_lock(self, game: Game) -> Iterator[None]:
        with self._locks_guard:
            lock = self._locks.setdefault(game.uri, threading.RLock())
        with lock:
            yield


def archive_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def game_managed_dir(game: Game, root: Path | None = None) -> Path:
    saves_root = root or data_home() / "saves"
    key = hashlib.sha256(game.uri.encode("utf-8")).hexdigest()[:20]
    return saves_root / f"game-{key}"


def game_data_dir(game: Game, root: Path | None = None) -> Path:
    path = game_managed_dir(game, root) / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_save_candidates(game: Game) -> list[Path]:
    directory = Path(game.uri)
    game_root = directory if directory.is_dir() else directory.parent
    if game.engine is EngineType.RENPY:
        return [
            game_root / "game" / "saves",
            game_root / "saves",
            Path.home() / ".renpy" / game_root.name,
        ]
    if game.engine is EngineType.ETHORNELL:
        return [game_root / "UserData", game_root / "userdata", game_root / "savedata"]
    if game.engine is EngineType.XSYS35:
        return [game_root / "savedata", game_root / "SaveData", game_root / "save"]
    return [game_root / "savedata", game_root / "save", game_root / "saves"]


def migrate_legacy_saves(game: Game, root: Path | None = None) -> Path:
    destination = game_data_dir(game, root)
    for source in legacy_save_candidates(game):
        if not source.is_dir() or source.resolve() == destination.resolve():
            continue
        for current, dirs, files in os.walk(source):
            current_path = Path(current)
            relative = current_path.relative_to(source)
            target_dir = destination / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            dirs[:] = [
                name
                for name in dirs
                if not (current_path / name).is_symlink()
            ]
            for name in files:
                source_file = current_path / name
                target_file = target_dir / name
                if source_file.is_symlink() or target_file.exists():
                    continue
                shutil.copy2(source_file, target_file)
    return destination


def verify_archive(path: Path, expected_hash: str) -> bool:
    return path.is_file() and archive_hash(path) == expected_hash


def _write_zip(directory: Path, destination: Path) -> None:
    total = 0
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
            for name in sorted(files):
                path = Path(root) / name
                if path.is_symlink() or not path.is_file():
                    continue
                size = path.stat().st_size
                if size > MAX_SINGLE_FILE_BYTES:
                    raise SaveError("FILE_TOO_LARGE", f"Save file exceeds 64 MiB: {path.name}")
                total += size
                if total > MAX_ARCHIVE_BYTES:
                    raise SaveError("ARCHIVE_TOO_LARGE", "Save directory exceeds 1 GiB.")
                archive.write(path, path.relative_to(directory).as_posix())


def _extract_zip(archive_path: Path, destination: Path) -> None:
    if not archive_path.is_file():
        raise SaveError("ARCHIVE_MISSING", "The save archive does not exist.")
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise SaveError("ARCHIVE_TOO_LARGE", "The save archive exceeds 1 GiB.")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        total = 0
        for info in archive.infolist():
            normalized = Path(info.filename.replace("\\", "/"))
            if normalized.is_absolute() or ".." in normalized.parts:
                raise SaveError("INVALID_ARCHIVE", "The save archive contains an unsafe path.")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise SaveError("INVALID_ARCHIVE", "Symbolic links are not allowed in save archives.")
            if info.file_size > MAX_SINGLE_FILE_BYTES:
                raise SaveError("FILE_TOO_LARGE", f"{info.filename} exceeds 64 MiB.")
            total += info.file_size
            if total > MAX_ARCHIVE_BYTES:
                raise SaveError("ARCHIVE_TOO_LARGE", "The expanded archive exceeds 1 GiB.")
        archive.extractall(destination)
