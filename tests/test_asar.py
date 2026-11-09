from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tyranor.asar import AsarArchive


class AsarTest(unittest.TestCase):
    def test_nested_file_lookup_and_read(self) -> None:
        tree = {
            "files": {
                "index.html": {"size": 5, "offset": "0"},
                "data": {
                    "files": {
                        "system": {
                            "files": {
                                "Config.tjs": {"size": 7, "offset": "5"},
                            }
                        }
                    }
                },
            }
        }
        payload = b"index" + b"config!"
        encoded = json.dumps(tree, separators=(",", ":")).encode("utf-8")
        header_size = 8 + len(encoded)
        header_size += (-header_size) % 4
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "app.asar"
            with archive_path.open("wb") as stream:
                stream.write(struct.pack("<II", 4, header_size))
                header = struct.pack("<II", len(encoded), len(encoded)) + encoded
                stream.write(header.ljust(header_size, b"\0"))
                stream.write(payload)
            archive = AsarArchive(archive_path)
            self.assertEqual(archive.read(archive.lookup("index.html")), b"index")
            config = archive.lookup("data/system/Config.tjs")
            self.assertIsNotNone(config)
            self.assertEqual(archive.read(config), b"config!")
