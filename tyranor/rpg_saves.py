from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .models import EngineType, Game


STANDARD_NAME = re.compile(r"^(global|config|file\d+)(?:\.(rpgsave|rmmzsave))(\.bak)?$", re.IGNORECASE)
HASHED_NAME = re.compile(r"^key_([0-9a-f]{64})\.bin$", re.IGNORECASE)


class RpgSaveError(RuntimeError):
    pass


@dataclass(slots=True)
class ConvertResult:
    imported: int = 0
    exported: int = 0
    skipped: int = 0
    failed: int = 0
    hashed: int = 0


def content_root(game: Game) -> Path:
    root = Path(game.uri)
    candidates = [root]
    for name in ("www", "game", "resources"):
        candidates.append(root / name)
        candidates.append(root / "www" / name)
    for candidate in candidates:
        if (candidate / "index.html").is_file() or (candidate / "app.asar").is_file():
            return candidate
    return root


def standard_dir(game: Game) -> Path:
    root = content_root(game)
    lower = root / "save"
    upper = root / "Save"
    if lower.is_dir():
        return lower
    if upper.is_dir():
        return upper
    return lower


def tyranor_dir(game: Game) -> Path:
    return Path(game.save_dir) if game.save_dir else Path(game.uri) / "savedata"


def detect_standard(game: Game) -> list[Path]:
    directory = standard_dir(game)
    extension = ".rpgsave" if game.engine is EngineType.RPG_MV else ".rmmzsave"
    if not directory.is_dir():
        return []
    output = []
    for path in directory.iterdir():
        match = STANDARD_NAME.match(path.name)
        if path.is_file() and match and match.group(2).casefold() == extension[1:]:
            if game.engine is EngineType.RPG_MZ and match.group(3):
                continue
            output.append(path)
    return sorted(output, key=lambda path: path.name.casefold())


def convert_to_tyranor(game: Game) -> ConvertResult:
    if game.engine not in {EngineType.RPG_MV, EngineType.RPG_MZ}:
        return ConvertResult()
    source_dir = standard_dir(game)
    target_dir = tyranor_dir(game)
    target_dir.mkdir(parents=True, exist_ok=True)
    original = source_dir / "original"
    original.mkdir(parents=True, exist_ok=True)
    result = ConvertResult()
    for source in detect_standard(game):
        result.hashed += 0
        target_name = _target_name(source.name, game.engine)
        target = target_dir / target_name
        if target.exists():
            result.skipped += 1
        else:
            temporary = target.with_name("." + target.name + ".tmp")
            try:
                shutil.copyfile(source, temporary)
                os.replace(temporary, target)
                shutil.copystat(source, target)
                result.imported += 1
            except OSError:
                temporary.unlink(missing_ok=True)
                result.failed += 1
                continue
        try:
            _move_preserving(source, original / source.name)
        except OSError:
            result.failed += 1
    result.hashed = sum(
        1 for path in target_dir.iterdir() if path.is_file() and HASHED_NAME.match(path.name)
    )
    return result


def export_to_standard(game: Game) -> ConvertResult:
    if game.engine not in {EngineType.RPG_MV, EngineType.RPG_MZ}:
        return ConvertResult()
    source_dir = tyranor_dir(game)
    target_dir = standard_dir(game)
    target_dir.mkdir(parents=True, exist_ok=True)
    result = ConvertResult()
    if not source_dir.is_dir():
        return result
    for source in sorted(source_dir.iterdir(), key=lambda path: path.name.casefold()):
        if not source.is_file():
            continue
        standard_name = _standard_name(source.name, game.engine)
        if standard_name is None:
            if HASHED_NAME.match(source.name):
                result.hashed += 1
            continue
        target = target_dir / standard_name
        if target.exists() and target.stat().st_size == source.stat().st_size:
            if target.read_bytes() == source.read_bytes():
                result.skipped += 1
                continue
        temporary = target.with_name("." + target.name + ".tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
            shutil.copystat(source, target)
            result.exported += 1
        except OSError:
            temporary.unlink(missing_ok=True)
            result.failed += 1
    return result


def _target_name(standard_name: str, engine: EngineType) -> str:
    match = STANDARD_NAME.match(standard_name)
    if not match:
        raise RpgSaveError(f"Unsupported RPG save name: {standard_name}")
    stem = match.group(1).casefold()
    backup = "bak" if match.group(3) else ""
    if engine is EngineType.RPG_MZ:
        return stem + backup + ".bin"
    key = "RPG " + stem.replace("file", "File").title().replace("Global", "Global").replace("Config", "Config")
    key += backup
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", key):
        return key + ".bin"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"key_{digest}.bin"


def _standard_name(name: str, engine: EngineType) -> str | None:
    lower = name.casefold()
    suffix = ".bin"
    if not lower.endswith(suffix):
        return None
    stem = lower[: -len(suffix)]
    backup = stem.endswith("bak")
    if backup:
        stem = stem[:-3]
    if engine is EngineType.RPG_MZ:
        if stem not in {"global", "config"} and not re.fullmatch(r"file\d+", stem):
            return None
        extension = ".rmmzsave"
    else:
        legacy = re.fullmatch(r"rpg (global|config|file\d+)(bak)?", stem)
        if legacy:
            stem = legacy.group(1).replace(" ", "")
        elif HASHED_NAME.match(name):
            # Reverse only standard slot names. Rebuild the MV key and test its digest.
            for candidate in _mv_candidates():
                for candidate_backup in (False, True):
                    key = candidate + ("bak" if candidate_backup else "")
                    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
                    if ("key_" + digest + ".bin") == lower:
                        stem = candidate.removeprefix("RPG ").casefold()
                        backup = candidate_backup
                        break
                else:
                    continue
                break
            else:
                return None
        else:
            return None
        extension = ".rpgsave"
    if stem not in {"global", "config"} and not re.fullmatch(r"file\d+", stem):
        return None
    return stem + extension + (".bak" if backup else "")


def _mv_candidates() -> list[str]:
    return ["RPG Global", "RPG Config"] + [f"RPG File{index}" for index in range(1000)]


def _move_preserving(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stem, suffix = target.stem, target.suffix
        index = 1
        while target.exists():
            target = target.with_name(f"{stem}_{index}{suffix}")
            index += 1
    try:
        source.replace(target)
    except OSError:
        shutil.copy2(source, target)
        source.unlink()
