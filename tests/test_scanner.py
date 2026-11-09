from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tyranor.models import EngineType, GAME_DIR
from tyranor.scanner import Scanner, recognize_game


class ScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_kirikiri_and_web_engines(self) -> None:
        kirikiri = self.root / "Kiri"
        kirikiri.mkdir()
        (kirikiri / "data.xp3").write_bytes(b"xp3")
        (kirikiri / "cover.jpg").write_bytes(b"not a real jpeg")
        renpy = self.root / "RenPy"
        (renpy / "game").mkdir(parents=True)
        (renpy / "game" / "script.rpy").write_text("label start:", encoding="utf-8")
        mv = self.root / "MV"
        (mv / "js").mkdir(parents=True)
        (mv / "index.html").write_text("", encoding="utf-8")
        (mv / "js" / "rpg_core.js").write_text("", encoding="utf-8")

        kirikiri_detection = recognize_game(kirikiri)
        self.assertEqual(kirikiri_detection.engine, EngineType.KIRIKIRI)
        self.assertEqual(kirikiri_detection.launch_target, "data.xp3")
        self.assertEqual(recognize_game(renpy).engine, EngineType.RENPY)
        self.assertEqual(recognize_game(mv).engine, EngineType.RPG_MV)

    def test_scan_stops_at_recognized_game_and_handles_roms(self) -> None:
        game = self.root / "Nested" / "Game"
        game.mkdir(parents=True)
        (game / "nscript.dat").write_bytes(b"*define")
        (game / "child").mkdir()
        (game / "child" / "index.html").write_text("", encoding="utf-8")
        (self.root / "rom.iso").write_bytes(b"iso")

        class DummyLibrary:
            pass

        result = Scanner(DummyLibrary()).scan([str(self.root)], depth=4)
        engines = {Path(item.uri).name: item.engine for item in result.games}
        self.assertEqual(engines["Game"], EngineType.ONS)
        self.assertEqual(engines["rom.iso"], EngineType.PSP)
        self.assertEqual(len(result.games), 2)

    def test_unknown_directory_is_not_added(self) -> None:
        unknown = self.root / "random"
        unknown.mkdir()
        (unknown / "readme.txt").write_text("hello", encoding="utf-8")

        class DummyLibrary:
            pass

        result = Scanner(DummyLibrary()).scan([str(self.root)])
        self.assertEqual(result.games, [])

    def test_www_wrapped_rpg_maker_mv_is_detected(self) -> None:
        game = self.root / "Wrapped MV"
        (game / "www" / "js").mkdir(parents=True)
        (game / "www" / "index.html").write_text("", encoding="utf-8")
        (game / "www" / "js" / "rpg_core.js").write_text("", encoding="utf-8")
        self.assertEqual(recognize_game(game).engine, EngineType.RPG_MV)

    def test_system4_title_parser(self) -> None:
        game = self.root / "System4"
        game.mkdir()
        (game / "System40.ini").write_text("GameName=Rance Quest\n", encoding="utf-8")
        (game / "x.ain").write_bytes(b"ain")
        detection = recognize_game(game)
        self.assertEqual(detection.engine, EngineType.XSYS4)
        self.assertEqual(detection.title_hint, "Rance Quest")

    def test_scan_merges_persistent_fields(self) -> None:
        from tyranor.scanner import merge_scan_results
        from tyranor.models import Game

        uri = str(self.root)
        previous = Game(uri=uri, title="Old", engine=EngineType.KIRIKIRI, open_time=123)
        scanned = Game(uri=uri, title="New", engine=EngineType.KIRIKIRI)
        merged = merge_scan_results([previous], [scanned])[0]
        self.assertEqual(merged.title, "New")
        self.assertEqual(merged.open_time, 123)

    def test_supported_engine_feature_table(self) -> None:
        cases = {
            "Kirikiri": EngineType.KIRIKIRI,
            "ONS": EngineType.ONS,
            "Artemis": EngineType.ARTEMIS,
            "Siglus": EngineType.SIGLUS,
            "RealLive": EngineType.REALLIVE,
            "AVG32": EngineType.AVG32,
            "UK2": EngineType.UK2,
            "FVP": EngineType.FVP,
            "Ethornell": EngineType.ETHORNELL,
            "System35": EngineType.XSYS35,
            "System4": EngineType.XSYS4,
            "CMVS": EngineType.CMVS,
            "Tyrano": EngineType.TYRANO,
            "RPGMZ": EngineType.RPG_MZ,
            "RPGXP": EngineType.RPGMAKER,
            "Ruffle": EngineType.RUFFLE,
            "YURIS": EngineType.YURIS,
            "CatSystem2": EngineType.CATSYSTEM2,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                game = self.root / name
                game.mkdir()
                if name == "Kirikiri":
                    (game / "data.xp3").write_bytes(b"xp3")
                elif name == "ONS":
                    (game / "nscript.dat").write_bytes(b"*define")
                elif name == "Artemis":
                    (game / "system.ini").write_bytes(b"")
                    (game / "system").mkdir()
                    (game / "system" / "first.iet").write_bytes(b"")
                elif name == "Siglus":
                    (game / "Gameexe.dat").write_bytes(b"")
                    (game / "Scene.pck").write_bytes(b"")
                elif name == "RealLive":
                    (game / "Gameexe.ini").write_bytes(b"")
                    head = bytearray(64)
                    head[0:8] = (16).to_bytes(4, "little") + (48).to_bytes(4, "little")
                    head[16:20] = (0x1D0).to_bytes(4, "little")
                    (game / "SEEN.TXT").write_bytes(head)
                elif name == "AVG32":
                    (game / "Gameexe.ini").write_bytes(b"")
                    (game / "SEEN.TXT").write_bytes(b"PACL" + b"\0" * 60)
                elif name == "UK2":
                    (game / "UK2.CFG").write_bytes(b"")
                elif name == "FVP":
                    (game / "start.hcb").write_bytes(b"")
                    (game / "graph.bin").write_bytes(b"")
                elif name == "Ethornell":
                    (game / "system.arc").write_bytes(b"BGI-archive-bootstrap")
                elif name == "System35":
                    (game / "SA.ALD").write_bytes(b"")
                    (game / "System39.ain").write_bytes(b"")
                elif name == "System4":
                    (game / "System40.ini").write_text("GameName=Test", encoding="utf-8")
                    (game / "x.ain").write_bytes(b"")
                elif name == "CMVS":
                    (game / "data" / "pack").mkdir(parents=True)
                    (game / "data" / "pack" / "script.cpz").write_bytes(b"")
                    (game / "data" / "pack" / "start.ps3").write_bytes(b"PS2A")
                elif name == "Tyrano":
                    (game / "index.html").write_text("", encoding="utf-8")
                    (game / "tyrano").mkdir()
                elif name == "RPGMZ":
                    (game / "index.html").write_text("", encoding="utf-8")
                    (game / "js").mkdir()
                    (game / "js" / "rmmz_core.js").write_text("", encoding="utf-8")
                elif name == "RPGXP":
                    (game / "Game.ini").write_text("", encoding="utf-8")
                    (game / "Data").mkdir()
                    (game / "Data" / "Map001.rxdata").write_bytes(b"")
                elif name == "Ruffle":
                    (game / "index.html").write_text("", encoding="utf-8")
                    (game / "movie.swf").write_bytes(b"FWS")
                elif name == "YURIS":
                    (game / "yscfg.dat").write_bytes(b"")
                    (game / "game.ypf").write_bytes(b"")
                elif name == "CatSystem2":
                    (game / "config").mkdir()
                    (game / "config" / "startup.xml").write_text("", encoding="utf-8")
                    for item in ("scene.int", "image.int", "config.int", "bgm.int"):
                        (game / item).write_bytes(b"")
                self.assertEqual(recognize_game(game).engine, expected)
