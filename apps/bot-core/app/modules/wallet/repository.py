"""Wallet repository for Bot Core."""
from __future__ import annotations

from app.database.connection import Database


class WalletRepository:
    """Repository for wallet operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def get_balance(self, user_id: int) -> int:
        """Get user wallet balance."""
        user = self.db.fetchone("SELECT balance FROM users WHERE user_id=?", (user_id,))
        return user["balance"] if user else 0
    
    def debit(self, user_id: int, amount: int, reference: str) -> bool:
        """Debit wallet (atomic)."""
        with self.db.transaction():
            cur = self.db.execute(
                "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                (amount, user_id, amount),
            )
            if cur.rowcount == 0:
                return False
            self.db.execute(
                "INSERT INTO ledger(user_id, delta, kind, reference, created_at) VALUES (?,?,?,?,?)",
                (user_id, -amount, "debit", reference, self.db.utcnow()),
            )
            return True
    
    def credit(self, user_id: int, amount: int, kind: str, reference: str) -> bool:
        """Credit wallet (atomic)."""
        if amount <= 0:
            return False
        with self.db.transaction():
            cur = self.db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
            if not cur.rowcount:
                return False
            self.db.execute(
                "INSERT INTO ledger(user_id, delta, kind, reference, created_at) VALUES (?,?,?,?,?)",
                (user_id, amount, kind, reference, self.db.utcnow()),
            )
            return True
    
    def get_ledger(self, user_id: int, limit: int = 20) -> list[dict]:
        """Get user ledger entries."""
        return self.db.fetchall(
            "SELECT * FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )