"""Main FastAPI application for Engagement API."""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import db
from app.schemas import (
    PlatformRead, CategoryRead, ProviderServiceRead,
    OrderCreate, OrderResult, OrderStatus,
    PlatformsResponse, CategoriesResponse, ServicesResponse, HealthResponse, ErrorResponse,
)
from app.providers.vietnamfb import vietnamfb_client, VietnamFBError

LOG = logging.getLogger("engagement.api")

# In-memory rate limiting (use Redis in production)
_rate_limit_store: dict[str, list[float]] = {}


def verify_internal_token(request: Request) -> None:
    """Verify internal API token."""
    token = request.headers.get("X-Internal-Token")
    if not token or token != settings.internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )


def check_rate_limit(request: Request) -> None:
    """Simple rate limiting."""
    client_ip = request.client.host if request.client else "unknown"
    now = datetime.now().timestamp()
    window = settings.rate_limit_window

    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = []

    # Clean old entries
    _rate_limit_store[client_ip] = [ts for ts in _rate_limit_store[client_ip] if now - ts < window]

    if len(_rate_limit_store[client_ip]) >= settings.rate_limit_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )

    _rate_limit_store[client_ip].append(now)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    LOG.info("Engagement API starting up...")
    yield
    LOG.info("Engagement API shutting down...")
    db.close()


app = FastAPI(
    title="ToolNet Engagement API",
    description="Internal API for engagement services",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

# CORS for internal services only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add correlation ID to requests."""
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4())[:8])
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.exception_handler(VietnamFBError)
async def vietnamfb_error_handler(request: Request, exc: VietnamFBError):
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content=ErrorResponse(detail=str(exc), correlation_id=getattr(request.state, "correlation_id", None)).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    LOG.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(detail="Internal server error", correlation_id=getattr(request.state, "correlation_id", None)).model_dump(),
    )


# Health check
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    # Check database
    db_status = "disconnected"
    try:
        db.conn.execute("SELECT 1")
        db_status = "connected"
    except Exception:
        pass

    # Check providers
    providers = {}
    try:
        vietnamfb_client.get_balance()
        providers["vietnamfb"] = "ok"
    except Exception:
        providers["vietnamfb"] = "error"

    overall = "healthy" if db_status == "connected" and providers.get("vietnamfb") == "ok" else "degraded"

    return HealthResponse(
        status=overall,
        timestamp=datetime.utcnow(),
        database=db_status,
        database_backend=db.backend,
        providers=providers,
    )


# Platforms
@app.get("/v1/platforms", response_model=PlatformsResponse, dependencies=[Depends(verify_internal_token)], tags=["Platforms"])
async def list_platforms():
    """List all engagement platforms."""
    rows = db.fetchall("SELECT * FROM engagement_platforms WHERE enabled=1 ORDER BY sort_order, id")
    platforms = [PlatformRead.model_validate(dict(row)) for row in rows]
    return PlatformsResponse(platforms=platforms)


@app.get("/v1/platforms/{platform_slug}/categories", response_model=CategoriesResponse, dependencies=[Depends(verify_internal_token)], tags=["Categories"])
async def list_categories(platform_slug: str):
    """List categories for a platform."""
    platform = db.fetchone("SELECT * FROM engagement_platforms WHERE slug=? AND enabled=1", (platform_slug,))
    if not platform:
        raise HTTPException(status_code=404, detail="Platform not found")

    rows = db.fetchall(
        "SELECT * FROM engagement_categories WHERE platform_id=? AND enabled=1 ORDER BY sort_order, id",
        (platform["id"],),
    )
    categories = [CategoryRead.model_validate(dict(row)) for row in rows]
    return CategoriesResponse(categories=categories)


# Services
@app.get("/v1/categories/{category_id}/services", response_model=ServicesResponse, dependencies=[Depends(verify_internal_token)], tags=["Services"])
async def list_services(category_id: int):
    """List provider services for a category."""
    category = db.fetchone("SELECT * FROM engagement_categories WHERE id=? AND enabled=1", (category_id,))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    rows = db.fetchall(
        "SELECT * FROM engagement_provider_services WHERE category_id=? AND status='active' ORDER BY id",
        (category_id,),
    )
    services = [ProviderServiceRead.model_validate(dict(row)) for row in rows]
    return ServicesResponse(services=services)


@app.get("/v1/services/{service_id}", response_model=ProviderServiceRead, dependencies=[Depends(verify_internal_token)], tags=["Services"])
async def get_service(service_id: int):
    """Get a single provider service."""
    row = db.fetchone("SELECT * FROM engagement_provider_services WHERE id=? AND status='active'", (service_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return ProviderServiceRead.model_validate(dict(row))


# Orders
@app.post("/v1/orders", response_model=OrderResult, dependencies=[Depends(verify_internal_token), Depends(check_rate_limit)], tags=["Orders"])
async def create_order(order: OrderCreate):
    """Create an order via provider."""
    # Get service details
    svc = db.fetchone("SELECT * FROM engagement_provider_services WHERE id=? AND status='active'", (order.service_id,))
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    # Check idempotency - use provider_order_id uniqueness (race condition handled by DB constraint)
    # We can't check by idempotency_key since it's not in the shared schema.
    # Instead, Bot Core should ensure idempotency before calling this API.
    
    # Validate quantity
    if order.quantity < svc["min_quantity"] or order.quantity > svc["max_quantity"]:
        raise HTTPException(
            status_code=400,
            detail=f"Quantity must be between {svc['min_quantity']} and {svc['max_quantity']}",
        )

    # Place order with provider
    try:
        if svc["provider_id"] == "vietnamfb":
            result = vietnamfb_client.create_order(
                service_id=svc["provider_service_id"],
                quantity=order.quantity,
                link=order.link,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {svc['provider_id']}")
    except VietnamFBError as exc:
        return OrderResult(success=False, error=str(exc))

    # Store provider order - matches migration 001 schema
    # order_id is NULL initially (Bot Core will link it)
    # api_price_per_1000_milli = rate_milli (cost from provider)
    # markup_percent = 0 (Bot Core applies markup)
    api_price_per_1000_milli = svc["rate_milli"]
    db.execute(
        """INSERT INTO provider_orders(
            order_id, provider_name, provider_service_id, provider_order_id,
            quantity, link, unit_price_milli, markup_percent,
            api_price_per_1000_milli, status, api_response, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            None,  # order_id - Bot Core will link later
            svc["provider_id"],
            svc["provider_service_id"],
            result.order_id,
            order.quantity,
            order.link,
            api_price_per_1000_milli,  # unit_price_milli = provider cost
            0,  # markup_percent
            api_price_per_1000_milli,  # api_price_per_1000_milli
            "processing",
            "{}",  # api_response
            datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat(),
        ),
    )

    return OrderResult(
        success=True,
        provider_order_id=result.order_id,
        charge_milli=int(result.charge * 1000) if result.charge else 0,
        status="processing",
    )


@app.get("/v1/orders/{provider_order_id}/status", response_model=OrderStatus, dependencies=[Depends(verify_internal_token)], tags=["Orders"])
async def get_order_status(provider_order_id: str):
    """Get order status from provider."""
    # Check local cache first
    local = db.fetchone("SELECT * FROM provider_orders WHERE provider_order_id=?", (provider_order_id,))
    if not local:
        raise HTTPException(status_code=404, detail="Order not found")

    # Fetch from provider
    try:
        if local["provider_name"] == "vietnamfb":
            result = vietnamfb_client.get_order_status(provider_order_id)
        else:
            raise HTTPException(status_code=400, detail="Unknown provider")
    except VietnamFBError as exc:
        LOG.warning("Provider status check failed: %s", exc)
        # Return cached status
        return OrderStatus(
            provider_order_id=local["provider_order_id"],
            status=local["status"],
            charge_milli=local["api_price_per_1000_milli"],
        )

    # Update local status
    new_status = result.get("status", local["status"])
    db.execute(
        "UPDATE provider_orders SET status=?, updated_at=?, api_response=? WHERE provider_order_id=?",
        (new_status, datetime.utcnow().isoformat(), str(result), provider_order_id),
    )

    return OrderStatus(
        provider_order_id=provider_order_id,
        status=new_status,
        charge_milli=int(result["charge"] * 1000) if result.get("charge") else local["api_price_per_1000_milli"],
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)