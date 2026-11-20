"""Application-wide persistent data (SQLite): preferences and recent projects."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

APP_DIR_NAME = "synapse"


def app_data_dir() -> Path:
    """Platform-appropriate writable directory for SYNAPSE's own data."""
    override = os.environ.get("SYNAPSE_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_DIR_NAME


class AppDatabase:
    """Small SQLite store for settings and the recent-project list."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path) if path else app_data_dir() / "app.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recent_projects (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    opened_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plugins (
                    name TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    installed_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    # -- settings -------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value)
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, payload),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            self._conn.commit()

    # -- recent projects ------------------------------------------------
    def add_recent(self, path: str, name: str = "") -> None:
        resolved = str(Path(path).expanduser().resolve())
        with self._lock:
            self._conn.execute(
                "INSERT INTO recent_projects(path, name, opened_at) VALUES(?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET name = excluded.name, opened_at = excluded.opened_at",
                (resolved, name or Path(resolved).stem, time.time()),
            )
            self._conn.execute(
                "DELETE FROM recent_projects WHERE path NOT IN "
                "(SELECT path FROM recent_projects ORDER BY opened_at DESC LIMIT 20)"
            )
            self._conn.commit()

    def recent(self, limit: int = 12) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT path, name, opened_at FROM recent_projects "
                "ORDER BY opened_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def remove_recent(self, path: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM recent_projects WHERE path = ?", (str(path),))
            self._conn.commit()

    def clear_recent(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM recent_projects")
            self._conn.commit()

    # -- plugins --------------------------------------------------------
    def record_plugin(self, name: str, version: str, enabled: bool = True) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO plugins(name, version, enabled, installed_at) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET version = excluded.version, enabled = excluded.enabled",
                (name, version, int(enabled), time.time() if enabled else time.time()),
            )
            self._conn.commit()

    def plugins(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, version, enabled, installed_at FROM plugins ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_default: AppDatabase | None = None


def default_database() -> AppDatabase:
    global _default
    if _default is None:
        _default = AppDatabase()
    return _default
