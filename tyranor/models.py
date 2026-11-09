from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class EngineType(str, Enum):
    KIRIKIRI = "KIRIKIRI"
    ONS = "ONS"
    TYRANO = "TYRANO"
    RPGMAKER = "RPGMAKER"
    RPG_MV = "RPG_MV"
    RPG_MZ = "RPG_MZ"
    VN = "VN"
    WEB_OTHER = "WEB_OTHER"
    ARTEMIS = "ARTEMIS"
    SIGLUS = "SIGLUS"
    REALLIVE = "REALLIVE"
    AVG32 = "AVG32"
    XSYS35 = "XSYS35"
    XSYS4 = "XSYS4"
    UK2 = "UK2"
    FVP = "FVP"
    ETHORNELL = "ETHORNELL"
    RENPY = "RENPY"
    RUFFLE = "RUFFLE"
    YURIS = "YURIS"
    CATSYSTEM2 = "CATSYSTEM2"
    PC = "PC"
    PSP = "PSP"
    NINTENDO_SWITCH = "NINTENDO_SWITCH"
    CMVS = "CMVS"
    UNKNOWN = "UNKNOWN"

    @property
    def display_name(self) -> str:
        return ENGINE_INFO[self].name

    @property
    def abbr(self) -> str:
        return ENGINE_INFO[self].abbr

    @property
    def color(self) -> str:
        return ENGINE_INFO[self].color

    @property
    def icon(self) -> str:
        return ENGINE_INFO[self].icon

    @property
    def runtime_key(self) -> str:
        return ENGINE_INFO[self].runtime_key


@dataclass(frozen=True)
class EngineInfo:
    name: str
    abbr: str
    color: str
    icon: str
    runtime_key: str
    description: str


ENGINE_INFO: dict[EngineType, EngineInfo] = {
    EngineType.KIRIKIRI: EngineInfo("Kirikiri", "KR2", "#3AA6D8", "◈", "krkrsdl3", "KiriKiri / KAG / TJS"),
    EngineType.ONS: EngineInfo("ONScripter", "ONS", "#7D61D9", "◇", "onscripter", "NScripter / ONScripter"),
    EngineType.TYRANO: EngineInfo("Tyrano", "TY", "#5D7BEE", "T", "web", "TyranoBuilder HTML runtime"),
    EngineType.RPGMAKER: EngineInfo("RPG Maker RGSS", "RPGM", "#E9845F", "♜", "mkxp-z", "XP / VX / VX Ace"),
    EngineType.RPG_MV: EngineInfo("RPG Maker MV", "MV", "#34B77B", "◆", "web", "RPG Maker MV HTML runtime"),
    EngineType.RPG_MZ: EngineInfo("RPG Maker MZ", "MZ", "#1EA36D", "◆", "web", "RPG Maker MZ HTML runtime"),
    EngineType.VN: EngineInfo("VN", "VN", "#668BD8", "V", "web", "globalData.vndata HTML runtime"),
    EngineType.WEB_OTHER: EngineInfo("WebOther", "WEB", "#6379BB", "W", "web", "Generic local HTML runtime"),
    EngineType.ARTEMIS: EngineInfo("Artemis", "AR", "#8B5D93", "A", "artemis", "Artemis visual novel runtime"),
    EngineType.SIGLUS: EngineInfo("Siglus", "SIG", "#416FC5", "S", "siglus", "SiglusEngine"),
    EngineType.REALLIVE: EngineInfo("RealLive", "RL", "#C46D93", "R", "game_launcher", "RealLive game_launcher"),
    EngineType.AVG32: EngineInfo("AVG32", "AVG", "#B38358", "32", "game_launcher", "AVG32 game_launcher"),
    EngineType.XSYS35: EngineInfo("System35", "S3X", "#47B7AB", "3", "xsystem35", "AliceSoft System 3.x"),
    EngineType.XSYS4: EngineInfo("System4", "S4X", "#4C88C9", "4", "xsystem4", "AliceSoft System 4"),
    EngineType.UK2: EngineInfo("UK2", "UK", "#A67C52", "U", "game_launcher", "PC-98 UK2 runtime"),
    EngineType.FVP: EngineInfo("FVP", "FVP", "#B46A39", "F", "rfvp", "FVP visual novel runtime"),
    EngineType.ETHORNELL: EngineInfo("Ethornell / BGI", "BGI", "#E0A431", "B", "ethornell", "BGI / Ethornell"),
    EngineType.RENPY: EngineInfo("Ren'Py", "RPY", "#D45A83", "R", "renpy", "Ren'Py 7 / 8"),
    EngineType.RUFFLE: EngineInfo("Ruffle", "SWF", "#D45A52", "▶", "ruffle", "Flash / SWF"),
    EngineType.YURIS: EngineInfo("YU-RIS", "YR", "#D59B4B", "Y", "wine", "YU-RIS Windows runtime"),
    EngineType.CATSYSTEM2: EngineInfo("CatSystem2", "CS2", "#C79A58", "C", "wine", "CatSystem2 Windows runtime"),
    EngineType.PC: EngineInfo("PC Game", "PC", "#6B8BA4", "P", "wine", "Windows executable"),
    EngineType.PSP: EngineInfo("PlayStation Portable", "PSP", "#5D7BC3", "P", "ppsspp", "PPSSPP"),
    EngineType.NINTENDO_SWITCH: EngineInfo("Nintendo Switch", "NS", "#E35C5C", "N", "switch", "Switch emulator"),
    EngineType.CMVS: EngineInfo("CMVS", "CMVS", "#4D8FBD", "C", "cmvs", "Prize CMVS"),
    EngineType.UNKNOWN: EngineInfo("Unknown", "UNK", "#7A8292", "?", "", "Unrecognized game"),
}


@dataclass(slots=True)
class Candidate:
    source: str
    item_id: str
    title: str
    subtitle: str = ""
    detail: str = ""
    cover_url: str = ""
    download_url: str = ""
    score: int = 0
    vndb_id: str | None = None
    metadata_title: str | None = None
    cover_kind: str = ""


@dataclass(slots=True)
class Game:
    uri: str
    title: str
    engine: EngineType
    launch_target: str = ""
    cover_uri: str | None = None
    cover_source: str | None = None
    vndb_id: str | None = None
    metadata_title: str | None = None
    launch_file: str | None = None
    runtime_id: str | None = None
    custom_args: list[str] = field(default_factory=list)
    save_dir: str | None = None
    open_time: int = 0
    play_time: int = 0
    quick_launch: bool = False
    detected_title: str | None = None
    package: str | None = None
    external_alias: str | None = None
    missing: bool = False
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return Path(self.uri)

    @property
    def display_cover(self) -> str | None:
        if self.cover_uri and Path(self.cover_uri).is_file():
            return self.cover_uri
        return None

    def as_row(self) -> tuple[Any, ...]:
        return (
            self.uri,
            self.title,
            self.engine.value,
            self.launch_target,
            self.cover_uri,
            self.cover_source,
            self.vndb_id,
            self.metadata_title,
            self.launch_file,
            self.runtime_id,
            "\n".join(self.custom_args),
            self.save_dir,
            self.open_time,
            self.play_time,
            int(self.quick_launch),
            self.detected_title,
            self.package,
            self.external_alias,
            int(self.missing),
        )

    @classmethod
    def from_row(cls, row: Any) -> "Game":
        return cls(
            uri=row["uri"],
            title=row["title"],
            engine=_engine(row["engine"]),
            launch_target=row["launch_target"] or "",
            cover_uri=row["cover_uri"],
            cover_source=row["cover_source"],
            vndb_id=row["vndb_id"],
            metadata_title=row["metadata_title"],
            launch_file=row["launch_file"],
            runtime_id=row["runtime_id"],
            custom_args=[part for part in (row["custom_args"] or "").splitlines() if part],
            save_dir=row["save_dir"],
            open_time=row["open_time"] or 0,
            play_time=row["play_time"] or 0,
            quick_launch=bool(row["quick_launch"]),
            detected_title=row["detected_title"],
            package=row["package"],
            external_alias=row["external_alias"],
            missing=bool(row["missing"]),
        )


def _engine(value: str) -> EngineType:
    try:
        return EngineType(value)
    except ValueError:
        return EngineType.UNKNOWN


@dataclass(slots=True)
class Detection:
    engine: EngineType
    confidence: int
    launch_target: str
    external_alias: str | None = None
    title_hint: str | None = None


UNKNOWN = Detection(EngineType.UNKNOWN, 0, "")
GAME_DIR = "DIR"
