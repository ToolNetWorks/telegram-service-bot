#!/usr/bin/env python3
"""Container health check: verify the configured database, never print secrets."""
from __future__ import annotations

import os
import sqlite3
import sys

from turso_client import TursoConnection


def main() -> int:
    url = os.getenv("TURSO_URL", "").strip()
    token = os.getenv("TURSO_TOKEN", "").strip()
    force_sqlite = os.getenv("DB_BACKEND", "").strip().lower() == "sqlite"
    if (url or token) and not force_sqlite:
        if not url or not token:
            print("FAIL: TURSO_URL/TURSO_TOKEN chưa đầy đủ")
            return 1
        try:
            connection = TursoConnection(url, token, timeout=10)
            ok = connection.ping()
            connection.close()
        except Exception as exc:
            print(f"FAIL: Turso không khả dụng: {exc}")
            return 1
        if not ok:
            print("FAIL: Turso SELECT 1 thất bại")
            return 1
        print("OK: Turso")
        return 0
    path = os.getenv("DB_PATH", "./data/bot.sqlite3")
    try:
        connection = sqlite3.connect(path, timeout=5)
        connection.execute("SELECT 1")
        connection.close()
    except Exception as exc:
        print(f"FAIL: SQLite không khả dụng: {exc}")
        return 1
    print("OK: SQLite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
