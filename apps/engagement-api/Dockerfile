# ToolNet Engagement API - Production Dockerfile
# Build context: repository root (/)
# Dockerfile location: apps/engagement-api/Dockerfile

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r apiuser && useradd -r -g apiuser apiuser

# Set working directory
WORKDIR /app

# Copy Python dependencies first (for better cache)
COPY apps/engagement-api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY apps/engagement-api/ /app/

# Create data directory for SQLite (if used)
RUN mkdir -p /data && chown -R apiuser:apiuser /data /app

# Switch to non-root user
USER apiuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/engagement.sqlite3

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the API
ENTRYPOINT ["python3", "app/main.py"]