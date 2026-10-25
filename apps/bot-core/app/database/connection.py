"""Database connection management for Bot Core."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import BotConfig

try:
    from turso_client import TursoConnection, TursoError
    TURSO_AVAILABLE = True
except ImportError:
    TursoConnection = None  # type: ignore
    TursoError = Exception  # type: ignore
    TURSO_AVAILABLE = False

import sqlite3

LOG = logging.getLogger("botcore.database")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Database connection supporting both Turso (production) and SQLite (dev/test)."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.backend = config.db_backend
        self._conn: Any = None
        
        if self.backend in (None, "turso"):
            turso = self._get_turso_config()
            if turso:
                if not TURSO_AVAILABLE:
                    raise RuntimeError(
                        "Turso is configured but turso_client is not available; "
                        "refusing to fall back to SQLite"
                    )
                url, token = turso
                try:
                    self._conn = TursoConnection(url, token)
                    self.backend = "turso"
                    LOG.info("Database backend: Turso (remote)")
                    return
                except TursoError as exc:
                    # Never silently fall back to a local SQLite file when
                    # Turso credentials are present in production.
                    raise RuntimeError(f"Cannot connect to Turso: {exc}") from exc
        
        # SQLite fallback
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(config.db_path, isolation_level=None, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self.backend = "sqlite"
        LOG.info("Database backend: SQLite (%s)", config.db_path)
    
    def _get_turso_config(self) -> tuple[str, str] | None:
        url = os.getenv("TURSO_URL", "").strip()
        token = os.getenv("TURSO_TOKEN", "").strip()
        if not url and not token:
            return None
        if not url or not token:
            raise RuntimeError("TURSO_URL and TURSO_TOKEN must be set together")
        return url, token
    
    @property
    def conn(self) -> Any:
        return self._conn
    
    @contextmanager
    def transaction(self):
        """Transaction context manager with automatic rollback on error."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                LOG.exception("Failed to rollback transaction; connection may be lost")
            raise
    
    def execute(self, sql: str, params: tuple = ()) -> Any:
        return self._conn.execute(sql, params)
    
    def executemany(self, sql: str, params: list[tuple]) -> Any:
        return self._conn.executemany(sql, params)
    
    def executescript(self, script: str) -> Any:
        return self._conn.executescript(script)
    
    def fetchone(self, sql: str, params: tuple = ()) -> Any:
        return self._conn.execute(sql, params).fetchone()
    
    def fetchall(self, sql: str, params: tuple = ()) -> list[Any]:
        return self._conn.execute(sql, params).fetchall()
    
    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def utcnow(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")