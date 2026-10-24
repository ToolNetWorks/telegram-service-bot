#!/usr/bin/env bash
# Safe SQLite Backup with WAL Support
# Creates consistent backup including WAL checkpoint

set -euo pipefail

DB_PATH="${1:-/home/ubuntu/telegram-service-bot/data/bot.sqlite3}"
BACKUP_DIR="${2:-/home/ubuntu/telegram-service-bot/backups}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/bot.sqlite3.${TIMESTAMP}.backup"

echo "=== SQLite Backup ==="
echo "Source: $DB_PATH"
echo "Backup: $BACKUP_FILE"

mkdir -p "$BACKUP_DIR"

# Check if database exists
if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: Database not found at $DB_PATH"
    exit 1
fi

# Method 1: SQLite .backup command (handles WAL automatically)
echo "Creating backup using SQLite .backup command..."
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

# Verify backup
if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not created"
    exit 1
fi

# Verify backup integrity
echo "Verifying backup integrity..."
sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" | grep -q "ok" || {
    echo "ERROR: Backup integrity check failed"
    exit 1
}

# Get backup size
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup size: $BACKUP_SIZE"

# Also create a compressed archive with WAL/SHM files for full state
ARCHIVE_FILE="${BACKUP_DIR}/bot-data.${TIMESTAMP}.tar.gz"
echo "Creating full state archive (includes WAL/SHM)..."
tar -czf "$ARCHIVE_FILE" -C "$(dirname "$DB_PATH")" "$(basename "$DB_PATH")" "$(basename "$DB_PATH")-wal" "$(basename "$DB_PATH")-shm" 2>/dev/null || true

ARCHIVE_SIZE=$(du -h "$ARCHIVE_FILE" | cut -f1)
echo "Archive size: $ARCHIVE_SIZE"

# Cleanup old backups (keep last 7 days)
echo "Cleaning old backups (>7 days)..."
find "$BACKUP_DIR" -name "bot.sqlite3.*.backup" -mtime +7 -delete
find "$BACKUP_DIR" -name "bot-data.*.tar.gz" -mtime +7 -delete

echo ""
echo "=== Backup Complete ==="
echo "Main backup: $BACKUP_FILE"
echo "Full archive: $ARCHIVE_FILE"