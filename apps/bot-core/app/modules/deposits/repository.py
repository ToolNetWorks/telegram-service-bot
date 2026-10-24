"""Deposits repository for Bot Core."""
from __future__ import annotations

from app.database.connection import Database


class DepositRepository:
    """Repository for deposit operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def create(self, user_id: int, amount: int) -> dict | None:
        """Create a new deposit request."""
        if amount < 10000 or amount > 100000000:
            return None
        with self.db.transaction():
            # Check pending deposit limit
            count = self.db.fetchone(
                "SELECT COUNT(*) c FROM deposits WHERE user_id=? AND status IN ('waiting_proof','pending')",
                (user_id,)
            )["c"]
            if count >= 3:
                return None
            
            cur = self.db.execute(
                "INSERT INTO deposits(user_id, amount, status, created_at, updated_at) VALUES (?,?,?,?,?)",
                (user_id, amount, "waiting_proof", self.db.utcnow(), self.db.utcnow()),
            )
            return self.db.fetchone("SELECT * FROM deposits WHERE id=?", (cur.lastrowid,))
    
    def submit_proof(self, deposit_id: int, user_id: int, kind: str, proof: str) -> dict | None:
        """Submit proof for a deposit."""
        with self.db.transaction():
            cur = self.db.execute(
                "UPDATE deposits SET proof_kind=?, proof=?, status='pending', updated_at=? "
                "WHERE id=? AND user_id=? AND status='waiting_proof'",
                (kind, proof, self.db.utcnow(), deposit_id, user_id),
            )
            return self.db.fetchone("SELECT * FROM deposits WHERE id=?", (deposit_id,)) if cur.rowcount else None
    
    def approve(self, deposit_id: int) -> dict | None:
        """Approve a deposit (admin action)."""
        with self.db.transaction():
            dep = self.db.fetchone("SELECT * FROM deposits WHERE id=?", (deposit_id,))
            if not dep or dep["status"] != "pending":
                return None
            
            self.db.execute(
                "UPDATE deposits SET status='approved', updated_at=? WHERE id=?",
                (self.db.utcnow(), deposit_id),
            )
            self.db.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (dep["amount"], dep["user_id"]),
            )
            self.db.execute(
                "INSERT INTO ledger(user_id, delta, kind, reference, created_at) VALUES (?,?,?,?,?)",
                (dep["user_id"], dep["amount"], "deposit", str(deposit_id), self.db.utcnow()),
            )
            return self.db.fetchone("SELECT * FROM deposits WHERE id=?", (deposit_id,))
    
    def reject(self, deposit_id: int) -> dict | None:
        """Reject a deposit (admin action)."""
        with self.db.transaction():
            dep = self.db.fetchone("SELECT * FROM deposits WHERE id=?", (deposit_id,))
            if not dep or dep["status"] != "pending":
                return None
            self.db.execute(
                "UPDATE deposits SET status='rejected', updated_at=? WHERE id=?",
                (self.db.utcnow(), deposit_id),
            )
            return self.db.fetchone("SELECT * FROM deposits WHERE id=?", (deposit_id,))
    
    def cancel(self, deposit_id: int, user_id: int) -> bool:
        """Cancel a deposit (user action)."""
        with self.db.transaction():
            cur = self.db.execute(
                "UPDATE deposits SET status='cancelled', updated_at=? "
                "WHERE id=? AND user_id=? AND status='waiting_proof'",
                (self.db.utcnow(), deposit_id, user_id),
            )
            return cur.rowcount == 1
    
    def list_user_deposits(self, user_id: int) -> list[dict]:
        """List user's deposits."""
        return self.db.fetchall(
            "SELECT id, amount, status FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (user_id,),
        )
    
    def list_pending_deposits(self) -> list[dict]:
        """List all pending deposits (admin)."""
        return self.db.fetchall(
            "SELECT id, user_id, amount, status FROM deposits WHERE status='pending' ORDER BY id DESC LIMIT 20"
        )