#!/usr/bin/env bash
# SQLite Restore Script for Northflank Volume
# Restores from backup created by backup-sqlite.sh

set -euo pipefail

BACKUP_FILE="${1:-}"
DB_PATH="${2:-/home/ubuntu/telegram-service-bot/data/bot.sqlite3}"

if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup-file> [target-db-path]"
    echo "Example: $0 /data/backups/bot.sqlite3.20261024-120000.backup /data/bot.sqlite3"
    exit 1
fi

echo "=== SQLite Restore ==="
echo "Backup: $BACKUP_FILE"
echo "Target: $DB_PATH"

# Verify backup integrity first
echo "Verifying backup integrity..."
sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" | grep -q "ok" || {
    echo "ERROR: Backup integrity check failed"
    exit 1
}

# Stop bot if running (check for PID file)
PID_FILE="$(dirname "$DB_PATH")/bot.pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Bot process $PID is running. Please stop it first:"
        echo "  kill -TERM $PID"
        echo "  Wait for process to exit"
        exit 1
    fi
fi

# Backup current database (just in case)
if [ -f "$DB_PATH" ]; then
    CURRENT_BACKUP="${DB_PATH}.pre-restore.$(date +%Y%m%d-%H%M%S)"
    echo "Backing up current database to $CURRENT_BACKUP"
    cp "$DB_PATH" "$CURRENT_BACKUP"
    # Also backup WAL/SHM if exist
    [ -f "${DB_PATH}-wal" ] && cp "${DB_PATH}-wal" "${CURRENT_BACKUP}-wal"
    [ -f "${DB_PATH}-shm" ] && cp "${DB_PATH}-shm" "${CURRENT_BACKUP}-shm"
fi

# Restore using SQLite .restore (not available) or copy
echo "Restoring database..."
cp "$BACKUP_FILE" "$DB_PATH"

# Remove WAL/SHM files to force fresh start
rm -f "${DB_PATH}-wal" "${DB_PATH}-shm"

# Verify restored database
echo "Verifying restored database..."
sqlite3 "$DB_PATH" "PRAGMA integrity_check;" | grep -q "ok" || {
    echo "ERROR: Restored database integrity check failed"
    exit 1
}

# Check key tables
echo "Checking key tables..."
sqlite3 "$DB_PATH" "
SELECT 'users: ' || COUNT(*) FROM users;
SELECT 'orders: ' || COUNT(*) FROM orders;
SELECT 'provider_orders: ' || COUNT(*) FROM provider_orders;
SELECT 'settings: ' || COUNT(*) FROM settings;
"

echo ""
echo "=== Restore Complete ==="
echo "Database restored to $DB_PATH"
echo "Start the bot to continue"