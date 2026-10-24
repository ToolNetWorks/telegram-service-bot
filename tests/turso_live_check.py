#!/usr/bin/env python3
"""Live Turso check (manual).  Creates and drops a temporary table only."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bot import env_file
from turso_client import TursoConnection, TursoError


def main() -> int:
    env_file(str(Path(__file__).resolve().parent.parent / ".env"))
    url = os.getenv("TURSO_URL", "").strip()
    token = os.getenv("TURSO_TOKEN", "").strip()
    if not url or not token:
        print("SKIP: TURSO_URL/TURSO_TOKEN chưa được thiết lập")
        return 0
    name = "_bot_live_check_" + secrets.token_hex(4)
    connection = TursoConnection(url, token, timeout=20)
    try:
        print("Turso connection: OK")
        connection.execute(f"CREATE TABLE {name}(id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
        connection.execute(f"INSERT INTO {name}(v) VALUES ('autocommit')")
        count = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        assert count == 1, count

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(f"INSERT INTO {name}(v) VALUES ('rollback-me')")
        inside = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        assert inside == 2, inside
        connection.execute("ROLLBACK")
        after = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        assert after == 1, after
        print("Turso transaction rollback: OK")

        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(f"INSERT INTO {name}(v) VALUES ('commit-me')")
        committed_id = cursor.lastrowid
        assert committed_id is not None
        connection.execute("COMMIT")
        committed = connection.execute(f"SELECT v FROM {name} WHERE id=?", (committed_id,)).fetchone()["v"]
        assert committed == "commit-me", committed
        print("Turso transaction commit: OK")

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(f"INSERT INTO {name}(v) VALUES ('x')")
        try:
            connection.execute(f"INSERT INTO {name}(id,v) VALUES (1,'duplicate')")
        except TursoError:
            pass
        else:
            raise AssertionError("expected unique constraint error")
        connection.execute("ROLLBACK")
        final = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        assert final == 2, final
        print("Turso constraint + rollback: OK")
        return 0
    finally:
        try:
            if connection._baton is not None:
                connection.execute("ROLLBACK")
            connection.execute(f"DROP TABLE IF EXISTS {name}")
        except Exception:
            pass
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
