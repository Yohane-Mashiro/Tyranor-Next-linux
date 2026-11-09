from __future__ import annotations

import tempfile
import unittest
import struct
import zlib
from pathlib import Path

from tyranor.archive import ArchiveConflict, ArchiveTool, Xp3Archive


class ArchiveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_pack_list_extract_round_trip(self) -> None:
        source = self.root / "source"
        (source / "scenario").mkdir(parents=True)
        (source / "scenario" / "start.ks").write_text("Hello 世界", encoding="utf-8")
        (source / "image.bin").write_bytes(bytes(range(256)) * 10)
        archive = self.root / "data.xp3"
        tool = ArchiveTool()
        count = tool.pack(source, archive, 6)
        self.assertEqual(count, 2)
        entries = Xp3Archive(archive).list_entries()
        self.assertIn(("scenario/start.ks", len("Hello 世界".encode("utf-8")), False), entries)
        output = self.root / "out"
        success, failed = tool.extract(archive, output)
        self.assertEqual((success, failed), (2, 0))
        self.assertEqual(
            (output / "scenario" / "start.ks").read_text(encoding="utf-8"),
            "Hello 世界",
        )
        self.assertEqual((output / "image.bin").read_bytes(), bytes(range(256)) * 10)

    def test_existing_output_conflict(self) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / "a.txt").write_text("a", encoding="utf-8")
        archive = self.root / "a.xp3"
        ArchiveTool().pack(source, archive)
        with self.assertRaises(ArchiveConflict):
            ArchiveTool().pack(source, archive)

    def test_duplicate_archive_paths_are_not_overwritten(self) -> None:
        target = self.root / "out"

        class FakeEntry:
            name = "x.txt"
            size = 1

        target.mkdir()
        first = target / "x.txt"
        first.write_text("first", encoding="utf-8")
        # Exercise helper semantics used by extraction for duplicate/case collisions.
        from tyranor.archive import _dedupe_target

        seen = {str(target / "X.TXT").casefold()}
        renamed = _dedupe_target(target / "X.TXT", seen)
        self.assertNotEqual(renamed.name.casefold(), "x.txt")

    def test_ksd_mode2_text_is_unwrapped_on_extract(self) -> None:
        text = "こんにちは".encode("utf-16-le")
        compressed = zlib.compress(text, 6)
        wrapped = (
            b"\xFE\xFE\x02\xFF\xFE"
            + struct.pack("<qq", len(compressed), len(text))
            + compressed
        )
        source = self.root / "source"
        source.mkdir()
        (source / "script.ks").write_bytes(wrapped)
        archive = self.root / "ksd.xp3"
        tool = ArchiveTool()
        tool.pack(source, archive, 0)
        output = self.root / "out"
        tool.extract(archive, output)
        self.assertEqual((output / "script.ks").read_bytes(), text)
