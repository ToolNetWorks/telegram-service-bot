"""ToolNet Engagement API entry point.

This module is intentionally thin: routes live in ``app/api/routes`` and all
provider knowledge lives in ``app/providers``.  It is stateless with respect to
customer/order data; Bot Core owns Turso.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.routes import catalog, health, orders
from app.core.config import settings
from app.core.logging import correlation_id_var, setup_logging
from app.core.runtime import order_service
from app.providers import provider_registry
from app.schemas import ErrorResponse

setup_logging(settings.log_level)
LOG = logging.getLogger("engagement.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    LOG.info(
        "Engagement API starting environment=%s providers=%s",
        settings.environment,
        provider_registry.names(),
    )
    yield
    await provider_registry.close()
    LOG.info("Engagement API stopped")


app = FastAPI(
    title="ToolNet Engagement API",
    description="Internal API for engagement services and provider integration",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()
    if not correlation_id:
        correlation_id = uuid.uuid4().hex[:12]
    token = correlation_id_var.set(correlation_id)
    request.state.correlation_id = correlation_id
    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    LOG.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            detail="Internal server error",
            correlation_id=getattr(request.state, "correlation_id", None),
        ).model_dump(),
    )


app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(orders.router)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
