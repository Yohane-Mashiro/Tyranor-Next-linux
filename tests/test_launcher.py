from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tyranor.database import Library
from tyranor.launcher import LaunchStatus, Launcher
from tyranor.models import EngineType, Game
from tyranor.runtimes import RuntimeManager
from tyranor.saves import game_data_dir
from tyranor.settings import Settings


class LauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = Library(self.root / "library.db")
        self.settings = Settings(self.root / "settings.json")
        self.env_patch = mock.patch.dict(
            os.environ,
            {"XDG_DATA_HOME": str(self.root / "data")},
        )
        self.dirs_patch = mock.patch("tyranor.runtimes.COMMON_DIRS", ())
        self.which_patch = mock.patch("tyranor.runtimes.shutil.which", return_value=None)
        self.env_patch.start()
        self.dirs_patch.start()
        self.which_patch.start()
        self.runtimes = RuntimeManager(self.settings)

    def tearDown(self) -> None:
        self.library.close()
        self.which_patch.stop()
        self.dirs_patch.stop()
        self.env_patch.stop()
        self.temp.cleanup()

    def test_bundled_renpy_launcher_is_preferred(self) -> None:
        game_dir = self.root / "Game"
        game_dir.mkdir()
        launcher = game_dir / "Game.sh"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o755)
        game = Game(uri=str(game_dir), title="Game", engine=EngineType.RENPY)
        result = Launcher(self.library, self.runtimes).launch(game, preview=True)
        self.assertEqual(result.status, LaunchStatus.STARTED)
        self.assertEqual(
            result.command,
            [str(launcher), "--savedir", str(game_data_dir(game))],
        )

    def test_missing_runtime_is_reported(self) -> None:
        game_dir = self.root / "Game"
        game_dir.mkdir()
        (game_dir / "data.xp3").write_bytes(b"xp3")
        game = Game(uri=str(game_dir), title="Game", engine=EngineType.KIRIKIRI)
        result = Launcher(self.library, self.runtimes).launch(game, preview=True)
        self.assertEqual(result.status, LaunchStatus.RUNTIME_MISSING)

    def test_web_runtime_builds_local_host_command(self) -> None:
        game_dir = self.root / "Web"
        game_dir.mkdir()
        (game_dir / "index.html").write_text("", encoding="utf-8")
        game = Game(uri=str(game_dir), title="Web", engine=EngineType.WEB_OTHER)
        result = Launcher(self.library, self.runtimes).launch(game, preview=True)
        self.assertEqual(result.status, LaunchStatus.STARTED)
        self.assertIn("tyranor.web_host", result.command or [])
        self.assertIn("--savedata-dir", result.command or [])
        self.assertIn(str(game_data_dir(game)), result.command or [])

    def test_launch_prefix_is_prepended_without_shell_reparsing(self) -> None:
        game_dir = self.root / "Web"
        game_dir.mkdir()
        (game_dir / "index.html").write_text("", encoding="utf-8")
        self.settings.set("launch_prefix", "/usr/bin/env TYRANOR_TEST=1")
        game = Game(uri=str(game_dir), title="Web", engine=EngineType.WEB_OTHER)
        result = Launcher(self.library, self.runtimes).launch(game, preview=True)
        self.assertEqual(result.status, LaunchStatus.STARTED)
        self.assertEqual((result.command or [])[:2], ["/usr/bin/env", "TYRANOR_TEST=1"])

    def test_missing_game_path_is_reported(self) -> None:
        game = Game(uri=str(self.root / "gone"), title="Gone", engine=EngineType.PC)
        result = Launcher(self.library, self.runtimes).launch(game, preview=True)
        self.assertEqual(result.status, LaunchStatus.MISSING_GAME)

    def test_real_process_updates_history_and_play_time(self) -> None:
        game_dir = self.root / "Game"
        game_dir.mkdir()
        launcher_file = game_dir / "Game.sh"
        launcher_file.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher_file.chmod(0o755)
        game = Game(uri=str(game_dir), title="Game", engine=EngineType.RENPY)
        self.library.save_game(game)
        launcher = Launcher(self.library, self.runtimes)
        result = launcher.launch(game)
        self.assertTrue(result.ok)
        assert result.process is not None
        result.process.wait(timeout=5)
        deadline = time.time() + 3
        while time.time() < deadline and launcher.running:
            time.sleep(0.01)
        stored = self.library.get_game(game.uri)
        assert stored is not None
        self.assertGreater(stored.open_time, 0)
        self.assertGreaterEqual(stored.play_time, 0)
        self.assertTrue(self.library.history(game.uri))

    def test_wine_fallback_uses_windows_executable(self) -> None:
        game_dir = self.root / "Game"
        game_dir.mkdir()
        (game_dir / "data.xp3").write_bytes(b"xp3")
        executable = game_dir / "Game.exe"
        executable.write_bytes(b"MZ")
        self.runtimes.set_override("wine", "/usr/bin/true", ["{target}"])
        self.runtimes.refresh()
        game = Game(uri=str(game_dir), title="Game", engine=EngineType.KIRIKIRI)
        result = Launcher(self.library, self.runtimes).launch(game, preview=True)
        self.assertEqual(result.status, LaunchStatus.STARTED)
        self.assertEqual(result.command, ["/usr/bin/true", str(executable)])

    def test_kirikiri_runtime_receives_xp3_entry_file(self) -> None:
        game_dir = self.root / "Game"
        game_dir.mkdir()
        entry = game_dir / "data.xp3"
        entry.write_bytes(b"xp3")
        self.runtimes.set_override("krkrsdl3", "/usr/bin/true", ["{target}"])
        self.runtimes.refresh()
        game = Game(
            uri=str(game_dir),
            title="Game",
            engine=EngineType.KIRIKIRI,
            launch_target="data.xp3",
        )
        result = Launcher(self.library, self.runtimes).launch(game, preview=True)
        self.assertEqual(result.status, LaunchStatus.STARTED)
        self.assertEqual(result.command, ["/usr/bin/true", str(entry)])
