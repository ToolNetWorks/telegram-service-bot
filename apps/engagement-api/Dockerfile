# ToolNet Engagement API - Production Dockerfile
# Build context: repository root (/)
# Dockerfile location: apps/engagement-api/Dockerfile

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r apiuser && useradd -r -g apiuser apiuser

WORKDIR /app

COPY apps/engagement-api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Stateless service: no Turso client and no local database are copied.
COPY apps/engagement-api/ /app/

RUN chown -R apiuser:apiuser /app
USER apiuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

ENTRYPOINT ["python3", "-m", "app.main"]
