from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .models import EngineType, Game


INDEX_URL = "https://zeas2.github.io/Kirikiroid2_patch/patch/alldata.js"
BASE_URL = "https://zeas2.github.io/Kirikiroid2_patch/patch/"
LINE_RE = re.compile(r'^\[(\d+),\s*"(.+?)",\s*"(.+?)",\s*"(.+?)",\s*\[(.+)]],?$')
MAX_BYTES = 200 * 1024 * 1024


class PatchError(RuntimeError):
    pass


@dataclass(slots=True)
class PatchEntry:
    timestamp: int
    brand: str
    path: str
    name: str
    patches: list[str]


def fetch_index() -> list[PatchEntry]:
    response = requests.get(INDEX_URL, timeout=(12, 30), headers={"User-Agent": "TyranorNextLinux/1.0"})
    if response.status_code != 200:
        raise PatchError(f"Patch index returned {response.status_code}.")
    entries: list[PatchEntry] = []
    for line in response.text.splitlines():
        match = LINE_RE.match(line.strip())
        if not match:
            continue
        patches = [
            BASE_URL + part.strip().strip('"')
            for part in match.group(5).split(",")
            if part.strip().strip('"')
        ]
        entries.append(
            PatchEntry(
                int(match.group(1)) * 1000,
                match.group(2),
                match.group(3),
                match.group(4),
                patches,
            )
        )
    return sorted(entries, key=lambda item: (item.name.casefold(), item.brand.casefold()))


def search(entries: list[PatchEntry], keyword: str) -> list[PatchEntry]:
    query = keyword.strip().casefold()
    if not query:
        return entries
    return [
        entry
        for entry in entries
        if query in entry.name.casefold() or query in entry.brand.casefold() or query in entry.path.casefold()
    ]


def install(game: Game, urls: list[str], on_progress=None) -> list[str]:
    on_progress = on_progress or (lambda _: None)
    if game.engine is not EngineType.KIRIKIRI:
        raise PatchError("Online patches are available only for KiriKiri games.")
    if not urls:
        raise PatchError("Select at least one patch.")
    root = Path(game.uri)
    if not root.is_dir() or not root.is_dir() or not _writable(root):
        raise PatchError("The game folder is not writable.")
    installed: list[str] = []
    for url in urls:
        name = Path(unquote(urlparse(url).path)).name or "patch.xp3"
        name = re.sub(r'[\\/:*?"<>|]', "_", name)
        on_progress(f"Downloading {name}…")
        response = requests.get(url, timeout=(12, 120), stream=True, headers={"User-Agent": "TyranorNextLinux/1.0"})
        if response.status_code != 200:
            raise PatchError(f"Download failed ({response.status_code}).")
        with tempfile.NamedTemporaryFile(prefix=f".{name}.", suffix=".tmp", dir=root, delete=False) as stream:
            temp = Path(stream.name)
            total = 0
            for block in response.iter_content(64 * 1024):
                total += len(block)
                if total > MAX_BYTES:
                    stream.close()
                    temp.unlink(missing_ok=True)
                    raise PatchError("Patch exceeds 200 MiB.")
                stream.write(block)
        target = root / name
        on_progress(f"Writing {name}…")
        temp.replace(target)
        installed.append(name)
    return installed


def _writable(path: Path) -> bool:
    try:
        probe = path / ".tyranor-write-probe"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False
