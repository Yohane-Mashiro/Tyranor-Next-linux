from __future__ import annotations

import unittest
from pathlib import Path


class PackagingAssetsTest(unittest.TestCase):
    def test_desktop_entry_exists_for_rpm_build(self) -> None:
        desktop_file = (
            Path(__file__).resolve().parents[1]
            / "packaging"
            / "io.github.tyranornext.linux.desktop"
        )
        self.assertTrue(desktop_file.is_file())
        text = desktop_file.read_text(encoding="utf-8")
        self.assertIn("Exec=tyranor-next", text)
        self.assertIn("Icon=io.github.tyranornext.linux", text)
