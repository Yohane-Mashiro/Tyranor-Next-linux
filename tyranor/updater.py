from __future__ import annotations

from dataclasses import dataclass

import requests

from . import __version__


RELEASES_URL = "https://api.github.com/repos/Weiss-UltimateSavior/Tyranor-Next/releases"


@dataclass(slots=True)
class ReleaseInfo:
    tag: str
    name: str
    body: str
    page_url: str
    prerelease: bool
    published_at: str


def check_updates(include_prerelease: bool = False) -> tuple[str, list[ReleaseInfo]]:
    response = requests.get(
        RELEASES_URL,
        params={"per_page": 20},
        timeout=(10, 25),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"TyranorNextLinux/{__version__}",
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"GitHub returned {response.status_code}.")
    releases = []
    for item in response.json():
        if item.get("draft") or (item.get("prerelease") and not include_prerelease):
            continue
        releases.append(
            ReleaseInfo(
                str(item.get("tag_name") or ""),
                str(item.get("name") or item.get("tag_name") or ""),
                str(item.get("body") or ""),
                str(item.get("html_url") or ""),
                bool(item.get("prerelease")),
                str(item.get("published_at") or ""),
            )
        )
    return __version__, releases
