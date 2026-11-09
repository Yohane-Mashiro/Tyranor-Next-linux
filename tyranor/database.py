from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .models import Game
from .paths import database_path


SCHEMA_VERSION = 1


class Library:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._write_lock = threading.RLock()
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            with self.connection:
                yield self.connection

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS games (
                uri TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                engine TEXT NOT NULL,
                launch_target TEXT NOT NULL DEFAULT '',
                cover_uri TEXT,
                cover_source TEXT,
                vndb_id TEXT,
                metadata_title TEXT,
                launch_file TEXT,
                runtime_id TEXT,
                custom_args TEXT NOT NULL DEFAULT '',
                save_dir TEXT,
                open_time INTEGER NOT NULL DEFAULT 0,
                play_time INTEGER NOT NULL DEFAULT 0,
                quick_launch INTEGER NOT NULL DEFAULT 0,
                detected_title TEXT,
                package TEXT,
                external_alias TEXT,
                missing INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS scan_roots (
                path TEXT PRIMARY KEY,
                added_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS launch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uri TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                exit_code INTEGER
            );
            CREATE TABLE IF NOT EXISTS game_overrides (
                uri TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (uri, key)
            );
            CREATE TABLE IF NOT EXISTS save_versions (
                id TEXT PRIMARY KEY,
                uri TEXT NOT NULL,
                archive_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'local'
            );
            CREATE INDEX IF NOT EXISTS idx_games_open ON games(open_time DESC);
            CREATE INDEX IF NOT EXISTS idx_history_uri ON launch_history(uri, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_versions_uri ON save_versions(uri, created_at DESC);
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def add_root(self, path: str) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO scan_roots(path, added_at) VALUES(?, ?)",
                (str(Path(path).expanduser().resolve()), int(time.time())),
            )

    def remove_root(self, path: str) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM scan_roots WHERE path = ?", (path,))

    def roots(self) -> list[str]:
        return [row["path"] for row in self.connection.execute("SELECT path FROM scan_roots ORDER BY added_at")]

    def upsert_games(self, games: Iterable[Game]) -> None:
        sql = """
        INSERT INTO games (
            uri, title, engine, launch_target, cover_uri, cover_source, vndb_id,
            metadata_title, launch_file, runtime_id, custom_args, save_dir,
            open_time, play_time, quick_launch, detected_title, package,
            external_alias, missing
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uri) DO UPDATE SET
            title=excluded.title,
            engine=excluded.engine,
            launch_target=excluded.launch_target,
            cover_uri=excluded.cover_uri,
            cover_source=excluded.cover_source,
            vndb_id=excluded.vndb_id,
            metadata_title=excluded.metadata_title,
            launch_file=excluded.launch_file,
            runtime_id=excluded.runtime_id,
            custom_args=excluded.custom_args,
            save_dir=excluded.save_dir,
            detected_title=excluded.detected_title,
            package=excluded.package,
            external_alias=excluded.external_alias,
            missing=excluded.missing
        """
        with self.transaction() as db:
            db.executemany(sql, [game.as_row() for game in games])

    def save_game(self, game: Game) -> None:
        self.upsert_games([game])
        with self.transaction() as db:
            db.execute(
                "UPDATE games SET open_time = ?, play_time = ?, quick_launch = ?, missing = ? WHERE uri = ?",
                (
                    game.open_time,
                    game.play_time,
                    int(game.quick_launch),
                    int(game.missing),
                    game.uri,
                ),
            )
        self._save_overrides(game)

    def _save_overrides(self, game: Game) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM game_overrides WHERE uri = ?", (game.uri,))
            db.executemany(
                "INSERT INTO game_overrides(uri, key, value) VALUES(?, ?, ?)",
                [(game.uri, key, str(value)) for key, value in game.overrides.items()],
            )

    def all_games(self) -> list[Game]:
        rows = self.connection.execute(
            "SELECT * FROM games ORDER BY title COLLATE NOCASE"
        ).fetchall()
        result: list[Game] = []
        for row in rows:
            game = Game.from_row(row)
            game.overrides = {
                item["key"]: item["value"]
                for item in self.connection.execute(
                    "SELECT key, value FROM game_overrides WHERE uri = ?", (game.uri,)
                )
            }
            result.append(game)
        return result

    def get_game(self, uri: str) -> Game | None:
        row = self.connection.execute("SELECT * FROM games WHERE uri = ?", (uri,)).fetchone()
        if row is None:
            return None
        game = Game.from_row(row)
        game.overrides = {
            item["key"]: item["value"]
            for item in self.connection.execute(
                "SELECT key, value FROM game_overrides WHERE uri = ?", (uri,)
            )
        }
        return game

    def recent_games(self, limit: int = 20) -> list[Game]:
        rows = self.connection.execute(
            "SELECT * FROM games WHERE open_time > 0 ORDER BY open_time DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Game.from_row(row) for row in rows]

    def quick_games(self) -> list[Game]:
        rows = self.connection.execute(
            "SELECT * FROM games WHERE quick_launch = 1 ORDER BY title COLLATE NOCASE"
        ).fetchall()
        return [Game.from_row(row) for row in rows]

    def set_quick(self, uri: str, enabled: bool) -> bool:
        count = self.connection.execute(
            "SELECT COUNT(*) AS n FROM games WHERE quick_launch = 1"
        ).fetchone()["n"]
        if enabled and count >= 3:
            return False
        with self.transaction() as db:
            db.execute("UPDATE games SET quick_launch = ? WHERE uri = ?", (int(enabled), uri))
        return True

    def mark_opened(self, uri: str) -> int:
        now = int(time.time() * 1000)
        with self.transaction() as db:
            db.execute("UPDATE games SET open_time = ? WHERE uri = ?", (now, uri))
            db.execute(
                "INSERT INTO launch_history(uri, started_at) VALUES(?, ?)",
                (uri, now),
            )
            return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

    def mark_closed(self, history_id: int, exit_code: int) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE launch_history SET ended_at = ?, exit_code = ? WHERE id = ?",
                (int(time.time() * 1000), exit_code, history_id),
            )

    def delete_game(self, uri: str) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM game_overrides WHERE uri = ?", (uri,))
            db.execute("DELETE FROM launch_history WHERE uri = ?", (uri,))
            db.execute("DELETE FROM save_versions WHERE uri = ?", (uri,))
            db.execute("DELETE FROM games WHERE uri = ?", (uri,))

    def history(self, uri: str, limit: int = 30) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM launch_history WHERE uri = ? ORDER BY started_at DESC LIMIT ?",
            (uri, limit),
        ).fetchall()

    def add_save_version(self, version_id: str, uri: str, archive_path: str, content_hash: str, source: str) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO save_versions(id, uri, archive_path, content_hash, created_at, source) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (version_id, uri, archive_path, content_hash, int(time.time() * 1000), source),
            )

    def save_versions(self, uri: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM save_versions WHERE uri = ? ORDER BY created_at DESC",
            (uri,),
        ).fetchall()

    def delete_save_version(self, version_id: str) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM save_versions WHERE id = ?", (version_id,))

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM games").fetchone()[0])
