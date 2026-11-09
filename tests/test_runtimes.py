from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tyranor.models import EngineType
from tyranor.runtimes import RuntimeManager
from tyranor.settings import Settings


class RuntimeVisibilityTest(unittest.TestCase):
    def test_only_available_and_supported_engines_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(Path(temp) / "settings.json")
            manager = RuntimeManager(settings)
            engines = {engine for engine, _ in manager.visible_engines()}
            self.assertIn(EngineType.TYRANO, engines)
            self.assertIn(EngineType.RPG_MV, engines)
            self.assertNotIn(EngineType.RUFFLE, engines)
            self.assertNotIn(EngineType.PC, engines)
            self.assertNotIn(EngineType.CMVS, engines)

    def test_configured_renpy_and_kirikiri_become_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(Path(temp) / "settings.json")
            manager = RuntimeManager(settings)
            manager.set_override("renpy", "/usr/bin/true", ["{path}"])
            manager.set_override("krkrsdl3", "/usr/bin/true", ["{path}"])
            manager.refresh()
            engines = {engine for engine, _ in manager.visible_engines()}
            self.assertIn(EngineType.RENPY, engines)
            self.assertIn(EngineType.KIRIKIRI, engines)
