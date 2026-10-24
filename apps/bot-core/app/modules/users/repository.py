"""User repository for Bot Core."""
from __future__ import annotations

from app.database.connection import Database


class UserRepository:
    """Repository for user operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def ensure_user(self, user_id: int, username: str, display_name: str, referral: int | None = None) -> None:
        """Create or update user."""
        if referral == user_id or not self.db.fetchone("SELECT 1 FROM users WHERE user_id=?", (referral,)):
            referral = None
        with self.db.transaction():
            self.db.execute(
                "INSERT OR IGNORE INTO users(user_id, username, display_name, referred_by, created_at) "
                "VALUES (?,?,?,?,?)",
                (user_id, username, display_name, referral, self.db.utcnow()),
            )
            self.db.execute(
                "UPDATE users SET username=?, display_name=? WHERE user_id=?",
                (username, display_name, user_id),
            )
    
    def get_user(self, user_id: int) -> dict | None:
        """Get user by ID."""
        return self.db.fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
    
    def verify_user(self, user_id: int) -> None:
        """Mark user as verified."""
        self.db.execute(
            "UPDATE users SET verified_at=?, state='', state_data='{}' WHERE user_id=?",
            (self.db.utcnow(), user_id),
        )
    
    def set_language(self, user_id: int, language: str) -> bool:
        """Set user language."""
        valid_languages = {"vi", "en", "ru", "ar", "fa", "es", "pt", "de", "fr", "hi", "id"}
        if language not in valid_languages:
            return False
        return self.db.execute(
            "UPDATE users SET language=? WHERE user_id=?",
            (language, user_id),
        ).rowcount == 1
    
    def get_referral_count(self, user_id: int) -> int:
        """Get number of referrals for a user."""
        return self.db.fetchone("SELECT COUNT(*) c FROM users WHERE referred_by=?", (user_id,))["c"]