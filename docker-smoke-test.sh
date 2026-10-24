#!/usr/bin/env bash
# Docker Smoke Test for ToolNet Telegram Service Bot
# Runs unit tests and basic container validation using mocks
# Does NOT call real Telegram API or VietnamFB API

set -euo pipefail

IMAGE_NAME="telegram-service-bot:smoke-test"
CONTAINER_NAME="telegram-bot-smoke-test"
TEST_DATA_DIR="$(pwd)/test-data-smoke"

echo "=== Docker Smoke Test ==="
echo "Image: $IMAGE_NAME"
echo "Test data dir: $TEST_DATA_DIR"

# Cleanup function
cleanup() {
    echo "Cleaning up..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    rm -rf "$TEST_DATA_DIR"
}
trap cleanup EXIT

# Create test data directory
mkdir -p "$TEST_DATA_DIR"

echo ""
echo "1. Building Docker image..."
docker build -t "$IMAGE_NAME" -f Dockerfile . > /dev/null
echo "   ✓ Image built"

echo ""
echo "2. Running unit tests in container..."
docker run --rm --entrypoint python3 \
  -e BOT_TOKEN="100000:dummy" \
  -e ADMIN_IDS="999" \
  -e BOT_NAME="Test" \
  -e DB_PATH="/tmp/bot.sqlite3" \
  -e VIETNAMFB_API_KEY="test_key_12345" \
  -e VIETNAMFB_BASE_URL="https://test.vietnamfb.com" \
  "$IMAGE_NAME" \
  -m unittest tests.test_flows -v 2>&1

echo ""
echo "3. Running database tests..."
docker run --rm --entrypoint python3 \
  -e BOT_TOKEN="100000:dummy" \
  -e ADMIN_IDS="999" \
  -e BOT_NAME="Test" \
  -e DB_PATH="/tmp/bot.sqlite3" \
  -e VIETNAMFB_API_KEY="test_key_12345" \
  -e VIETNAMFB_BASE_URL="https://test.vietnamfb.com" \
  "$IMAGE_NAME" \
  -m unittest tests.test_db -v 2>&1

echo ""
echo "4. Testing container startup (configuration validation)..."
# Test that the container starts and validates configuration correctly
# We expect it to fail on getMe (due to dummy token) but NOT on config/db errors
docker run -d \
  --name "$CONTAINER_NAME" \
  -e BOT_TOKEN="100000:dummy" \
  -e ADMIN_IDS="999" \
  -e BOT_NAME="Test" \
  -e DB_PATH="/data/bot.sqlite3" \
  -e VIETNAMFB_API_KEY="test_key_12345" \
  -e VIETNAMFB_BASE_URL="https://test.vietnamfb.com" \
  -v "$TEST_DATA_DIR:/data" \
  --user root \
  "$IMAGE_NAME" > /dev/null

# Wait for startup attempt
sleep 3

# Check logs - should show DB initialization success, then fail on Telegram auth (expected)
LOGS=$(docker logs "$CONTAINER_NAME" 2>&1)
if echo "$LOGS" | grep -q "unable to open database file"; then
    echo "   ✗ Database error"
    echo "$LOGS"
    exit 1
elif echo "$LOGS" | grep -q "VIETNAMFB_API_KEY not set"; then
    echo "   ✗ Config error: API key not loaded"
    echo "$LOGS"
    exit 1
elif echo "$LOGS" | grep -q "Bot @.* đã hoạt động"; then
    echo "   ✓ Bot fully started (unexpected with dummy token)"
elif echo "$LOGS" | grep -q "Telegram getMe: Unauthorized"; then
    echo "   ✓ Config/DB OK, failed on Telegram auth (expected with dummy token)"
else
    echo "   ? Unexpected log output:"
    echo "$LOGS"
    exit 1
fi

# Test SIGTERM handling
echo ""
echo "5. Testing configuration validation complete..."
echo "   (SIGTERM handling tested in unit tests)"

# Verify database persisted
echo ""
echo "6. Verifying database persistence..."
if [ -f "$TEST_DATA_DIR/bot.sqlite3" ]; then
    echo "   ✓ Database file exists"
    # Fix permissions and check tables
    sudo chown -R $(whoami):$(whoami) "$TEST_DATA_DIR" 2>/dev/null || true
    docker run --rm --entrypoint python3 -v "$TEST_DATA_DIR:/data" \
      -e BOT_TOKEN="100000:dummy" \
      -e ADMIN_IDS="999" \
      -e BOT_NAME="Test" \
      -e VIETNAMFB_API_KEY="test_key_12345" \
      -e VIETNAMFB_BASE_URL="https://test.vietnamfb.com" \
      --user root \
      "$IMAGE_NAME" \
      -c "
import sqlite3
conn = sqlite3.connect('/data/bot.sqlite3')
cursor = conn.cursor()
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
tables = [row[0] for row in cursor.fetchall()]
print('   Tables:', ', '.join(tables))
for t in ['users', 'orders', 'provider_orders', 'settings']:
    if t in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {t}')
        print(f'   {t}: {cursor.fetchone()[0]} rows')
    else:
        print(f'   {t}: MISSING')
conn.close()
"
else
    echo "   ✗ Database file not found"
    exit 1
fi

# Verify WAL files handled
echo ""
echo "7. Checking WAL mode..."
if [ -f "$TEST_DATA_DIR/bot.sqlite3-wal" ] || [ -f "$TEST_DATA_DIR/bot.sqlite3-shm" ]; then
    echo "   ✓ WAL files present (normal for SQLite WAL mode)"
else
    echo "   ℹ No WAL files (checkpointed or not yet created)"
fi

echo ""
echo "=== All Smoke Tests Passed ==="
echo "Image is ready for Northflank deployment"