"""Provider order endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.rate_limit import check_rate_limit
from app.core.runtime import order_service
from app.core.security import verify_internal_token
from app.providers.base import ProviderError
from app.schemas import OrderCreate, OrderResult, OrderStatus
from app.services.orders import (
    DuplicateInFlightError,
    InvalidQuantityError,
    ProviderUnavailableError,
    ServiceNotFoundError,
)

router = APIRouter(prefix="/v1/orders", tags=["Orders"])


@router.post(
    "",
    response_model=OrderResult,
    dependencies=[Depends(verify_internal_token), Depends(check_rate_limit)],
)
async def create_order(order: OrderCreate) -> OrderResult:
    """Create a provider order.

    Durable idempotency is enforced by Bot Core's ``orders.request_key`` unique
    constraint before this endpoint is called.  This endpoint additionally
    rejects the same idempotency key while a request is in flight.
    """
    try:
        return await order_service.create_order(order)
    except ServiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidQuantityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DuplicateInFlightError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ProviderError as exc:
        # Provider errors are normally converted to OrderResult by the service.
        # This is a last-resort guard for provider-specific errors.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.message,
        ) from exc


@router.get(
    "/{provider_order_id}/status",
    response_model=OrderStatus,
    dependencies=[Depends(verify_internal_token)],
)
async def get_order_status(
    provider_order_id: str,
    provider: str = Query(default="vietnamfb", min_length=1, max_length=50),
) -> OrderStatus:
    """Read order status directly from the provider (no local order storage)."""
    try:
        return await order_service.get_status(provider_order_id, provider)
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.message,
        ) from exc
