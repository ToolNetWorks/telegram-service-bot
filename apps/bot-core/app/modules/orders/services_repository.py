"""Services catalog repository for Bot Core."""
from __future__ import annotations

from app.database.connection import Database


class ServicesRepository:
    """Repository for services catalog operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def list(self, platform: str | None = None) -> list[dict]:
        if platform is None:
            return self.db.fetchall("SELECT * FROM services WHERE enabled=1 ORDER BY id")
        return self.db.fetchall("SELECT * FROM services WHERE enabled=1 AND platform=? ORDER BY id", (platform,))
    
    def get(self, service_id: int) -> dict | None:
        return self.db.fetchone("SELECT * FROM services WHERE id=? AND enabled=1", (service_id,))
    
    def get_by_title(self, title: str) -> dict | None:
        return self.db.fetchone("SELECT * FROM services WHERE title=?", (title,))
    
    def set_price(self, service_id: int, price: int) -> bool:
        if price < 0:
            return False
        return self.db.execute("UPDATE services SET price=? WHERE id=?", (price, service_id)).rowcount == 1

    def get_or_create_engagement_service(self, name: str, provider_id: str, provider_service_id: str) -> dict:
        """Return a local label row for an Engagement API service.

        ``orders.service_id`` is a foreign key into the local ``services`` table
        (Bot Core owns orders).  The provider service identity itself is stored
        in ``provider_orders``; this row only provides a stable local label.
        """
        title = f"Engagement · {name}"[:120]
        existing = self.db.fetchone("SELECT * FROM services WHERE title=?", (title,))
        if existing:
            return existing

        with self.db.transaction():
            self.db.execute(
                "INSERT OR IGNORE INTO services(title, description, price, platform, enabled) "
                "VALUES (?,?,?,?,?)",
                (title, f"{provider_id}:{provider_service_id}", 0, "engagement", 1),
            )
        row = self.db.fetchone("SELECT * FROM services WHERE title=?", (title,))
        if row is None:
            raise RuntimeError("Unable to create local engagement service label")
        return row