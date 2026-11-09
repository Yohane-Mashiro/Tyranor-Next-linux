from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from tyranor.database import Library
from tyranor.models import EngineType, Game
from tyranor.saves import (
    SaveError,
    SaveManager,
    _extract_zip,
    _write_zip,
    game_data_dir,
    migrate_legacy_saves,
)


class SaveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = Library(self.root / "library.db")
        self.saves = SaveManager(self.library, root=self.root / "managed-saves")

    def tearDown(self) -> None:
        self.library.close()
        self.temp.cleanup()

    def test_export_import_and_version(self) -> None:
        game_dir = self.root / "game"
        (game_dir / "savedata").mkdir(parents=True)
        (game_dir / "savedata" / "global.sav").write_bytes(b"save-1")
        game = Game(uri=str(game_dir), title="Game", engine=EngineType.KIRIKIRI)
        central = self.saves.resolve(game)
        assert central is not None
        archive = self.root / "backup.zip"
        self.saves.export_zip(game, archive)
        self.assertTrue(archive.is_file())
        (central.path / "global.sav").write_bytes(b"save-2")
        self.saves.import_zip(game, archive)
        self.assertEqual((central.path / "global.sav").read_bytes(), b"save-1")

    def test_zip_traversal_is_rejected(self) -> None:
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as value:
            value.writestr("../escape.txt", "bad")
        with self.assertRaises(SaveError):
            _extract_zip(archive, self.root / "out")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_running_game_blocks_save_changes(self) -> None:
        game_dir = self.root / "game"
        (game_dir / "savedata").mkdir(parents=True)
        game = Game(uri=str(game_dir), title="Game", engine=EngineType.KIRIKIRI)
        manager = SaveManager(self.library, is_running=lambda uri: True)
        with self.assertRaises(SaveError) as error:
            manager.export_zip(game, self.root / "blocked.zip")
        self.assertEqual(error.exception.code, "GAME_RUNNING")

    def test_create_version_is_content_idempotent(self) -> None:
        game_dir = self.root / "game"
        (game_dir / "savedata").mkdir(parents=True)
        (game_dir / "savedata" / "slot.dat").write_bytes(b"unchanged")
        game = Game(uri=str(game_dir), title="Game", engine=EngineType.KIRIKIRI)
        first = self.saves.create_version(game)
        second = self.saves.create_version(game)
        self.assertEqual(first.version_id, second.version_id)
        self.assertEqual(len(self.saves.versions(game)), 1)

    def test_legacy_saves_are_migrated_without_overwriting(self) -> None:
        game_dir = self.root / "game"
        legacy = game_dir / "savedata"
        legacy.mkdir(parents=True)
        (legacy / "one.sav").write_bytes(b"legacy-one")
        (legacy / "two.sav").write_bytes(b"legacy-two")
        game = Game(
            uri=str(game_dir),
            title="Game",
            engine=EngineType.KIRIKIRI,
        )
        central = game_data_dir(game, self.root / "managed-saves")
        (central / "two.sav").write_bytes(b"current-two")

        migrate_legacy_saves(game, self.root / "managed-saves")

        self.assertEqual((central / "one.sav").read_bytes(), b"legacy-one")
        self.assertEqual((central / "two.sav").read_bytes(), b"current-two")
