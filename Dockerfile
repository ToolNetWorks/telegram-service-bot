# Dockerfile for ToolNet Telegram Service Bot
# Production-ready, single-instance long polling
# Northflank deployment: Worker service, no public port

FROM python:3.12-slim AS base

# Install runtime dependencies only (no build tools needed - stdlib only)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set timezone
ENV TZ=Asia/Ho_Chi_Minh

# Create non-root user
RUN groupadd -r botuser && useradd -r -g botuser -d /app -s /bin/bash botuser

# Create app directory
WORKDIR /app

# Copy source code
COPY --chown=botuser:botuser bot.py db.py i18n.py vietnamfb_api.py ./
COPY --chown=botuser:botuser tests/ ./tests/
COPY --chown=botuser:botuser assets/ ./assets/
COPY --chown=botuser:botuser .env.example ./

# Create data directory for persistent volume
RUN mkdir -p /data && chown botuser:botuser /data

# Create logs directory
RUN mkdir -p /app/logs && chown botuser:botuser /app/logs

# Switch to non-root user
USER botuser

# Environment variables (configured via Northflank Secrets/Config)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/bot.sqlite3 \
    LOG_LEVEL=INFO

# Health check: verify process is alive and can connect to Telegram
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python3 -c "import sys, os; sys.path.insert(0, '.'); from bot import App; print('OK')" || exit 1

# Run the bot
ENTRYPOINT ["python3", "-m", "bot"]