from __future__ import annotations

import hashlib
import io
import re
import time
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote, urljoin

import requests
from PIL import Image, ImageOps

from .models import Candidate, Game
from .paths import data_home
from .secrets import SecretStore
from .hikarinagi import HikarinagiAuth
from .settings import COVER_SOURCES, Settings


USER_AGENT = "TyranorNextLinux/1.0 (+https://github.com/Weiss-UltimateSavior/Tyranor-Next)"
TIMEOUT = (10, 25)


class CoverError(RuntimeError):
    pass


class CoverService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._last_request: dict[str, float] = {}
        self.cover_dir = data_home() / "covers"
        self.cover_dir.mkdir(parents=True, exist_ok=True)
        self.secrets = SecretStore()
        self.hikarinagi = HikarinagiAuth(settings, self.secrets)

    def enabled_sources(self) -> list[str]:
        enabled = self.settings.get("cover_enabled", {})
        return [
            source
            for source in self.settings.get("cover_order", [])
            if enabled.get(source, True) and source in COVER_SOURCES
        ]

    def search(self, source: str, keyword: str, limit: int = 8) -> list[Candidate]:
        query = clean_title(keyword)
        if not query:
            return []
        if source == "vndb":
            return self.search_vndb(query, limit)
        if source == "nextmoe":
            return self.search_nextmoe(query, limit)
        if source == "bangumi":
            return self.search_bangumi(query, limit)
        if source == "steam":
            return self.search_steam(query, limit)
        if source == "hikarinagi":
            return self.search_hikarinagi(query, limit)
        return []

    def list_covers(self, candidate: Candidate, limit: int = 100) -> list[Candidate]:
        if candidate.source != "nextmoe" or not candidate.item_id:
            return []
        url = (
            f"https://api.nextmoe.dev/v2/catalog/works/{quote(candidate.item_id, safe='')}"
            f"/covers?nsfw=true&limit={max(1, min(limit, 100))}"
        )
        payload = self._json(self._get(url, throttle=1.3))
        items = payload.get("items", []) if isinstance(payload, dict) else []
        output: list[Candidate] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            size = f"{width}×{height}" if width and height else ""
            output.append(
                Candidate(
                    source="nextmoe",
                    item_id=str(item.get("id", "")),
                    title=candidate.title,
                    subtitle=str(item.get("cover_kind", "")),
                    detail=size,
                    cover_url=str(item["url"]),
                    download_url=str(item["url"]),
                    score=int(item.get("vote_count") or 0),
                    vndb_id=candidate.vndb_id,
                    metadata_title=candidate.metadata_title,
                    cover_kind=str(item.get("cover_kind", "")),
                )
            )
        return sorted(output, key=lambda item: (item.score, item.subtitle == "main"), reverse=True)

    def download(self, game: Game, candidate: Candidate) -> Game:
        url = candidate.download_url or candidate.cover_url
        if not url:
            raise CoverError("The selected candidate has no image URL.")
        chunks: list[bytes] = []
        total = 0
        with self.session.get(url, timeout=TIMEOUT, stream=True) as response:
            if response.status_code != 200:
                raise CoverError(f"Image download failed ({response.status_code}).")
            for block in response.iter_content(64 * 1024):
                total += len(block)
                if total > 25 * 1024 * 1024:
                    raise CoverError("Cover image is larger than 25 MiB.")
                chunks.append(block)
        raw = b"".join(chunks)
        try:
            image = Image.open(io.BytesIO(raw))
            if image.width * image.height > 100_000_000:
                raise CoverError("Cover image dimensions are too large.")
            image.load()
        except Exception as exc:
            raise CoverError("The downloaded file is not a valid image.") from exc
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((1600, 2400), Image.Resampling.LANCZOS)
        digest = hashlib.sha256(game.uri.encode("utf-8")).hexdigest()[:16]
        target = self.cover_dir / f"{candidate.source}_{digest}.jpg"
        image.save(target, "JPEG", quality=92, optimize=True)
        game.cover_uri = str(target)
        game.cover_source = candidate.source
        if candidate.vndb_id:
            game.vndb_id = candidate.vndb_id
        if candidate.metadata_title:
            game.metadata_title = candidate.metadata_title
        return game

    def save_custom(self, game: Game, source: Path) -> Game:
        try:
            image = Image.open(source)
            if image.width * image.height > 100_000_000:
                raise CoverError("Cover image dimensions are too large.")
            image.load()
            image = ImageOps.exif_transpose(image).convert("RGB")
        except Exception as exc:
            raise CoverError("The selected file is not a valid image.") from exc
        digest = hashlib.sha256(game.uri.encode("utf-8")).hexdigest()[:16]
        target = self.cover_dir / f"custom_{digest}.jpg"
        image.thumbnail((1600, 2400), Image.Resampling.LANCZOS)
        image.save(target, "JPEG", quality=92, optimize=True)
        game.cover_uri = str(target)
        game.cover_source = "custom"
        return game

    def batch_scrape(
        self,
        games: Iterable[Game],
        on_result: Callable[[Game, bool, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int, int, int]:
        on_result = on_result or (lambda *_: None)
        should_cancel = should_cancel or (lambda: False)
        only_missing = bool(self.settings.get("cover_only_missing", True))
        updated = skipped = failed = 0
        sources = self.enabled_sources()
        for game in games:
            if should_cancel():
                break
            if only_missing and game.display_cover:
                skipped += 1
                on_result(game, False, "Already has a cover")
                continue
            success = False
            error = ""
            for source in sources:
                try:
                    candidates = self.search(source, game.title, 3)
                    for candidate in candidates:
                        if not (candidate.download_url or candidate.cover_url):
                            continue
                        try:
                            self.download(game, candidate)
                            updated += 1
                            success = True
                            on_result(game, True, COVER_SOURCES[source])
                            break
                        except CoverError as exc:
                            error = str(exc)
                    if success:
                        break
                except (requests.RequestException, CoverError, ValueError) as exc:
                    error = str(exc)
            if not success:
                failed += 1
                on_result(game, False, error or "No cover found")
        return updated, skipped, failed

    def search_vndb(self, query: str, limit: int) -> list[Candidate]:
        self._throttle("vndb", 1.1)
        body = {
            "filters": ["search", "=", query],
            "fields": (
                "title,alttitle,titles.lang,titles.title,titles.main,released,"
                "image.url,image.thumbnail,developers.name,developers.original"
            ),
            "sort": "searchrank",
            "results": max(1, min(limit, 10)),
        }
        response = self.session.post("https://api.vndb.org/kana/vn", json=body, timeout=TIMEOUT)
        if response.status_code != 200:
            raise CoverError(f"VNDB returned {response.status_code}.")
        payload = response.json()
        output: list[Candidate] = []
        for item in payload.get("results", []):
            image = item.get("image") or {}
            large = str(image.get("url") or "")
            thumb = str(image.get("thumbnail") or large)
            original = str(item.get("alttitle") or item.get("title") or "")
            local_title = ""
            for title in item.get("titles", []):
                if title.get("lang") in {"zh-Hans", "zh-Hant", "zh"} and title.get("title"):
                    local_title = str(title["title"])
                    break
                if title.get("main") and not original:
                    original = str(title.get("title") or "")
            developers = " / ".join(
                str(dev.get("original") or dev.get("name") or "")
                for dev in item.get("developers", [])[:3]
                if dev.get("original") or dev.get("name")
            )
            title = local_title or str(item.get("title") or original)
            output.append(
                Candidate(
                    source="vndb",
                    item_id=str(item.get("id", "")),
                    title=title,
                    subtitle=original,
                    detail=" · ".join(part for part in (str(item.get("id", "")), developers, str(item.get("released", ""))) if part),
                    cover_url=thumb,
                    download_url=large if self.settings.get("vndb_large_cover", True) else thumb,
                    vndb_id=str(item.get("id") or "") or None,
                    metadata_title=title or None,
                )
            )
        return output

    def search_nextmoe(self, query: str, limit: int) -> list[Candidate]:
        params = f"q={quote(query)}&nsfw=true&limit={max(1, min(limit, 100))}&include=refs"
        payload = self._json(self._get(f"https://api.nextmoe.dev/v2/catalog/works?{params}", throttle=1.3))
        output: list[Candidate] = []
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            localized = item.get("localized") or {}
            local_title = ""
            for language in ("zh-Hans", "zh-Hant"):
                value = localized.get(language) or {}
                if value.get("value") and not value.get("is_machine"):
                    local_title = str(value["value"])
                    break
            original = str(item.get("display_name") or item.get("latin") or "")
            title = local_title or original
            cover = item.get("cover") or {}
            vndb_id = None
            for ref in item.get("refs", []):
                if ref.get("source") == "vndb" and str(ref.get("external_id", "")).startswith("v"):
                    vndb_id = str(ref["external_id"])
                    break
            output.append(
                Candidate(
                    source="nextmoe",
                    item_id=str(item["id"]),
                    title=title,
                    subtitle=original if original != title else "",
                    detail=" · ".join(
                        part
                        for part in (
                            str(item.get("release_date") or ""),
                            (
                                f"{cover.get('width')}×{cover.get('height')}"
                                if cover.get("width") and cover.get("height")
                                else ""
                            ),
                        )
                        if part
                    ),
                    cover_url=str(cover.get("url") or ""),
                    download_url=str(cover.get("url") or ""),
                    vndb_id=vndb_id,
                    metadata_title=title if vndb_id else None,
                )
            )
        return output

    def search_bangumi(self, query: str, limit: int) -> list[Candidate]:
        self._throttle("bangumi", 0.6)
        body = {
            "keyword": query,
            "filter": {"type": [4]},
        }
        response = self.session.post(
            "https://api.bgm.tv/v0/search/subjects?limit=" + str(max(1, min(limit, 10))),
            json=body,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code != 200:
            raise CoverError(f"Bangumi returned {response.status_code}.")
        return [
            Candidate(
                source="bangumi",
                item_id=str(item.get("id", "")),
                title=str((item.get("name_cn") or item.get("name") or "")),
                subtitle=str(item.get("name") or ""),
                detail=f"bgm.tv/{item.get('id', '')}",
                cover_url=str((item.get("images") or {}).get("large") or ""),
            )
            for item in response.json().get("data", [])
            if (item.get("images") or {}).get("large")
        ]

    def search_steam(self, query: str, limit: int) -> list[Candidate]:
        self._throttle("steam", 0.5)
        response = self.session.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": query, "l": "schinese", "cc": "CN"},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise CoverError(f"Steam returned {response.status_code}.")
        output: list[Candidate] = []
        for item in response.json().get("items", [])[: limit * 2]:
            app_id = str(item.get("id", ""))
            if not app_id:
                continue
            cover = (
                f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg"
            )
            output.append(
                Candidate(
                    source="steam",
                    item_id=app_id,
                    title=str(item.get("name") or ""),
                    subtitle="Steam",
                    detail=f"App ID {app_id}",
                    cover_url=cover,
                )
            )
            if len(output) >= limit:
                break
        return output

    def search_hikarinagi(self, query: str, limit: int) -> list[Candidate]:
        token = self.hikarinagi.valid_access_token().strip()
        if not token:
            raise CoverError("Hikarinagi authorization is required.")
        response = self.session.get(
            "https://api.hikarinagi.org/v3/search",
            params={"q": query, "types": "galgame", "page": 1, "page_size": min(limit, 10)},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        if response.status_code in {401, 403}:
            raise CoverError("Hikarinagi token expired; authorize again.")
        if response.status_code != 200:
            raise CoverError(f"Hikarinagi returned {response.status_code}.")
        payload = response.json()
        if not payload.get("success"):
            raise CoverError("Hikarinagi rejected the search.")
        items = ((payload.get("data") or {}).get("items") or [])
        output: list[Candidate] = []
        for item in items:
            if item.get("type") != "galgame":
                continue
            cover = item.get("cover") or {}
            raw_url = str(cover.get("url") or "")
            if not raw_url:
                continue
            image_url = raw_url if raw_url.startswith(("http://", "https://")) else urljoin(
                "https://imagesp.yurari.moe/", raw_url.lstrip("/")
            )
            output.append(
                Candidate(
                    source="hikarinagi",
                    item_id=str(item.get("id", "")),
                    title=str(item.get("title") or item.get("subtitle") or ""),
                    detail=f"Hikarinagi · {cover.get('votes', 0)} votes",
                    cover_url=image_url,
                    score=int(cover.get("votes") or 0),
                )
            )
        return output

    def _get(self, url: str, throttle: float = 0.0) -> requests.Response:
        if throttle:
            self._throttle(url, throttle)
        response = self.session.get(url, timeout=TIMEOUT)
        if response.status_code == 429:
            raise CoverError("The cover source is rate-limited. Try again later.")
        if response.status_code != 200:
            raise CoverError(f"Cover source returned {response.status_code}.")
        return response

    def _throttle(self, key: str, delay: float) -> None:
        elapsed = time.monotonic() - self._last_request.get(key, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request[key] = time.monotonic()

    @staticmethod
    def _json(response: requests.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoverError("Cover source returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise CoverError("Cover source returned an invalid response.")
        return payload


def clean_title(value: str) -> str:
    title = value.strip()
    title = re.sub(r"[\[\(【（][^\]\)】）]{1,24}[\]\)】）]\s*$", "", title).strip()
    title = re.sub(r"\s+", " ", title)
    return title
