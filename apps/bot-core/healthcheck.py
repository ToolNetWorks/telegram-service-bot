#!/usr/bin/env python3
"""Container health check: verify the configured database, never print secrets."""
from __future__ import annotations

import os
import sqlite3
import sys

try:
    from app.clients.engagement import EngagementClient
    from app.core.config import BotConfig
except ImportError:
    sys.path.insert(0, ".")
    from app.clients.engagement import EngagementClient
    from app.core.config import BotConfig

try:
    from turso_client import TursoConnection
except ImportError:
    TursoConnection = None


def main() -> int:
    # Check database connectivity
    url = os.getenv("TURSO_URL", "").strip()
    token = os.getenv("TURSO_TOKEN", "").strip()
    backend = os.getenv("DB_BACKEND", "").strip().lower()
    force_sqlite = backend == "sqlite"

    if backend == "turso" and (not url or not token):
        print("FAIL: DB_BACKEND=turso requires TURSO_URL and TURSO_TOKEN")
        return 1

    if (url or token) and not force_sqlite:
        if not url or not token:
            print("FAIL: TURSO_URL/TURSO_TOKEN not fully configured")
            return 1
        if TursoConnection is None:
            print("FAIL: Turso client not available")
            return 1
        try:
            connection = TursoConnection(url, token, timeout=10)
            ok = connection.ping()
            connection.close()
        except Exception as exc:
            print(f"FAIL: Turso unavailable: {exc}")
            return 1
        if not ok:
            print("FAIL: Turso SELECT 1 failed")
            return 1
        print("OK: Turso")
    else:
        path = os.getenv("DB_PATH", "/data/bot.sqlite3")
        try:
            conn = sqlite3.connect(path, timeout=5)
            conn.execute("SELECT 1")
            conn.close()
        except Exception as exc:
            print(f"FAIL: SQLite unavailable: {exc}")
            return 1
        print("OK: SQLite")

    # Check Engagement API connectivity (optional - don't fail if unavailable)
    try:
        config = BotConfig.load()
        client = EngagementClient(config)
        if client.health_check():
            print("OK: Engagement API")
        else:
            print("WARN: Engagement API unreachable")
    except Exception as exc:
        print(f"WARN: Engagement API check skipped: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())