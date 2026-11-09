from __future__ import annotations

import io
import os
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


XP3_MAGIC = b"XP3\r\n \n\x1a\x8b\x67"
CURRENT_VERSION = 0x17
VERSION_IDENTIFIER = 0x80
CHUNK_FILE = 0x656C6946
CHUNK_INFO = 0x6F666E69
CHUNK_SEGM = 0x6D676573
CHUNK_ADLR = 0x726C6461
CHUNK_TIME = 0x656D6974
PROTECTED_FLAG = 0x80000000
MAX_ENTRY_COUNT = 1_000_000
MAX_INDEX_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
KSD_PROBE_MAX = 16 * 1024 * 1024


class ArchiveError(RuntimeError):
    pass


class ArchiveConflict(ArchiveError):
    pass


@dataclass(slots=True)
class Segment:
    compressed: bool
    start: int
    size: int
    archive_size: int


@dataclass(slots=True)
class Xp3Entry:
    name: str
    size: int
    archive_size: int
    checksum: int
    protected: bool
    segments: list[Segment]


class Xp3Archive:
    def __init__(self, path: Path):
        self.path = path
        self.entries: list[Xp3Entry] = []
        self._data_start = 0
        self._open()

    def _open(self) -> None:
        with self.path.open("rb") as stream:
            self._data_start = stream.tell()
            header = stream.read(11)
            if len(header) != 11 or header[:10] != XP3_MAGIC:
                raise ArchiveError("Not a Kirikiri XP3 archive.")
            version_value = struct.unpack("<Q", stream.read(8))[0]
            if version_value == CURRENT_VERSION:
                stream.read(4)
                if stream.read(1) != bytes([VERSION_IDENTIFIER]):
                    raise ArchiveError("Unsupported XP3 version header.")
                stream.read(8)
                index_start = struct.unpack("<Q", stream.read(8))[0]
            else:
                index_start = version_value
            stream.seek(self._data_start + index_start)
            index = self._read_index(stream)
        self._parse_index(index)

    @staticmethod
    def _read_index(stream) -> bytes:
        compressed = stream.read(1) != b"\x00"
        size = struct.unpack("<Q", stream.read(8))[0]
        if size > MAX_INDEX_BYTES:
            raise ArchiveError("XP3 index is too large.")
        if compressed:
            original_size = struct.unpack("<Q", stream.read(8))[0]
            if original_size > MAX_INDEX_BYTES:
                raise ArchiveError("XP3 decompressed index is too large.")
            compressed_data = stream.read(size)
            if len(compressed_data) != size:
                raise ArchiveError("Truncated XP3 index.")
            try:
                decoder = zlib.decompressobj()
                data = decoder.decompress(compressed_data, MAX_INDEX_BYTES + 1)
                if len(data) > MAX_INDEX_BYTES or decoder.unconsumed_tail:
                    raise ArchiveError("XP3 decompressed index is too large.")
                data += decoder.flush()
            except zlib.error as exc:
                raise ArchiveError("Unable to decompress XP3 index.") from exc
            if len(data) != original_size or len(data) > MAX_INDEX_BYTES:
                raise ArchiveError("XP3 index size mismatch.")
            return data
        data = stream.read(size)
        if len(data) != size:
            raise ArchiveError("Truncated XP3 index.")
        return data

    def _parse_index(self, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            key, payload, offset = _read_chunk(data, offset)
            if key == CHUNK_FILE:
                entry = self._parse_file_chunk(payload)
                self.entries.append(entry)
                if len(self.entries) > MAX_ENTRY_COUNT:
                    raise ArchiveError("XP3 contains too many entries.")

    @staticmethod
    def _parse_file_chunk(data: bytes) -> Xp3Entry:
        offset = 0
        name = ""
        size = archive_size = checksum = 0
        protected = False
        segments: list[Segment] = []
        while offset < len(data):
            key, payload, offset = _read_chunk(data, offset)
            if key == CHUNK_INFO:
                if len(payload) < 22:
                    raise ArchiveError("Truncated XP3 file info.")
                flags, size, archive_size = struct.unpack_from("<IQQ", payload, 0)
                protected = flags == PROTECTED_FLAG
                name_length = struct.unpack_from("<H", payload, 20)[0]
                name_end = 22 + name_length * 2
                if name_end > len(payload):
                    raise ArchiveError("Truncated XP3 file name.")
                name = payload[22:name_end].decode("utf-16-le", errors="replace")
            elif key == CHUNK_SEGM:
                if len(payload) % 28:
                    raise ArchiveError("Invalid XP3 segment table.")
                for index in range(0, len(payload), 28):
                    compressed, start, raw_size, stored_size = struct.unpack_from("<IQQQ", payload, index)
                    segments.append(Segment(bool(compressed), start, raw_size, stored_size))
            elif key == CHUNK_ADLR and len(payload) >= 4:
                checksum = struct.unpack_from("<I", payload)[0]
        if not name or not segments:
            raise ArchiveError("XP3 entry has no name or data segment.")
        return Xp3Entry(name, size, archive_size, checksum, protected, segments)

    def read(self, entry: Xp3Entry) -> bytes:
        if entry.size > 512 * 1024 * 1024:
            raise ArchiveError("Use streaming extraction for large XP3 entries.")
        payload = b"".join(self.iter_entry(entry))
        if len(payload) <= KSD_PROBE_MAX:
            payload = ksd_mode2_decode(payload) or payload
        return payload

    def iter_entry(self, entry: Xp3Entry):
        limit = min(MAX_FILE_BYTES, entry.size + 1024 * 1024 * 1024)
        emitted = 0
        with self.path.open("rb") as stream:
            for segment in entry.segments:
                stream.seek(self._data_start + segment.start)
                remaining = segment.archive_size
                decoder = zlib.decompressobj() if segment.compressed else None
                while remaining:
                    stored = stream.read(min(64 * 1024, remaining))
                    if not stored:
                        raise ArchiveError(f"Truncated XP3 segment for {entry.name}.")
                    remaining -= len(stored)
                    if decoder is not None:
                        try:
                            data = decoder.decompress(stored, limit - emitted + 1)
                        except zlib.error as exc:
                            raise ArchiveError(f"Unable to decompress {entry.name}.") from exc
                    else:
                        data = stored
                    emitted += len(data)
                    if emitted > limit:
                        raise ArchiveError(f"Expanded file is too large: {entry.name}")
                    if data:
                        yield data
                if decoder is not None:
                    tail = decoder.flush()
                    emitted += len(tail)
                    if emitted > limit:
                        raise ArchiveError(f"Expanded file is too large: {entry.name}")
                    if tail:
                        yield tail

    def list_entries(self) -> list[tuple[str, int, bool]]:
        directories: set[str] = set()
        for entry in self.entries:
            parts = entry.name.replace("\\", "/").split("/")
            for index in range(1, len(parts)):
                directories.add("/".join(parts[:index]))
        values = [(name, 0, True) for name in directories]
        values.extend((entry.name.replace("\\", "/"), entry.size, False) for entry in self.entries)
        return sorted(values, key=lambda item: item[0])


class ArchiveTool:
    def __init__(self):
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def scan(self, root: Path, max_depth: int = 6, max_archives: int = 500) -> list[Path]:
        root = root.expanduser().resolve()
        found: list[Path] = []
        base_depth = len(root.parts)
        for current, dirs, files in os.walk(root):
            if self.cancelled or len(found) >= max_archives:
                break
            path = Path(current)
            if len(path.parts) - base_depth >= max_depth:
                dirs[:] = []
            for name in sorted(files):
                if name.casefold().endswith(".xp3"):
                    found.append(path / name)
                    if len(found) >= max_archives:
                        break
        return found

    def list(self, archive: Path) -> list[tuple[str, int, bool]]:
        return Xp3Archive(archive).list_entries()

    def extract(
        self,
        archive: Path,
        output: Path,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> tuple[int, int]:
        on_progress = on_progress or (lambda *_: None)
        xp3 = Xp3Archive(archive)
        if output.exists() and any(output.iterdir()):
            raise ArchiveConflict(f"Extraction target is not empty: {output}")
        output.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        success = failed = 0
        total = len(xp3.entries)
        for index, entry in enumerate(xp3.entries, start=1):
            if self.cancelled:
                raise ArchiveError("Archive operation cancelled.")
            on_progress(entry.name, index - 1, total)
            try:
                target = _safe_join(output, entry.name)
            except ArchiveError:
                failed += 1
                continue
            target = _dedupe_target(target, seen)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                if entry.size <= KSD_PROBE_MAX:
                    payload = xp3.read(entry)
                    target.write_bytes(payload)
                else:
                    with target.open("wb") as stream:
                        for block in xp3.iter_entry(entry):
                            stream.write(block)
                success += 1
            except (OSError, ArchiveError):
                target.unlink(missing_ok=True)
                failed += 1
        on_progress("", total, total)
        return success, failed

    def extract_all(
        self,
        root: Path,
        output: Path | None = None,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> list[tuple[Path, Path, int, int]]:
        self.cancelled = False
        archives = self.scan(root)
        results = []
        for archive in archives:
            if self.cancelled:
                break
            target = (output or archive.parent) / archive.stem
            success, failed = self.extract(archive, target, on_progress)
            results.append((archive, target, success, failed))
        return results

    def pack(
        self,
        source: Path,
        output: Path,
        level: int = 6,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> int:
        self.cancelled = False
        on_progress = on_progress or (lambda *_: None)
        files = collect_files(source)
        if not files:
            raise ArchiveError("No files to archive.")
        if output.exists():
            raise ArchiveConflict(f"Output archive already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkstemp(prefix=".xp3-", suffix=".tmp", dir=output.parent)[1])
        level = max(0, min(level, 9))
        try:
            with temp.open("wb") as stream:
                stream.write(XP3_MAGIC)
                stream.write(b"\x01")
                stream.write(struct.pack("<Q", CURRENT_VERSION))
                stream.write(struct.pack("<I", 0))
                stream.write(bytes([VERSION_IDENTIFIER]))
                stream.write(struct.pack("<Q", 0))
                index_offset_position = stream.tell()
                stream.write(struct.pack("<Q", 0))
                entries: list[tuple[str, int, int, int, int, bool]] = []
                for index, (path, name) in enumerate(files, start=1):
                    if self.cancelled:
                        raise ArchiveError("Archive operation cancelled.")
                    if "\\" in name or ":" in name:
                        raise ArchiveError(f"Unsafe file name: {name}")
                    on_progress(name, index - 1, len(files))
                    payload = path.read_bytes()
                    if len(payload) > MAX_FILE_BYTES:
                        raise ArchiveError(f"File is too large: {name}")
                    start = stream.tell()
                    stored = zlib.compress(payload, level) if level else payload
                    stream.write(stored)
                    entries.append(
                        (
                            name,
                            len(payload),
                            len(stored),
                            zlib.adler32(payload) & 0xFFFFFFFF,
                            start,
                            level > 0,
                        )
                    )
                index_start = stream.tell()
                index = _build_index(entries)
                stream.write(b"\x00")
                stream.write(struct.pack("<Q", len(index)))
                stream.write(index)
                stream.seek(index_offset_position)
                stream.write(struct.pack("<Q", index_start))
            temp.replace(output)
        finally:
            temp.unlink(missing_ok=True)
        on_progress("", len(files), len(files))
        return len(files)


def _read_chunk(data: bytes, offset: int) -> tuple[int, bytes, int]:
    if offset + 12 > len(data):
        raise ArchiveError("Truncated XP3 index chunk.")
    key, size = struct.unpack_from("<IQ", data, offset)
    start = offset + 12
    end = start + size
    if end > len(data):
        raise ArchiveError("Truncated XP3 index chunk payload.")
    return key, data[start:end], end


def _chunk(key: int, payload: bytes) -> bytes:
    return struct.pack("<IQ", key, len(payload)) + payload


def _build_index(entries: list[tuple[str, int, int, int, int, bool]]) -> bytes:
    result = bytearray()
    for name, size, archive_size, checksum, start, compressed in entries:
        encoded_name = name.encode("utf-16-le")
        info = (
            struct.pack("<IQQH", 0, size, archive_size, len(encoded_name) // 2)
            + encoded_name
        )
        segment = struct.pack("<IQQQ", int(compressed), start, size, archive_size)
        file_payload = (
            _chunk(CHUNK_INFO, info)
            + _chunk(CHUNK_ADLR, struct.pack("<I", checksum))
            + _chunk(CHUNK_SEGM, segment)
        )
        result.extend(_chunk(CHUNK_FILE, file_payload))
    return bytes(result)


def collect_files(source: Path) -> list[tuple[Path, str]]:
    source = source.expanduser().resolve()
    if source.is_file():
        return [(source, source.name)]
    output: list[tuple[Path, str]] = []
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(name for name in dirs if not (Path(root) / name).is_symlink())
        for name in sorted(files):
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            output.append((path, path.relative_to(source).as_posix()))
    return output


def _safe_join(root: Path, archive_name: str) -> Path:
    normalized = archive_name.replace("\\", "/")
    if normalized.startswith("/") or "\x00" in normalized:
        raise ArchiveError("Unsafe archive path.")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or ".." in parts or any(":" in part for part in parts):
        raise ArchiveError("Unsafe archive path.")
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ArchiveError("Unsafe archive path.")
    return target


def _dedupe_target(target: Path, seen: set[str]) -> Path:
    key = str(target).casefold()
    if key not in seen:
        seen.add(key)
        return target
    stem, suffix = target.stem, target.suffix
    for index in range(1, 1_000_000):
        candidate = target.with_name(f"{stem} ({index}){suffix}")
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            return candidate
    raise ArchiveError("Unable to resolve duplicate archive entry.")


def ksd_mode2_decode(data: bytes) -> bytes | None:
    if len(data) < 21 or data[:5] != b"\xFE\xFE\x02\xFF\xFE":
        return None
    inner = data[5:]
    compressed_length, uncompressed_length = struct.unpack_from("<qq", inner, 0)
    if compressed_length < 2 or uncompressed_length < 0 or uncompressed_length > KSD_PROBE_MAX:
        return None
    end = 16 + compressed_length
    if end > len(inner):
        return None
    try:
        output = zlib.decompress(inner[18:end], wbits=-15)
    except zlib.error:
        return None
    output = output[:uncompressed_length]
    if len(output) % 2:
        return None
    try:
        text = output.decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    if any(ord(char) < 0x20 and char not in "\n\r\t" for char in text):
        return None
    return output
