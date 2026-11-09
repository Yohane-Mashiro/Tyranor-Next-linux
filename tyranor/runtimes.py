from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .models import EngineType
from .paths import data_home
from .settings import Settings


@dataclass(frozen=True, slots=True)
class RuntimeDefinition:
    key: str
    name: str
    candidates: tuple[str, ...]
    engines: tuple[EngineType, ...]
    default_args: tuple[str, ...] = ("{path}",)
    description: str = ""
    homepage: str = ""
    managed: bool = False


RUNTIMES: dict[str, RuntimeDefinition] = {
    "renpy": RuntimeDefinition(
        "renpy",
        "Ren'Py",
        ("renpy", "renpy.sh"),
        (EngineType.RENPY,),
        (),
        "Ren'Py native Linux runtime",
        "https://www.renpy.org/",
    ),
    "krkrsdl3": RuntimeDefinition(
        "krkrsdl3",
        "krkrsdl3",
        ("krkrsdl3", "krkrsdl3-linux"),
        (EngineType.KIRIKIRI,),
        ("{target}",),
        "KiriKiri SDL3 native runtime",
        "https://github.com/uyjulian/krkrsdl3",
    ),
    "onscripter": RuntimeDefinition(
        "onscripter",
        "ONScripter",
        ("onscripter", "onscripter-en", "onsyuri"),
        (EngineType.ONS,),
        ("--root", "{path}"),
        "ONScripter native Linux runtime",
        "https://github.com/YuriSizuku/OnscripterYuri",
    ),
    "artemis": RuntimeDefinition(
        "artemis",
        "Artemis",
        ("artemis", "artemis-linux"),
        (EngineType.ARTEMIS,),
        ("{path}",),
        "Artemis native runtime",
    ),
    "siglus": RuntimeDefinition(
        "siglus",
        "Siglus / game_launcher",
        ("siglus", "siglus-rs", "game_launcher"),
        (EngineType.SIGLUS, EngineType.REALLIVE, EngineType.AVG32, EngineType.UK2),
        ("{path}",),
        "siglus_rs / game_launcher native runtime",
        "https://github.com/xmoezzz/siglus_rs",
    ),
    "game_launcher": RuntimeDefinition(
        "game_launcher",
        "Framebuffer game_launcher",
        ("game_launcher", "game-launcher"),
        (EngineType.REALLIVE, EngineType.AVG32, EngineType.UK2),
        ("{path}",),
        "RealLive / AVG32 / UK2 native runtime",
    ),
    "rfvp": RuntimeDefinition(
        "rfvp",
        "rfvp",
        ("rfvp", "rfvp-linux"),
        (EngineType.FVP,),
        ("{path}",),
        "FVP Rust runtime",
        "https://github.com/xmoezzz/rfvp",
    ),
    "xsystem35": RuntimeDefinition(
        "xsystem35",
        "xsystem35",
        ("xsystem35", "xsystem35-sdl2"),
        (EngineType.XSYS35,),
        ("{path}",),
        "System 3.x SDL2 runtime",
        "https://github.com/kichikuou/xsystem35-sdl2",
    ),
    "xsystem4": RuntimeDefinition(
        "xsystem4",
        "xsystem4",
        ("xsystem4",),
        (EngineType.XSYS4,),
        ("{path}",),
        "System 4 runtime",
        "https://github.com/nunuhara/xsystem4",
    ),
    "ethornell": RuntimeDefinition(
        "ethornell",
        "Ethornell",
        ("ethornell", "ethornell-player"),
        (EngineType.ETHORNELL,),
        ("{path}",),
        "Ethornell / BGI runtime",
    ),
    "cmvs": RuntimeDefinition(
        "cmvs",
        "CMVS",
        ("cmvs", "cmvs-rs"),
        (EngineType.CMVS,),
        ("{path}",),
        "CMVS native runtime",
    ),
    "mkxp-z": RuntimeDefinition(
        "mkxp-z",
        "mkxp-z",
        ("mkxp-z", "mkxp"),
        (EngineType.RPGMAKER,),
        ("{path}",),
        "RPG Maker XP / VX / VX Ace runtime",
        "https://github.com/mkxp-z/mkxp-z",
    ),
    "ruffle": RuntimeDefinition(
        "ruffle",
        "Ruffle",
        ("ruffle", "ruffle-desktop"),
        (EngineType.RUFFLE,),
        ("{target}",),
        "Ruffle desktop Flash player",
        "https://ruffle.rs/",
    ),
    "ppsspp": RuntimeDefinition(
        "ppsspp",
        "PPSSPP",
        ("ppsspp", "PPSSPPSDL"),
        (EngineType.PSP,),
        ("{target}",),
        "PPSSPP PlayStation Portable emulator",
        "https://www.ppsspp.org/",
    ),
    "switch": RuntimeDefinition(
        "switch",
        "Switch emulator",
        ("ryujinx", "eden", "yuzu"),
        (EngineType.NINTENDO_SWITCH,),
        ("{target}",),
        "Ryujinx / Eden / Yuzu compatible emulator",
    ),
    "wine": RuntimeDefinition(
        "wine",
        "Wine",
        ("wine",),
        (EngineType.YURIS, EngineType.CATSYSTEM2, EngineType.PC),
        ("{target}",),
        "Windows compatibility layer",
        "https://www.winehq.org/",
    ),
    "web": RuntimeDefinition(
        "web",
        "Local Web Host",
        (sys.executable,),
        (EngineType.TYRANO, EngineType.RPG_MV, EngineType.RPG_MZ, EngineType.VN, EngineType.WEB_OTHER),
        (),
        "Built-in local HTTP host and browser window",
    ),
}

REMOVED_ENGINE_TYPES = {
    EngineType.RUFFLE,
    EngineType.YURIS,
    EngineType.CATSYSTEM2,
    EngineType.PC,
    EngineType.PSP,
    EngineType.NINTENDO_SWITCH,
    EngineType.CMVS,
}


COMMON_DIRS = (
    Path.home() / ".local/bin",
    Path.home() / "Applications",
    Path.home() / ".local/opt",
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/opt"),
)


@dataclass(slots=True)
class RuntimeStatus:
    key: str
    name: str
    available: bool
    executable: str | None
    source: str
    engines: list[EngineType]
    description: str
    homepage: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


class RuntimeManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[str, RuntimeStatus] = {}

    def refresh(self) -> dict[str, RuntimeStatus]:
        self._cache = {key: self.resolve(key) for key in RUNTIMES}
        return dict(self._cache)

    def statuses(self) -> dict[str, RuntimeStatus]:
        return dict(self._cache) if self._cache else self.refresh()

    def status_for_engine(self, engine: EngineType) -> RuntimeStatus | None:
        return self.statuses().get(engine.runtime_key)

    def candidates_for_engine(self, engine: EngineType) -> list[RuntimeStatus]:
        return [
            status
            for status in self.statuses().values()
            if engine in status.engines
        ]

    def resolve(self, key: str, refresh: bool = False) -> RuntimeStatus:
        definition = RUNTIMES[key]
        override = self.settings.runtime_override(key)
        configured = str(override.get("executable", "")).strip()
        if configured:
            path = _expand_executable(configured)
            args = override.get("args")
            env = override.get("env")
            return RuntimeStatus(
                key=key,
                name=definition.name,
                available=path is not None,
                executable=str(path) if path else configured,
                source="custom",
                engines=list(definition.engines),
                description=definition.description,
                homepage=definition.homepage,
                args=list(args) if isinstance(args, list) else list(definition.default_args),
                env=dict(env) if isinstance(env, dict) else {},
            )
        if key == "web":
            return RuntimeStatus(
                key=key,
                name=definition.name,
                available=True,
                executable=sys.executable,
                source="built-in",
                engines=list(definition.engines),
                description=definition.description,
                homepage=definition.homepage,
                args=list(definition.default_args),
                env={},
            )
        path = None
        for candidate in definition.candidates:
            path = _expand_executable(candidate)
            if path:
                break
        return RuntimeStatus(
            key=key,
            name=definition.name,
            available=path is not None,
            executable=str(path) if path else None,
            source="PATH" if path and path.parent in {Path("/usr/bin"), Path("/usr/local/bin")} else "system",
            engines=list(definition.engines),
            description=definition.description,
            homepage=definition.homepage,
            args=list(definition.default_args),
            env={},
        )

    def set_override(
        self,
        key: str,
        executable: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        overrides = self.settings.get("runtime_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        overrides[key] = {
            "executable": executable.strip(),
            "args": args if args is not None else list(RUNTIMES[key].default_args),
            "env": env or {},
        }
        self.settings.set("runtime_overrides", overrides)
        self._cache.pop(key, None)

    def clear_override(self, key: str) -> None:
        overrides = self.settings.get("runtime_overrides", {})
        if isinstance(overrides, dict):
            overrides.pop(key, None)
            self.settings.set("runtime_overrides", overrides)
        self._cache.pop(key, None)

    def summary(self) -> tuple[int, int]:
        statuses = self.statuses()
        available = sum(1 for status in statuses.values() if status.available)
        return available, len(statuses)

    def visible_engines(self) -> list[tuple[EngineType, RuntimeStatus]]:
        statuses = self.statuses()
        result: list[tuple[EngineType, RuntimeStatus]] = []
        for engine in EngineType:
            if engine in REMOVED_ENGINE_TYPES or engine is EngineType.UNKNOWN:
                continue
            status = statuses.get(engine.runtime_key)
            if status is not None and status.available:
                result.append((engine, status))
        return result


def _expand_executable(value: str) -> Path | None:
    if not value:
        return None
    expanded = os.path.expandvars(os.path.expanduser(value))
    candidate = Path(expanded)
    if candidate.is_absolute():
        return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None
    found = shutil.which(expanded)
    if found:
        return Path(found)
    for directory in COMMON_DIRS:
        path = directory / expanded
        if path.is_file() and os.access(path, os.X_OK):
            return path
    managed = data_home() / "runtimes"
    if managed.is_dir():
        for path in managed.glob(f"**/{Path(expanded).name}"):
            if path.is_file() and os.access(path, os.X_OK):
                return path
    return None
