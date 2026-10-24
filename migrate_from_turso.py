#!/usr/bin/env python3
"""Export Turso back to a fresh SQLite file (rollback path).

Read-only for Turso.  The target is a new file so the current production
SQLite is never touched.  Use ``restore-sqlite.sh`` afterwards if needed.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

from bot import env_file
from db import Database
from migrate_to_turso import TABLES


def counts(db: Database):
    return {table: db.one(f"SELECT COUNT(*) c FROM {table}")["c"]
            for table, _ in TABLES}


def copy_all(source: Database, target: Database):
    with target.transaction():
        target.conn.execute("UPDATE users SET referred_by=NULL")
        for table in ("provider_orders", "ledger", "deposits", "orders",
                      "tickets", "users", "services", "settings"):
            target.conn.execute(f"DELETE FROM {table}")
        for table, columns in TABLES:
            order = {"settings": "key", "users": "user_id"}.get(table, "id")
            rows = source.all(f"SELECT {','.join(columns)} FROM {table} ORDER BY {order}")
            if not rows:
                continue
            placeholders = ",".join("?" for _ in columns)
            sql = f"INSERT OR REPLACE INTO {table}({','.join(columns)}) VALUES ({placeholders})"
            prepared = []
            for row in rows:
                values = list(row)
                if table == "users":
                    values[columns.index("referred_by")] = None
                prepared.append(tuple(values))
            target.conn.executemany(sql, prepared)
        for row in source.all("SELECT user_id,referred_by FROM users WHERE referred_by IS NOT NULL"):
            target.conn.execute("UPDATE users SET referred_by=? WHERE user_id=?",
                                (row["referred_by"], row["user_id"]))


def verify(source: Database, target: Database) -> bool:
    ok = True
    source_n, target_n = counts(source), counts(target)
    print("Xác minh số bản ghi:")
    for table, _ in TABLES:
        match = source_n[table] == target_n[table]
        ok = ok and match
        print(f"  {table:16s} turso={source_n[table]:>8d} sqlite={target_n[table]:>8d}  "
              f"{'OK' if match else 'MISMATCH'}")
    checks = [
        ("users.balance", "SELECT COALESCE(SUM(balance),0) FROM users"),
        ("ledger.delta", "SELECT COALESCE(SUM(delta),0) FROM ledger"),
        ("orders.amount", "SELECT COALESCE(SUM(amount),0) FROM orders"),
        ("deposits.amount", "SELECT COALESCE(SUM(amount),0) FROM deposits"),
        ("provider.quantity", "SELECT COALESCE(SUM(quantity),0) FROM provider_orders"),
    ]
    print("Xác minh tổng tiền:")
    for label, sql in checks:
        left = source.one(f"SELECT ({sql}) AS total")["total"]
        right = target.one(f"SELECT ({sql}) AS total")["total"]
        match = left == right
        ok = ok and match
        print(f"  {label:18s} turso={left:>12d} sqlite={right:>12d}  {'OK' if match else 'MISMATCH'}")
    source_settings = {row["key"]: row["value"] for row in source.all("SELECT key,value FROM settings")}
    target_settings = {row["key"]: row["value"] for row in target.all("SELECT key,value FROM settings")}
    settings_match = source_settings == target_settings
    ok = ok and settings_match
    print(f"  settings           {'OK' if settings_match else 'MISMATCH'} "
          f"({len(source_settings)} keys)")
    source_users = [tuple(row) for row in source.all(
        "SELECT user_id,username,display_name,balance,referred_by,verified_at,language "
        "FROM users ORDER BY user_id")]
    target_users = [tuple(row) for row in target.all(
        "SELECT user_id,username,display_name,balance,referred_by,verified_at,language "
        "FROM users ORDER BY user_id")]
    users_match = source_users == target_users
    ok = ok and users_match
    print(f"  users detail       {'OK' if users_match else 'MISMATCH'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=None,
                        help="SQLite file to create (default: backups/rollback-<timestamp>.sqlite3)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite the target file if it exists")
    args = parser.parse_args()

    env_file(str(Path(__file__).with_name(".env")))
    target_path = Path(args.target) if args.target else Path("backups") / (
        "rollback-" + time.strftime("%Y%m%d-%H%M%S") + ".sqlite3")
    if target_path.exists() and not args.force:
        print(f"Target đã tồn tại: {target_path}. Dùng --force để ghi đè.")
        return 2
    if target_path.exists():
        target_path.unlink()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    source = Database("turso", backend="turso")
    if source.backend != "turso":
        print("TURSO_URL/TURSO_TOKEN chưa được thiết lập.")
        source.close()
        return 2
    target = Database(str(target_path), backend="sqlite")
    try:
        print("Turso nguồn:", counts(source))
        copy_all(source, target)
        print("SQLite đích:", counts(target))
        if not verify(source, target):
            print("EXPORT THẤT BẠI: dữ liệu không khớp.")
            return 1
        print(f"EXPORT THÀNH CÔNG: {target_path}")
        print("Rollback:")
        print(f"  ./botctl.sh stop")
        print(f"  ./restore-sqlite.sh {target_path}")
        print(f"  DB_BACKEND=sqlite ./botctl.sh start")
        return 0
    finally:
        target.close()
        source.close()


if __name__ == "__main__":
    sys.exit(main())
