"""Engagement services repository for Bot Core."""
from __future__ import annotations

from app.database.connection import Database


class EngagementRepository:
    """Repository for engagement platform/category/service operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    # Platforms
    def list_platforms(self, enabled_only: bool = True) -> list[dict]:
        """List all engagement platforms."""
        sql = "SELECT * FROM engagement_platforms"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY sort_order, id"
        return self.db.fetchall(sql)
    
    def get_platform(self, platform_id: int) -> dict | None:
        return self.db.fetchone("SELECT * FROM engagement_platforms WHERE id=?", (platform_id,))
    
    def get_platform_by_slug(self, slug: str) -> dict | None:
        return self.db.fetchone("SELECT * FROM engagement_platforms WHERE slug=?", (slug,))
    
    # Categories
    def list_categories(self, platform_id: int, enabled_only: bool = True) -> list[dict]:
        """List service categories for a platform."""
        sql = "SELECT * FROM engagement_categories WHERE platform_id=?"
        params = [platform_id]
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY sort_order, id"
        return self.db.fetchall(sql, tuple(params))
    
    def get_category(self, category_id: int) -> dict | None:
        return self.db.fetchone("SELECT * FROM engagement_categories WHERE id=?", (category_id,))
    
    def get_category_by_slug(self, platform_id: int, slug: str) -> dict | None:
        return self.db.fetchone(
            "SELECT * FROM engagement_categories WHERE platform_id=? AND slug=?",
            (platform_id, slug),
        )
    
    # Provider Services
    def list_provider_services(self, category_id: int, enabled_only: bool = True) -> list[dict]:
        """List provider services for a category."""
        sql = "SELECT * FROM engagement_provider_services WHERE category_id=?"
        params = [category_id]
        if enabled_only:
            sql += " AND status='active'"
        sql += " ORDER BY id"
        return self.db.fetchall(sql, tuple(params))
    
    def get_provider_service(self, service_id: int) -> dict | None:
        return self.db.fetchone("SELECT * FROM engagement_provider_services WHERE id=?", (service_id,))
    
    def get_provider_service_by_provider_id(self, provider_id: str, provider_service_id: str) -> dict | None:
        return self.db.fetchone(
            "SELECT * FROM engagement_provider_services WHERE provider_id=? AND provider_service_id=?",
            (provider_id, provider_service_id),
        )