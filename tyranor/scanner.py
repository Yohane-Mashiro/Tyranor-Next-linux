from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .database import Library
from .models import UNKNOWN, Detection, EngineType, GAME_DIR, Game


PFS_PATCH_RE = re.compile(r"^[^.]+\.pfs\.\d{3}$", re.IGNORECASE)
GAMEEXE_DAT_RE = re.compile(r"^gameexe(en|zh|zhtw|de|es|fr|id)?\.dat$", re.IGNORECASE)
GAMEEXE_INI_RE = re.compile(r"^gameexe(en|zh|zhtw|de|es|fr|id)?\.ini$", re.IGNORECASE)
SEEN_AVG32_RE = re.compile(r"^seen\d{3}\.txt$", re.IGNORECASE)
SEEN_REALLIVE_RE = re.compile(r"^seen\d{4}\.txt$", re.IGNORECASE)
YS_DLL_RE = re.compile(r"^ys[a-z0-9]*\.dll$", re.IGNORECASE)

ENGINE_DIRS = {"data", "dat", "tyrano", "scenario", "system", "app", "game", "www", "js"}
LOCAL_COVERS = (
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "cover.webp",
    "cover.bmp",
    "icon.png",
)
FVP_PACKS = {
    "graph.bin",
    "graph_vis.bin",
    "bgm.bin",
    "se.bin",
    "se_env.bin",
    "se_sys.bin",
    "voice.bin",
    "voice2.bin",
    "etc.bin",
}
XS35_SUPPORT_NAMES = {"system39.ain", "system39.ini"}
XS35_SUPPORT_EXTS = (".wai", ".bgi", ".alk")
PSP_EXTS = {".pbp", ".cso", ".iso", ".chd"}
SWITCH_EXTS = {".nsp", ".xci", ".nca", ".nro"}
CS2_TYPICAL = {"scene.int", "image.int", "config.int", "bgm.int", "se.int", "kcs.int"}
ARCHIVE_EXTS = {".xp3", ".pfs", ".dat", ".arc", ".pak"}


@dataclass(slots=True)
class ScanResult:
    games: list[Game] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    visited_directories: int = 0


def recognize_game(directory: Path) -> Detection:
    """Port of Tyranor Next's directory recognition priority chain."""
    if not directory.is_dir():
        return UNKNOWN
    try:
        children = _children(directory)
    except OSError:
        return UNKNOWN
    return recognize_children(directory, children)


def recognize_children(directory: Path, children: list[Path]) -> Detection:
    files: dict[str, Path] = {}
    dirs: dict[str, Path] = {}
    for child in children:
        try:
            if child.is_dir():
                dirs.setdefault(child.name.casefold(), child)
            elif child.is_file():
                files.setdefault(child.name.casefold(), child)
        except OSError:
            continue

    xp3_files: list[str] = []
    has_startup_tjs = "startup.tjs" in files
    has_config_tjs = "config.tjs" in files
    has_index = "index.html" in files or "index.htm" in files
    has_root_index = has_index
    has_child_directory = bool(dirs)
    has_app_asar = "app.asar" in files
    has_tyrano_dir = "tyrano" in dirs
    has_rpg_mv_core = False
    has_rpg_mz_core = False
    has_vn_data = "globaldata.vndata" in files
    has_system_ini = "system.ini" in files
    has_first_iet = False
    has_boot_ini = "boot.ini" in files
    has_root_pfs = "root.pfs" in files
    has_patch_pfs = any(PFS_PATCH_RE.match(name) for name in files)
    has_any_pfs = has_root_pfs or has_patch_pfs or any(name.endswith(".pfs") for name in files)
    has_obb = any(name.endswith(".obb") for name in files)
    has_gameexe_dat = any(GAMEEXE_DAT_RE.match(name) for name in files)
    has_gameexe_ini = any(GAMEEXE_INI_RE.match(name) for name in files)
    has_yscfg = "yscfg.dat" in files
    has_ypf = any(name.endswith(".ypf") for name in files)
    has_ymv = any(name.endswith(".ymv") for name in files)
    ys_dll_count = sum(1 for name in files if YS_DLL_RE.match(name))
    has_startup_xml = False
    has_cs2_exe = "cs2.exe" in files
    int_count = 0
    typical_int_count = 0
    has_cst = False
    has_cstl = False
    has_hg3 = False
    has_fes = False
    has_anm = False
    has_kcs = False
    has_scene_pck = "scene.pck" in files
    has_select_ini = "select.ini" in files
    has_g00 = any(name.endswith(".g00") for name in files)
    has_ons_script = any(
        name in {"0.txt", "00.txt", "nscript.dat", "onscript.nt2", "onscript.nt3"}
        for name in files
    )
    has_ons_archive = any(name.endswith((".nsa", ".sar")) for name in files)
    has_renpy_dir = "renpy" in dirs
    has_game_dir = "game" in dirs
    has_rpa = any(name.endswith(".rpa") for name in files)
    has_rpy = any(name.endswith(".rpy") for name in files)
    has_rpyc = any(name.endswith(".rpyc") for name in files)
    game_script_rpy = False
    game_options_rpy = False
    first_rgssad = None
    first_rgss2a = None
    first_rgss3a = None
    first_swf = None
    swf_count = 0
    has_game_ini = "game.ini" in files
    has_rxdata = False
    has_rvdata = False
    has_rvdata2 = False
    has_mkxp_ruby = False
    has_fvp_script = False
    has_fvp_pack = False
    has_ald = False
    ald_count = 0
    has_xs35_support = False
    has_system39_marker = False
    system40_ini = files.get("system40.ini")
    alice_start_ini = files.get("alicestart.ini")
    has_ain = any(name.endswith(".ain") for name in files if name not in XS35_SUPPORT_NAMES)
    has_uk2_cfg = "uk2.cfg" in files
    has_seen_avg32 = any(SEEN_AVG32_RE.match(name) for name in files)
    has_seen_reallive = any(SEEN_REALLIVE_RE.match(name) for name in files)
    seen_archive = files.get("seen.txt")
    uk2_mes = next((path for name, path in files.items() if name.endswith(".mes")), None)
    ethornell_system = files.get("system.arc")
    has_cmvs_script = False
    has_cmvs_start = False
    cmvs_start_count = 0
    has_cmvs_start_header = False
    has_cmvs_exe = any(name in {"cmvs.exe", "cmvs32.exe", "cmvs64.exe"} for name in files)

    for name, path in list(files.items()):
        if name.endswith(".xp3"):
            xp3_files.append(path.name)
        if name.endswith(".rgssad") and first_rgssad is None:
            first_rgssad = path.name
        if name.endswith(".rgss2a") and first_rgss2a is None:
            first_rgss2a = path.name
        if name.endswith(".rgss3a") and first_rgss3a is None:
            first_rgss3a = path.name
        if name.endswith(".swf"):
            swf_count += 1
            first_swf = first_swf or path.name
        if name.startswith("x64-msvcrt-ruby") and name.endswith(".dll"):
            has_mkxp_ruby = True
        if name.endswith((".hcb", ".bch")):
            has_fvp_script = True
        if name in FVP_PACKS:
            has_fvp_pack = True
        if name.endswith(".ald") and len(name) >= 6:
            has_ald = True
            ald_count += 1
        if name in XS35_SUPPORT_NAMES or name.endswith(XS35_SUPPORT_EXTS):
            has_xs35_support = True
        if name in XS35_SUPPORT_NAMES:
            has_system39_marker = True
        if name.endswith(".int"):
            int_count += 1
            typical_int_count += int(name in CS2_TYPICAL)
        has_cst |= name.endswith(".cst")
        has_cstl |= name.endswith(".cstl")
        has_hg3 |= name.endswith(".hg3")
        has_fes |= name.endswith(".fes")
        has_anm |= name.endswith(".anm")
        has_kcs |= name.endswith(".kcs")

    for name, path in list(dirs.items()):
        if name == "config":
            has_startup_xml |= any(child.name.casefold() == "startup.xml" for child in _children(path))
        if name == "pac":
            has_ypf |= any(child.name.casefold().endswith(".ypf") for child in _children(path))
            has_ymv |= any(child.name.casefold().endswith(".ymv") for child in _children(path))
        if name == "gamedata":
            for child in _children(path):
                child_name = child.name.casefold()
                if child_name.endswith(".ald") and len(child_name) >= 6:
                    has_ald = True
                    ald_count += 1
                if child_name in XS35_SUPPORT_NAMES or child_name.endswith(XS35_SUPPORT_EXTS):
                    has_xs35_support = True
                if child_name in XS35_SUPPORT_NAMES:
                    has_system39_marker = True
        if name == "data":
            for child in _children(path):
                child_name = child.name.casefold()
                has_rxdata |= child_name.endswith(".rxdata")
                has_rvdata |= child_name.endswith(".rvdata")
                has_rvdata2 |= child_name.endswith(".rvdata2")
        if name == "game":
            game_script_rpy |= (path / "script.rpy").is_file()
            game_options_rpy |= (path / "options.rpy").is_file()
        if name in ENGINE_DIRS:
            for child in _children(path):
                child_name = child.name.casefold()
                if child_name in {"index.html", "index.htm"}:
                    has_index = True
                if child_name == "rpg_core.js":
                    has_rpg_mv_core = True
                if child_name == "rmmz_core.js":
                    has_rpg_mz_core = True
                if child_name.endswith(".ain") and child_name not in XS35_SUPPORT_NAMES:
                    has_ain = True
            js = path / "js"
            if js.is_dir():
                has_rpg_mv_core |= (js / "rpg_core.js").is_file()
                has_rpg_mz_core |= (js / "rmmz_core.js").is_file()
        if name == "www":
            js = path / "js"
            has_index |= (path / "index.html").is_file() or (path / "index.htm").is_file()
            has_rpg_mv_core |= (js / "rpg_core.js").is_file()
            has_rpg_mz_core |= (js / "rmmz_core.js").is_file()
            has_app_asar |= (path / "app.asar").is_file()
        if name == "system":
            has_first_iet |= (path / "first.iet").is_file()
        if name == "data" and (path / "pack").is_dir():
            pack = path / "pack"
            for child in _children(pack):
                if child.name == "script.cpz":
                    has_cmvs_script = True
                if child.name in {"start.ps3", "start.ps2"}:
                    has_cmvs_start = True
                    cmvs_start_count += 1
                    head = _read_head(child, 4)
                    has_cmvs_start_header |= head == b"PS2A"

    for path in files.values():
        if not path.is_file():
            continue
        if path.name.casefold() == "index.html":
            has_index = True
        if path.name.casefold() == "app.asar":
            has_app_asar = True

    if has_gameexe_dat and has_scene_pck:
        return Detection(EngineType.SIGLUS, 96, GAME_DIR)
    if has_fvp_script and has_fvp_pack:
        return Detection(EngineType.FVP, 96, GAME_DIR)
    if has_fvp_script:
        return Detection(EngineType.FVP, 88, GAME_DIR)
    if has_uk2_cfg:
        return Detection(EngineType.UK2, 96, GAME_DIR)
    if uk2_mes is not None and _read_head(uk2_mes, 24).startswith(b"<< UK2 TEXT Ver1.00 >>"):
        return Detection(EngineType.UK2, 90, GAME_DIR)
    if ethornell_system is not None and _looks_like_ethornell(ethornell_system):
        return Detection(EngineType.ETHORNELL, 96, GAME_DIR)
    seen_kind = _classify_seen(_read_head(seen_archive, 0x200) if seen_archive else None)
    if has_gameexe_ini and seen_kind is not None:
        return Detection(seen_kind, 96, GAME_DIR)
    if has_gameexe_ini and has_seen_reallive:
        return Detection(EngineType.REALLIVE, 92, GAME_DIR)
    if has_gameexe_ini and has_seen_avg32:
        return Detection(EngineType.AVG32, 92, GAME_DIR)
    if seen_kind is not None:
        return Detection(seen_kind, 80, GAME_DIR)
    if uk2_mes is not None:
        return Detection(EngineType.UK2, 82, GAME_DIR)
    if has_gameexe_ini and has_scene_pck:
        return Detection(EngineType.SIGLUS, 95, GAME_DIR)
    if has_gameexe_dat or has_gameexe_ini:
        return Detection(EngineType.SIGLUS, 85, GAME_DIR)
    if has_scene_pck and has_select_ini and has_g00:
        return Detection(EngineType.SIGLUS, 80, GAME_DIR)
    if has_yscfg and has_ypf:
        return Detection(EngineType.YURIS, 96, GAME_DIR)
    if has_ypf:
        return Detection(EngineType.YURIS, 90, GAME_DIR)
    if has_yscfg:
        return Detection(EngineType.YURIS, 85, GAME_DIR)
    if ys_dll_count >= 2:
        return Detection(EngineType.YURIS, 80, GAME_DIR)
    if has_ymv:
        return Detection(EngineType.YURIS, 75, GAME_DIR)

    cs2_score = (
        (20 if has_startup_xml else 0)
        + min(int_count, 8) * 4
        + min(typical_int_count, 4) * 8
        + (12 if has_cst else 0)
        + (12 if has_hg3 else 0)
        + (6 if has_cstl else 0)
        + (5 if has_fes else 0)
        + (5 if has_anm else 0)
        + (5 if has_kcs else 0)
        + (10 if has_cs2_exe else 0)
    )
    if cs2_score >= 50:
        return Detection(EngineType.CATSYSTEM2, cs2_score, GAME_DIR)

    system4_ini = system40_ini or alice_start_ini
    is_system4 = system4_ini is not None and not has_system39_marker
    if not is_system4 and has_ald and has_xs35_support:
        return Detection(EngineType.XSYS35, 96, GAME_DIR)
    if not is_system4 and has_ald and ald_count >= 2:
        return Detection(EngineType.XSYS35, 90, GAME_DIR)
    if not is_system4 and has_ald:
        return Detection(EngineType.XSYS35, 80, GAME_DIR)
    if (
        (has_system_ini and has_first_iet)
        or has_root_pfs
        or has_patch_pfs
        or has_any_pfs
        or (has_boot_ini and has_obb)
    ):
        confidence = 95 if (has_system_ini and has_first_iet) or has_root_pfs or (has_boot_ini and has_obb) else 90
        return Detection(EngineType.ARTEMIS, confidence, GAME_DIR)
    if has_index and has_tyrano_dir:
        return Detection(EngineType.TYRANO, 95, GAME_DIR)
    if has_index and has_rpg_mv_core:
        return Detection(EngineType.RPG_MV, 95, GAME_DIR)
    if has_index and has_rpg_mz_core:
        return Detection(EngineType.RPG_MZ, 95, GAME_DIR)
    if has_index and has_vn_data:
        return Detection(EngineType.VN, 90, GAME_DIR)
    if has_app_asar:
        return Detection(EngineType.TYRANO, 80, GAME_DIR)
    if first_rgss3a:
        return Detection(EngineType.RPGMAKER, 96, first_rgss3a, "internal.rpgmvxace")
    if first_rgss2a:
        return Detection(EngineType.RPGMAKER, 96, first_rgss2a, "internal.rpgmvx")
    if has_game_ini and has_rvdata2:
        return Detection(EngineType.RPGMAKER, 92, GAME_DIR, "internal.rpgmvxace")
    if has_game_ini and has_rvdata:
        return Detection(EngineType.RPGMAKER, 92, GAME_DIR, "internal.rpgmvx")
    if has_mkxp_ruby:
        return Detection(EngineType.RPGMAKER, 92, GAME_DIR, "internal.mkxp-z")
    if first_rgssad:
        return Detection(EngineType.RPGMAKER, 96, first_rgssad, "internal.rpgmxp")
    if has_game_ini and has_rxdata:
        return Detection(EngineType.RPGMAKER, 92, GAME_DIR, "internal.rpgmxp")
    if has_rpa or game_script_rpy or game_options_rpy or (has_renpy_dir and (has_rpy or has_rpyc)) or (has_game_dir and has_rpy):
        confidence = 96 if has_rpa else 94 if game_script_rpy or game_options_rpy else 90 if has_renpy_dir else 85
        return Detection(EngineType.RENPY, confidence, GAME_DIR)
    has_console_rom = any(path.suffix.casefold() in PSP_EXTS | SWITCH_EXTS for path in files.values())
    if (
        has_root_index
        and not has_child_directory
        and swf_count == 1
        and first_swf
        and not has_tyrano_dir
        and not has_rpg_mv_core
        and not has_rpg_mz_core
        and not has_vn_data
        and not has_app_asar
        and not xp3_files
        and not has_startup_tjs
        and not has_config_tjs
        and not has_ons_script
        and not has_ons_archive
        and not is_system4
        and not has_console_rom
    ):
        return Detection(EngineType.RUFFLE, 88, first_swf, "internal.flash")
    if has_index:
        return Detection(EngineType.WEB_OTHER, 70, GAME_DIR)
    if xp3_files or has_startup_tjs or has_config_tjs:
        krkr_target = _pick_krkr_target(files, xp3_files)
        return Detection(EngineType.KIRIKIRI, 95 if xp3_files else 80, krkr_target)
    if has_ons_script or has_ons_archive:
        return Detection(EngineType.ONS, 90 if has_ons_script else 70, GAME_DIR)
    if is_system4:
        title = _system4_title(system4_ini)
        return Detection(EngineType.XSYS4, 97 if has_ain else 90, GAME_DIR, title_hint=title)
    if has_cmvs_script and has_cmvs_start and cmvs_start_count == 1:
        return Detection(EngineType.CMVS, 96 if has_cmvs_start_header else 92, GAME_DIR)
    if has_cmvs_exe:
        return Detection(EngineType.CMVS, 82, GAME_DIR)
    return UNKNOWN


class Scanner:
    def __init__(
        self,
        library: Library,
        on_progress: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ):
        self.library = library
        self.on_progress = on_progress or (lambda _: None)
        self.should_cancel = should_cancel or (lambda: False)
        self._seen: set[str] = set()
        self._visited = 0
        self._errors: list[str] = []

    def scan(self, roots: Iterable[str], depth: int = 3) -> ScanResult:
        started = time.monotonic()
        games: list[Game] = []
        for root_value in roots:
            root = Path(root_value).expanduser()
            if self.should_cancel():
                break
            if not root.is_dir():
                self._errors.append(f"Scan root is unavailable: {root}")
                continue
            self._walk(root, 0, max(1, min(depth, 8)), games)
        elapsed = time.monotonic() - started
        self.on_progress(f"Scanned {self._visited} directories, found {len(games)} games")
        return ScanResult(games=games, errors=self._errors, elapsed_seconds=elapsed, visited_directories=self._visited)

    def _walk(self, directory: Path, level: int, max_depth: int, out: list[Game]) -> None:
        if level > max_depth or self.should_cancel():
            return
        self._visited += 1
        if self._visited % 25 == 0:
            self.on_progress(f"Scanning {directory.name}…")
        try:
            children = _children(directory)
        except OSError as exc:
            self._errors.append(f"{directory}: {exc}")
            return
        for child in children:
            if child.is_file() and child.suffix.casefold() in PSP_EXTS | SWITCH_EXTS:
                self._add_rom(child, out)
            elif child.is_file() and child.suffix.casefold() == ".swf":
                self._add_swf(child, out)

        detection = recognize_children(directory, children)
        if detection.engine is not EngineType.UNKNOWN:
            game = self._game_from_detection(directory, detection)
            key = str(directory.resolve())
            if key not in self._seen:
                self._seen.add(key)
                out.append(game)
            return

        for child in children:
            if child.is_dir() and not child.is_symlink():
                self._walk(child, level + 1, max_depth, out)

    def _add_rom(self, path: Path, out: list[Game]) -> None:
        engine = EngineType.PSP if path.suffix.casefold() in PSP_EXTS else EngineType.NINTENDO_SWITCH
        key = str(path.resolve())
        if key in self._seen:
            return
        self._seen.add(key)
        cover = _file_cover(path)
        out.append(
            Game(
                uri=key,
                title=path.stem,
                engine=engine,
                launch_target=path.name,
                cover_uri=str(cover) if cover else None,
                cover_source="local" if cover else None,
            )
        )

    def _add_swf(self, path: Path, out: list[Game]) -> None:
        # A wrapper directory is handled by recognize_children. A loose SWF is one record.
        parent = path.parent
        try:
            siblings = _children(parent)
        except OSError:
            siblings = []
        wrapper = (
            (parent / "index.html").is_file() or (parent / "index.htm").is_file()
        ) and sum(1 for item in siblings if item.suffix.casefold() == ".swf") == 1
        if wrapper:
            return
        key = str(path.resolve())
        if key in self._seen:
            return
        self._seen.add(key)
        cover = _file_cover(path)
        out.append(
            Game(
                uri=key,
                title=parent.name if parent.name not in {"games", "game"} else path.stem,
                engine=EngineType.RUFFLE,
                launch_target=path.name,
                external_alias="internal.flash",
                cover_uri=str(cover) if cover else None,
                cover_source="local" if cover else None,
            )
        )

    def _game_from_detection(self, directory: Path, detection: Detection) -> Game:
        cover = _local_cover(directory)
        title = detection.title_hint or _clean_title(directory.name)
        launch_file = None
        if detection.engine in {EngineType.YURIS, EngineType.CATSYSTEM2}:
            launch_file = _windows_launch_file(directory)
        return Game(
            uri=str(directory.resolve()),
            title=title,
            engine=detection.engine,
            launch_target=detection.launch_target,
            cover_uri=str(cover) if cover else None,
            cover_source="local" if cover else None,
            detected_title=detection.title_hint,
            external_alias=detection.external_alias,
            launch_file=launch_file,
        )


def merge_scan_results(existing: list[Game], scanned: list[Game]) -> list[Game]:
    by_uri = {game.uri: game for game in scanned}
    for previous in existing:
        current = by_uri.get(previous.uri)
        if current is None:
            continue
        current.cover_uri = previous.cover_uri or current.cover_uri
        current.cover_source = previous.cover_source or current.cover_source
        current.vndb_id = previous.vndb_id
        current.metadata_title = previous.metadata_title
        current.launch_file = previous.launch_file
        current.runtime_id = previous.runtime_id
        current.custom_args = previous.custom_args
        current.save_dir = previous.save_dir
        current.open_time = previous.open_time
        current.play_time = previous.play_time
        current.quick_launch = previous.quick_launch
        current.overrides = previous.overrides
    return list(by_uri.values())


def _children(directory: Path) -> list[Path]:
    with os.scandir(directory) as entries:
        return [Path(entry.path) for entry in entries]


def _read_head(path: Path, count: int) -> bytes:
    try:
        with path.open("rb") as stream:
            return stream.read(count) if count else stream.read()
    except OSError:
        return b""


def _looks_like_ethornell(path: Path) -> bool:
    head = _read_head(path, 512)
    lower = head.lower()
    return b"bgi" in lower or b"ethornell" in lower or b"buriko" in lower or len(head) >= 16


def _classify_seen(head: bytes | None) -> EngineType | None:
    if not head or len(head) < 8:
        return None
    if head.startswith(b"PACL"):
        return EngineType.AVG32
    valid = 0
    for index in range(4):
        at = index * 8
        if at + 8 > len(head):
            break
        offset = int.from_bytes(head[at : at + 4], "little")
        length = int.from_bytes(head[at + 4 : at + 8], "little")
        if offset == 0 or length < 4:
            continue
        if offset + 4 <= len(head):
            header = int.from_bytes(head[offset : offset + 4], "little")
            if header not in {0x1D0, 0x1CC}:
                return None
        valid += 1
        if valid >= 4:
            break
    return EngineType.REALLIVE if valid else None


def _system4_title(path: Path | None) -> str | None:
    if path is None:
        return None
    for encoding in ("utf-8-sig", "cp932", "gb18030", "latin-1"):
        try:
            text = path.read_text(encoding=encoding, errors="strict")
        except (OSError, UnicodeError):
            continue
        match = re.search(r"(?im)^\s*GameName\s*=\s*(.+?)\s*$", text)
        if match:
            value = match.group(1).strip().strip('"')
            if value:
                return value
    return None


def _local_cover(directory: Path) -> Path | None:
    for name in LOCAL_COVERS:
        for child in _children(directory):
            if child.is_file() and child.name.casefold() == name:
                return child
    return None


def _file_cover(path: Path) -> Path | None:
    for suffix in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    try:
        return _local_cover(path.parent)
    except OSError:
        return None


def _clean_title(value: str) -> str:
    title = value.strip()
    title = re.sub(r"[\[\(【（][^\]\)】）]{1,20}[\]\)】）]\s*$", "", title).strip()
    return title or value


def _windows_launch_file(directory: Path) -> str | None:
    ignored = ("unins", "uninstall", "setup", "install", "update", "config", "readme")
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.casefold() == ".exe"
        and not any(token in path.name.casefold() for token in ignored)
    ]
    if not candidates:
        return None
    preferred = ("game.exe", "cs2.exe", "ys.exe", "start.exe")
    candidates.sort(
        key=lambda path: (
            0 if path.name.casefold() in preferred else 1,
            len(path.name),
            path.name.casefold(),
        )
    )
    return candidates[0].name


def _pick_krkr_target(files: dict[str, Path], xp3_files: list[str]) -> str:
    preferred = ("data.xp3", "main.xp3", "scn.xp3", "patch.xp3", "scenario.xp3")
    for name in preferred:
        path = files.get(name)
        if path is not None:
            return path.name
    if xp3_files:
        return xp3_files[0]
    for name in ("startup.tjs", "config.tjs", "0.ebk"):
        path = files.get(name)
        if path is not None:
            return path.name
    return GAME_DIR
