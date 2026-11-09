from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tyranor.settings import Settings


class SettingsTest(unittest.TestCase):
    def test_reload_and_nested_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            settings = Settings(path)
            settings.set("accent", "#123456")
            settings.set("cover_enabled", {"vndb": False})
            reloaded = Settings(path)
            self.assertEqual(reloaded.get("accent"), "#123456")
            self.assertFalse(reloaded.get("cover_enabled")["vndb"])
            self.assertIn("nextmoe", reloaded.get("cover_enabled"))
