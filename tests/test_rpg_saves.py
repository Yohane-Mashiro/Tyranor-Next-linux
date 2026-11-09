from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tyranor.models import EngineType, Game
from tyranor.rpg_saves import convert_to_tyranor, export_to_standard, standard_dir


class RpgSaveTest(unittest.TestCase):
    def test_mv_convert_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "www" / "js").mkdir(parents=True)
            (root / "www" / "index.html").write_text("", encoding="utf-8")
            standard = root / "www" / "save"
            standard.mkdir()
            (standard / "global.rpgsave").write_bytes(b"global")
            (standard / "file1.rpgsave").write_bytes(b"slot")
            game = Game(uri=str(root), title="MV", engine=EngineType.RPG_MV)
            result = convert_to_tyranor(game)
            self.assertEqual(result.imported, 2)
            self.assertTrue((root / "savedata").is_dir())
            self.assertFalse((standard / "file1.rpgsave").exists())
            self.assertTrue((standard / "original" / "file1.rpgsave").exists())
            (root / "savedata" / "global.bin").write_bytes(b"changed")
            exported = export_to_standard(game)
            self.assertGreaterEqual(exported.exported, 1)

    def test_mz_names_are_direct(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "js").mkdir()
            (root / "index.html").write_text("", encoding="utf-8")
            save = root / "save"
            save.mkdir()
            (save / "file1.rmmzsave").write_bytes(b"mz")
            game = Game(uri=str(root), title="MZ", engine=EngineType.RPG_MZ)
            convert_to_tyranor(game)
            self.assertEqual((root / "savedata" / "file1.bin").read_bytes(), b"mz")
            self.assertTrue((save / "original" / "file1.rmmzsave").exists())
