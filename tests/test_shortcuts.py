from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tyranor.models import EngineType, Game
from tyranor.shortcuts import create_shortcut


class ShortcutTest(unittest.TestCase):
    def test_desktop_file_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"XDG_DATA_HOME": temp}):
                game = Game(uri="/games/Example", title="Example", engine=EngineType.RENPY)
                path = create_shortcut(game, "/usr/bin/true")
                text = path.read_text(encoding="utf-8")
                self.assertIn("Name=Example", text)
                self.assertIn("--launch-uri /games/Example", text)
                self.assertTrue(os.access(path, os.X_OK))
