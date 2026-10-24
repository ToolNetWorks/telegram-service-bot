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