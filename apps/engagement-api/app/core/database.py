"""Database connection for Engagement API."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

from app.core.config import settings

try:
    from turso_client import TursoConnection, TursoError
    TURSO_AVAILABLE = True
except ImportError:
    TursoConnection = None  # type: ignore
    TursoError = Exception  # type: ignore
    TURSO_AVAILABLE = False

import sqlite3

LOG = logging.getLogger("engagement.database")


class Database:
    """Database connection supporting Turso (production) and SQLite (dev/test only)."""

    def __init__(self):
        self.backend = "unknown"
        self._conn: Any = None

        # Determine if we're in production (Turso required) or dev/test (SQLite allowed)
        is_production = settings.environment.lower() == "production"
        # Also consider it production if DATABASE_URL and DATABASE_TOKEN are set
        has_turso_config = bool(settings.database_url.strip() and settings.database_token.strip())

        if TURSO_AVAILABLE and has_turso_config:
            url = settings.database_url.strip()
            token = settings.database_token.strip()
            try:
                self._conn = TursoConnection(url, token)
                self.backend = "turso"
                LOG.info("Database backend: Turso (remote)")
                return
            except TursoError as exc:
                LOG.error("Turso connection failed: %s", exc)
                if is_production:
                    raise RuntimeError(f"Production requires Turso database. Connection failed: {exc}") from exc
                LOG.warning("Falling back to SQLite for development")
        elif has_turso_config and not TURSO_AVAILABLE:
            raise RuntimeError("Turso client not available but DATABASE_URL/DATABASE_TOKEN are set. Ensure turso_client.py is present.")

        # SQLite fallback - ONLY for non-production
        if is_production:
            raise RuntimeError("Production environment requires Turso database (DATABASE_URL and DATABASE_TOKEN). SQLite not allowed.")

        db_path = os.getenv("DB_PATH", "./data/engagement.sqlite3")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, isolation_level=None, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self.backend = "sqlite"
        LOG.info("Database backend: SQLite (%s)", db_path)

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
                LOG.exception("Failed to rollback transaction")
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


# Global database instance
db = Database()