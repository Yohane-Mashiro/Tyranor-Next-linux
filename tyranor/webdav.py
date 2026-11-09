from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse

import requests
from lxml import etree

from .models import Game
from .saves import MAX_ARCHIVE_BYTES, SaveManager, archive_hash
from .secrets import SecretStore
from .settings import Settings


class WebDavError(RuntimeError):
    pass


@dataclass(slots=True)
class RemoteVersion:
    name: str
    url: str
    size: int
    etag: str


class WebDavSync:
    NAMESPACE = "TYN-saves"

    def __init__(self, settings: Settings, saves: SaveManager):
        self.settings = settings
        self.saves = saves
        self.session = requests.Session()
        self._lock = threading.Lock()
        self.secrets = SecretStore()
        self._origin: tuple[str, str] | None = None

    def configured(self) -> bool:
        return bool(
            self.settings.get("save_sync_enabled", False)
            and str(self.settings.get("save_sync_url", "")).strip()
        )

    def test_connection(self, url: str, username: str, password: str) -> str:
        base = _validated_base(url)
        parsed = urlparse(base)
        self._origin = (parsed.scheme, parsed.netloc)
        with self._request(base, username, password, "PROPFIND", headers={"Depth": "0"}) as response:
            if response.status_code not in {200, 207, 404}:
                raise WebDavError(f"WebDAV returned {response.status_code}.")
        return "Connection succeeded"

    def sync_game(self, game: Game, direction: str = "bidirectional") -> str:
        if not self.configured():
            raise WebDavError("WebDAV sync is not enabled.")
        url = str(self.settings.get("save_sync_url", ""))
        username = str(self.settings.get("save_sync_username", ""))
        password = self.secrets.get("webdav_password", "")
        base = _validated_base(url)
        root = urljoin(base, f"{self.NAMESPACE}/")
        folder = urljoin(root, f"{game_key(game.uri)}/")
        with self._lock:
            self._ensure_collection(root, username, password)
            self._ensure_collection(folder, username, password)
            versions = self._list(folder, username, password)
            local_versions = self.saves.versions(game)
            local_latest = local_versions[0] if local_versions else None
            remote_latest = versions[0] if versions else None
            if direction in {"upload", "bidirectional"}:
                location = self.saves.resolve(game)
                if location is not None:
                    current = self.saves.create_version(game)
                    if remote_latest is None or remote_latest.name != current.version_id:
                        self._put(
                            urljoin(folder, current.version_id),
                            current.archive_path,
                            username,
                            password,
                        )
                        local_latest = current
                    if direction == "upload":
                        self._trim(folder, username, password)
                        return f"Uploaded {current.version_id}"
            if direction in {"download", "bidirectional"} and remote_latest is not None:
                if local_latest is None or local_latest.version_id != remote_latest.name:
                    archive = self.saves.managed_dir(game) / "remote" / remote_latest.name
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    self._get(remote_latest.url, archive, username, password)
                    digest = archive_hash(archive)
                    self.saves.library.add_save_version(
                        remote_latest.name,
                        game.uri,
                        str(archive),
                        digest,
                        "remote",
                    )
                    return f"Downloaded {remote_latest.name}"
            self._trim(folder, username, password)
            return "Already up to date"

    def list_versions(self, game: Game) -> list[RemoteVersion]:
        if not self.configured():
            raise WebDavError("WebDAV sync is not enabled.")
        base = _validated_base(str(self.settings.get("save_sync_url", "")))
        parsed = urlparse(base)
        self._origin = (parsed.scheme, parsed.netloc)
        folder = urljoin(urljoin(base, f"{self.NAMESPACE}/"), f"{game_key(game.uri)}/")
        return self._list(
            folder,
            str(self.settings.get("save_sync_username", "")),
            self.secrets.get("webdav_password", ""),
        )

    def download_version(self, game: Game, remote: RemoteVersion):
        if not self.configured():
            raise WebDavError("WebDAV sync is not enabled.")
        target = self.saves.managed_dir(game) / "remote" / remote.name
        target.parent.mkdir(parents=True, exist_ok=True)
        self._get(
            remote.url,
            target,
            str(self.settings.get("save_sync_username", "")),
            self.secrets.get("webdav_password", ""),
        )
        digest = archive_hash(target)
        match = re.fullmatch(r"\d+-([0-9a-f]{12})\.zip", remote.name, re.IGNORECASE)
        if match and not digest.startswith(match.group(1).casefold()):
            target.unlink(missing_ok=True)
            raise WebDavError("Downloaded save version failed content verification.")
        self.saves.library.add_save_version(
            remote.name,
            game.uri,
            str(target),
            digest,
            "remote",
        )
        return remote.name

    def sync_all(self, games: Iterable[Game], direction: str = "bidirectional") -> list[tuple[Game, str]]:
        results: list[tuple[Game, str]] = []
        for game in games:
            try:
                results.append((game, self.sync_game(game, direction)))
            except (WebDavError, requests.RequestException) as exc:
                results.append((game, f"Failed: {exc}"))
        return results

    def _ensure_collection(self, url: str, username: str, password: str) -> None:
        with self._request(url, username, password, "MKCOL") as response:
            if response.status_code not in {201, 405, 409}:
                if response.status_code != 403:
                    raise WebDavError(f"Unable to create remote folder ({response.status_code}).")
                raise WebDavError("WebDAV rejected folder creation.")

    def _list(self, folder: str, username: str, password: str) -> list[RemoteVersion]:
        body = b"""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/><d:getetag/></d:prop></d:propfind>"""
        response = self.session.request(
            "PROPFIND",
            folder,
            auth=(username, password),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            data=body,
            timeout=(15, 60),
            stream=True,
            allow_redirects=False,
        )
        if response.status_code == 404:
            response.close()
            return []
        if response.status_code not in {200, 207}:
            response.close()
            raise WebDavError(f"Unable to list remote saves ({response.status_code}).")
        chunks: list[bytes] = []
        total = 0
        try:
            for block in response.iter_content(64 * 1024):
                total += len(block)
                if total > 10 * 1024 * 1024:
                    raise WebDavError("WebDAV directory listing exceeds 10 MiB.")
                chunks.append(block)
        finally:
            response.close()
        content = b"".join(chunks)
        if not content:
            return []
        try:
            parser = etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                huge_tree=False,
            )
            root = etree.fromstring(content, parser=parser)
        except etree.XMLSyntaxError as exc:
            raise WebDavError("WebDAV returned invalid XML.") from exc
        versions: list[RemoteVersion] = []
        for node in root.xpath("//*[local-name()='response']"):
            href = node.xpath("string(.//*[local-name()='href'][1])")
            if not href.endswith(".zip"):
                continue
            length_value = node.xpath("string(.//*[local-name()='getcontentlength'][1])")
            etag = node.xpath("string(.//*[local-name()='getetag'][1])")
            absolute = urljoin(folder, href)
            parsed = urlparse(absolute)
            if self._origin != (parsed.scheme, parsed.netloc) or not absolute.startswith(folder):
                continue
            versions.append(
                RemoteVersion(
                    name=href.rstrip("/").rsplit("/", 1)[-1],
                    url=absolute,
                    size=int(length_value or 0),
                    etag=etag,
                )
            )
        return sorted(versions, key=lambda item: item.name, reverse=True)

    def _put(self, url: str, source: Path, username: str, password: str) -> None:
        with source.open("rb") as stream:
            response = self.session.put(
                url,
                data=stream,
                auth=(username, password),
                headers={"If-None-Match": "*", "Content-Type": "application/zip"},
                timeout=(20, 600),
                allow_redirects=False,
            )
        response.close()
        if response.status_code not in {200, 201, 204, 412}:
            raise WebDavError(f"Upload failed ({response.status_code}).")

    def _get(self, url: str, destination: Path, username: str, password: str) -> None:
        temporary = destination.with_suffix(".part")
        try:
            with self.session.get(
                url,
                auth=(username, password),
                stream=True,
                timeout=(20, 600),
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise WebDavError(f"Download failed ({response.status_code}).")
                declared = int(response.headers.get("Content-Length") or 0)
                if declared > MAX_ARCHIVE_BYTES:
                    raise WebDavError("Remote save archive exceeds 1 GiB.")
                written = 0
                with temporary.open("wb") as stream:
                    for block in response.iter_content(64 * 1024):
                        written += len(block)
                        if written > MAX_ARCHIVE_BYTES:
                            raise WebDavError("Remote save archive exceeds 1 GiB.")
                        stream.write(block)
                    stream.flush()
                    os.fsync(stream.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _trim(self, folder: str, username: str, password: str) -> None:
        retention = int(self.settings.get("save_sync_retention", 10))
        if retention <= 0:
            return
        versions = self._list(folder, username, password)
        for version in versions[retention:]:
            response = self.session.delete(
                version.url,
                auth=(username, password),
                timeout=(15, 60),
                allow_redirects=False,
            )
            response.close()
            if response.status_code not in {200, 204, 404}:
                raise WebDavError(f"Remote cleanup failed ({response.status_code}).")

    def _request(self, *args, **kwargs) -> requests.Response:
        kwargs.setdefault("allow_redirects", False)
        return self.session.request(*args, timeout=(15, 60), **kwargs)


def game_key(uri: str) -> str:
    return hashlib.sha256(uri.encode("utf-8")).hexdigest()[:24]


def _validated_base(value: str) -> str:
    value = value.strip()
    if not value:
        raise WebDavError("Server URL is empty.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebDavError("Server URL must be HTTP or HTTPS.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WebDavError("Server URL cannot contain credentials, a query, or a fragment.")
    return value if value.endswith("/") else value + "/"
