"""Settings repository for Bot Core."""
from __future__ import annotations

from app.database.connection import Database


class SettingsRepository:
    """Repository for settings operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def get(self, key: str) -> str:
        row = self.db.fetchone("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else ""
    
    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    
    def get_markup_percent(self) -> int:
        val = self.get("provider_markup_percent")
        try:
            return max(0, int(val))
        except (ValueError, TypeError):
            return 100
    
    def set_markup_percent(self, percent: int) -> bool:
        if percent < 0:
            return False
        self.set("provider_markup_percent", str(percent))
        return True
    
    def get_banner(self) -> tuple[str, str] | None:
        kind = self.get("banner_kind")
        file_id = self.get("banner_id")
        if kind and file_id:
            return kind, file_id
        return None
    
    def set_banner(self, kind: str, file_id: str) -> None:
        self.set("banner_kind", kind)
        self.set("banner_id", file_id)
    
    def get_poll_offset(self) -> int:
        val = self.get("poll_offset")
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0
    
    def set_poll_offset(self, offset: int) -> None:
        self.set("poll_offset", str(offset))