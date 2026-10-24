#!/usr/bin/env bash
# Bot Control Script for VPS
# Manages the production bot process

set -euo pipefail

BOT_DIR="/home/ubuntu/telegram-service-bot"
PID_FILE="$BOT_DIR/data/bot.pid"
LOG_FILE="$BOT_DIR/logs/bot.log"

cd "$BOT_DIR"

case "${1:-}" in
    start)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo "Bot already running (PID: $PID)"
                exit 1
            else
                echo "Stale PID file, removing..."
                rm -f "$PID_FILE"
            fi
        fi
        echo "Starting bot..."
        setsid nohup python3 -m bot >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "Bot started (PID: $(cat $PID_FILE))"
            tail -5 "$LOG_FILE"
        else
            echo "Failed to start bot"
            tail -20 "$LOG_FILE"
            exit 1
        fi
        ;;
    stop)
        if [ ! -f "$PID_FILE" ]; then
            echo "PID file not found"
            exit 1
        fi
        PID=$(cat "$PID_FILE")
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "Bot not running (stale PID)"
            rm -f "$PID_FILE"
            exit 1
        fi
        echo "Stopping bot (PID: $PID)..."
        kill -TERM "$PID"
        # Wait for graceful shutdown
        for i in {1..30}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                echo "Bot stopped gracefully"
                rm -f "$PID_FILE"
                exit 0
            fi
            sleep 1
        done
        echo "Force killing..."
        kill -9 "$PID" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "Bot force stopped"
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo "Bot RUNNING (PID: $PID)"
                ps -p "$PID" -o pid,ppid,cmd,etime
                exit 0
            fi
        fi
        echo "Bot STOPPED"
        exit 1
        ;;
    logs)
        tail -f "$LOG_FILE"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac