from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


MAX_HEADER_BYTES = 64 * 1024 * 1024


class AsarError(RuntimeError):
    pass


@dataclass(slots=True)
class AsarEntry:
    path: str
    size: int
    offset: int
    unpacked: bool = False
    executable: bool = False


class AsarArchive:
    def __init__(self, path: Path):
        self.path = path
        self.data_offset = 0
        self.tree: dict = {}
        self._open()

    def _open(self) -> None:
        with self.path.open("rb") as stream:
            prefix = stream.read(8)
            if len(prefix) != 8:
                raise AsarError("Truncated ASAR header.")
            first, header_size = struct.unpack("<II", prefix)
            if first != 4 or header_size <= 8 or header_size > MAX_HEADER_BYTES:
                raise AsarError("Unsupported ASAR header.")
            header = stream.read(header_size)
            if len(header) != header_size:
                raise AsarError("Truncated ASAR JSON header.")
        self.data_offset = 8 + header_size
        try:
            text = header[8:].decode("utf-8", errors="strict")
            self.tree, _ = json.JSONDecoder().raw_decode(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AsarError("Invalid ASAR JSON header.") from exc

    def lookup(self, path: str) -> AsarEntry | None:
        parts = [part for part in PurePosixPath(path.replace("\\", "/")).parts if part not in {"", "."}]
        if any(part == ".." for part in parts):
            return None
        node = self.tree
        for part in parts:
            children = node.get("files")
            if not isinstance(children, dict) or part not in children:
                return None
            node = children[part]
        if node.get("files") is not None:
            return None
        size = node.get("size")
        offset = node.get("offset")
        if not isinstance(size, int) or (offset is None and not node.get("unpacked")):
            return None
        return AsarEntry(
            path="/".join(parts),
            size=size,
            offset=int(offset or 0),
            unpacked=bool(node.get("unpacked")),
            executable=bool(node.get("executable")),
        )

    def lookup_file(self, path: str) -> AsarEntry | None:
        entry = self.lookup(path)
        if entry is not None:
            return entry
        for name in ("index.html", "index.htm"):
            entry = self.lookup(f"{path.rstrip('/')}/{name}" if path else name)
            if entry is not None:
                return entry
        return None

    def exists(self, path: str) -> bool:
        return self.lookup_file(path) is not None

    def open_entry(self, entry: AsarEntry):
        if entry.unpacked:
            unpacked_root = Path(str(self.path) + ".unpacked")
            target = (unpacked_root / entry.path).resolve()
            if not target.is_relative_to(unpacked_root.resolve()) or not target.is_file():
                raise AsarError("ASAR unpacked file is missing.")
            return target.open("rb")
        stream = self.path.open("rb")
        stream.seek(self.data_offset + entry.offset)
        return stream

    def read(self, entry: AsarEntry, start: int = 0, length: int | None = None) -> bytes:
        if start < 0 or start > entry.size:
            raise AsarError("Invalid ASAR byte range.")
        count = entry.size - start if length is None else min(length, entry.size - start)
        with self.open_entry(entry) as stream:
            if not entry.unpacked:
                stream.seek(self.data_offset + entry.offset + start)
            else:
                stream.seek(start)
            data = stream.read(count)
        if len(data) != count:
            raise AsarError("Truncated ASAR file payload.")
        return data
