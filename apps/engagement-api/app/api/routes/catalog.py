"""Versioned catalog endpoints consumed by Bot Core."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.runtime import catalog_service
from app.core.security import verify_internal_token
from app.schemas import (
    CategoriesResponse,
    CategoryRead,
    PlatformsResponse,
    ProviderServiceRead,
    ServicesResponse,
)

router = APIRouter(prefix="/v1", tags=["Catalog"], dependencies=[Depends(verify_internal_token)])


@router.get("/platforms", response_model=PlatformsResponse)
async def list_platforms() -> PlatformsResponse:
    """List all visible platforms, including Coming Soon platforms."""
    return PlatformsResponse(platforms=catalog_service.list_platforms())


@router.get("/platforms/{platform_slug}/categories", response_model=CategoriesResponse)
async def list_categories(platform_slug: str) -> CategoriesResponse:
    categories = catalog_service.list_categories(platform_slug)
    if categories is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform not found")
    return CategoriesResponse(categories=categories)


@router.get("/categories/{category_id}", response_model=CategoryRead)
async def get_category(category_id: int) -> CategoryRead:
    """Category metadata endpoint used by Bot Core for back-navigation."""
    category = catalog_service.get_category(category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


@router.get("/categories/{category_id}/services", response_model=ServicesResponse)
async def list_services(category_id: int) -> ServicesResponse:
    services = await catalog_service.list_services(category_id)
    if services is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return ServicesResponse(services=services)


@router.get("/services/{service_id}", response_model=ProviderServiceRead)
async def get_service(service_id: int) -> ProviderServiceRead:
    service = await catalog_service.get_service(service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return service
