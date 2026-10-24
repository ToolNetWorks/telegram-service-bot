#!/usr/bin/env python3
"""Copy the local SQLite snapshot into Turso without losing any history.

Safety rules:
  * Always creates a WAL-safe backup of the source first.
  * Refuses to touch a non-empty Turso database unless ``--replace --yes``.
  * Preserves IDs, wallets, referrals, orders, provider orders, deposits,
    ledger, tickets and settings.
  * Verifies row counts, money sums and settings after copying.

The local SQLite file is never deleted or modified.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys
import time

from bot import env_file
from db import Database

TABLES = [
    ("services", ["id", "title", "description", "price", "enabled", "platform"]),
    ("users", ["user_id", "username", "display_name", "balance", "referred_by",
               "state", "state_data", "created_at", "verified_at", "language"]),
    ("orders", ["id", "user_id", "service_id", "request_key", "subject",
                "evidence_kind", "evidence", "amount", "paid", "status",
                "created_at", "updated_at"]),
    ("provider_orders", ["id", "order_id", "provider_name", "provider_service_id",
                         "provider_order_id", "quantity", "link",
                         "unit_price_milli", "markup_percent",
                         "api_price_per_1000_milli", "status", "api_response",
                         "created_at", "updated_at"]),
    ("deposits", ["id", "user_id", "amount", "status", "proof_kind", "proof",
                  "created_at", "updated_at"]),
    ("ledger", ["id", "user_id", "delta", "kind", "reference", "created_at"]),
    ("tickets", ["id", "user_id", "message", "status", "created_at"]),
    ("settings", ["key", "value"]),
]

DELETE_ORDER = ["provider_orders", "ledger", "deposits", "orders",
                "tickets", "users", "services", "settings"]


def sqlite_backup(source: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"pre-turso-{stamp}.sqlite3"
    src = sqlite3.connect(str(source), timeout=30)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if integrity != "ok":
        raise RuntimeError(f"Backup integrity check failed: {integrity}")
    return target


def source_counts(source: sqlite3.Connection):
    return {table: source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table, _ in TABLES}


def target_counts(db: Database):
    return {table: db.one(f"SELECT COUNT(*) c FROM {table}")["c"]
            for table, _ in TABLES}


def print_counts(title: str, counts):
    print(title)
    for table, _ in TABLES:
        print(f"  {table:16s} {counts[table]:>8d}")


def confirm_replace(args):
    if not args.replace:
        return
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise SystemExit("--replace yêu cầu --yes khi chạy không tương tác")
    print("CẢNH BÁO: --replace sẽ xoá toàn bộ dữ liệu nghiệp vụ trên Turso "
          "trước khi copy snapshot SQLite.")
    answer = input("Nhập REPLACE để tiếp tục: ").strip()
    if answer != "REPLACE":
        raise SystemExit("Đã hủy")


def wipe_target(db: Database):
    with db.transaction():
        db.conn.execute("UPDATE users SET referred_by=NULL")
        for table in DELETE_ORDER:
            db.conn.execute(f"DELETE FROM {table}")


def copy_table(db: Database, table: str, columns, rows):
    if not rows:
        return
    placeholders = ",".join("?" for _ in columns)
    quoted = ",".join(columns)
    sql = f"INSERT OR REPLACE INTO {table}({quoted}) VALUES ({placeholders})"
    prepared = []
    for row in rows:
        values = list(row)
        if table == "users":
            idx = columns.index("referred_by")
            values[idx] = None  # self-FK: fill after all users exist
        prepared.append(tuple(values))
    db.conn.executemany(sql, prepared)


def copy_all(source: sqlite3.Connection, db: Database):
    rows_by_table = {}
    for table, columns in TABLES:
        order = {"settings": "key", "users": "user_id"}.get(table, "id")
        sql = f"SELECT {','.join(columns)} FROM {table} ORDER BY {order}"
        rows_by_table[table] = source.execute(sql).fetchall()
        copy_table(db, table, columns, rows_by_table[table])
    refs = [(row[0], row[4]) for row in rows_by_table["users"] if row[4] is not None]
    if refs:
        with db.transaction():
            for user_id, referred_by in refs:
                db.conn.execute("UPDATE users SET referred_by=? WHERE user_id=?",
                                (referred_by, user_id))


def verify(source: sqlite3.Connection, db: Database) -> bool:
    ok = True
    source_n = source_counts(source)
    target_n = target_counts(db)
    print("Xác minh số bản ghi:")
    for table, _ in TABLES:
        match = source_n[table] == target_n[table]
        ok = ok and match
        mark = "OK" if match else "MISMATCH"
        print(f"  {table:16s} sqlite={source_n[table]:>8d} turso={target_n[table]:>8d}  {mark}")

    scalar_checks = [
        ("users.balance", "SELECT COALESCE(SUM(balance),0) FROM users"),
        ("ledger.delta", "SELECT COALESCE(SUM(delta),0) FROM ledger"),
        ("orders.amount", "SELECT COALESCE(SUM(amount),0) FROM orders"),
        ("deposits.amount", "SELECT COALESCE(SUM(amount),0) FROM deposits"),
        ("provider.quantity", "SELECT COALESCE(SUM(quantity),0) FROM provider_orders"),
    ]
    print("Xác minh tổng tiền:")
    for label, sql in scalar_checks:
        left = source.execute(sql).fetchone()[0]
        right = db.one(f"SELECT ({sql}) AS total")["total"]
        match = left == right
        ok = ok and match
        print(f"  {label:18s} sqlite={left:>12d} turso={right:>12d}  {'OK' if match else 'MISMATCH'}")

    source_settings = dict(source.execute("SELECT key,value FROM settings").fetchall())
    target_settings = {row["key"]: row["value"] for row in db.all("SELECT key,value FROM settings")}
    settings_match = source_settings == target_settings
    ok = ok and settings_match
    print(f"  settings           {'OK' if settings_match else 'MISMATCH'} "
          f"({len(source_settings)} keys)")

    source_services = source.execute(
        "SELECT id,title,price,enabled,platform FROM services ORDER BY id").fetchall()
    target_services = [tuple(row) for row in db.all(
        "SELECT id,title,price,enabled,platform FROM services ORDER BY id")]
    services_match = [tuple(row) for row in source_services] == target_services
    ok = ok and services_match
    print(f"  services detail    {'OK' if services_match else 'MISMATCH'}")

    source_users = source.execute(
        "SELECT user_id,username,display_name,balance,referred_by,verified_at,language "
        "FROM users ORDER BY user_id").fetchall()
    target_users = [tuple(row) for row in db.all(
        "SELECT user_id,username,display_name,balance,referred_by,verified_at,language "
        "FROM users ORDER BY user_id")]
    users_match = [tuple(row) for row in source_users] == target_users
    ok = ok and users_match
    print(f"  users detail       {'OK' if users_match else 'MISMATCH'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="data/bot.sqlite3",
                        help="SQLite database to copy (default: data/bot.sqlite3)")
    parser.add_argument("--backup-dir", default="backups",
                        help="Directory for the pre-migration backup")
    parser.add_argument("--replace", action="store_true",
                        help="Wipe business tables on Turso before copying")
    parser.add_argument("--yes", action="store_true",
                        help="Non-interactive confirmation for --replace")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print source counts only; no write to Turso")
    parser.add_argument("--verify-only", action="store_true",
                        help="Compare existing Turso data with SQLite; no writes")
    args = parser.parse_args()

    env_file(str(Path(__file__).with_name(".env")))
    if args.replace and not args.yes:
        confirm_replace(args)

    source_path = Path(args.source).resolve()
    if not source_path.is_file():
        print(f"Không tìm thấy SQLite: {source_path}")
        return 2

    if args.dry_run:
        source = sqlite3.connect(str(source_path))
        print_counts("SQLite (dry-run):", source_counts(source))
        source.close()
        return 0

    backup = None if args.verify_only else sqlite_backup(source_path, Path(args.backup_dir))
    if backup:
        print(f"Đã backup SQLite: {backup}")

    source = sqlite3.connect(str(backup) if backup else str(source_path))
    source.row_factory = sqlite3.Row
    try:
        if not args.verify_only:
            print_counts("SQLite nguồn:", source_counts(source))
        db = Database("turso")
        if db.backend != "turso":
            print("TURSO_URL/TURSO_TOKEN chưa được thiết lập; không migrate.")
            db.close()
            return 2
        try:
            if args.verify_only:
                return 0 if verify(source, db) else 1
            current = target_counts(db)
            business_nonempty = any(current[t] for t in
                                    ("users", "orders", "provider_orders", "deposits",
                                     "ledger", "tickets"))
            if business_nonempty and not args.replace:
                print("Turso đã có dữ liệu nghiệp vụ. Dùng --replace --yes để ghi đè.")
                return 2
            if args.replace:
                wipe_target(db)
            copy_all(source, db)
            print_counts("Turso sau migrate:", target_counts(db))
            if not verify(source, db):
                print("MIGRATE THẤT BẠI: dữ liệu không khớp. SQLite gốc vẫn nguyên vẹn.")
                return 1
            print("MIGRATE THÀNH CÔNG: Turso khớp với SQLite.")
            return 0
        finally:
            db.close()
    finally:
        source.close()


if __name__ == "__main__":
    sys.exit(main())
