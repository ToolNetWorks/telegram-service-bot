# ToolNet Bot Core - Production Dockerfile
# Build context: repository root (/)
# Dockerfile location: apps/bot-core/Dockerfile

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Set working directory
WORKDIR /app

# Copy Python dependencies first (for better cache)
COPY apps/bot-core/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and the shared Turso transport
COPY apps/bot-core/ /app/
COPY turso_client.py /app/turso_client.py
COPY assets/ /app/assets/

# Create data directory for SQLite (if used)
RUN mkdir -p /data && chown -R botuser:botuser /data /app

# Switch to non-root user
USER botuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/bot.sqlite3

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python3 -c "import sys; sys.path.insert(0, '.'); from healthcheck import main; sys.exit(main())"

# Run the bot
ENTRYPOINT ["python3", "bot.py"]