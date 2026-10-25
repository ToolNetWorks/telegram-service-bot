"""Orders repository for Bot Core."""
from __future__ import annotations

from app.database.connection import Database


class OrderRepository:
    """Repository for order operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def count_active_orders(self, user_id: int) -> int:
        """Count user's active orders."""
        return self.db.fetchone(
            "SELECT COUNT(*) c FROM orders WHERE user_id=? AND status IN "
            "('awaiting_quote','awaiting_payment','pending_review','processing','pending_reconciliation')",
            (user_id,),
        )["c"]
    
    def create(
        self,
        user_id: int,
        service_id: int,
        subject: str,
        kind: str,
        evidence: str,
        request_key: str,
    ) -> dict | None:
        """Create a new order (idempotent by request_key)."""
        with self.db.transaction():
            existing = self.db.fetchone("SELECT * FROM orders WHERE request_key=?", (request_key,))
            if existing:
                return existing
            
            service = self.db.fetchone("SELECT * FROM services WHERE id=? AND enabled=1", (service_id,))
            if not service:
                return None
            
            if self.count_active_orders(user_id) >= 5:
                return None
            
            price = int(service["price"])
            status = "awaiting_quote" if price == 0 else "awaiting_payment"
            
            cur = self.db.execute(
                "INSERT INTO orders(user_id, service_id, request_key, subject, evidence_kind, evidence, amount, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (user_id, service_id, request_key, subject, kind, evidence, price, status, self.db.utcnow(), self.db.utcnow()),
            )
            return self.db.fetchone("SELECT * FROM orders WHERE id=?", (cur.lastrowid,))
    
    def get(self, order_id: int) -> dict | None:
        """Get order by ID with service info."""
        return self.db.fetchone(
            "SELECT o.*, s.title service_name FROM orders o LEFT JOIN services s ON s.id=o.service_id WHERE o.id=?",
            (order_id,),
        )
    
    def get_provider_order(self, order_id: int) -> dict | None:
        """Get provider order details."""
        return self.db.fetchone(
            "SELECT po.*, o.user_id, o.amount, o.status as order_status FROM provider_orders po "
            "JOIN orders o ON o.id=po.order_id WHERE po.order_id=?",
            (order_id,),
        )

    def find_by_request_key(self, request_key: str) -> dict | None:
        return self.db.fetchone("SELECT * FROM orders WHERE request_key=?", (request_key,))
    
    def pay(self, order_id: int, user_id: int) -> str:
        """Pay for an order from wallet."""
        with self.db.transaction():
            order = self.get(order_id)
            if not order or order["user_id"] != user_id:
                return "missing"
            if order["status"] == "pending_review" and order["paid"]:
                return "already_paid"
            if order["status"] != "awaiting_payment" or order["paid"] or order["amount"] <= 0:
                return "not_payable"
            
            cur = self.db.execute(
                "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                (order["amount"], user_id, order["amount"]),
            )
            if cur.rowcount == 0:
                return "insufficient"
            
            self.db.execute(
                "UPDATE orders SET paid=1, status='pending_review', updated_at=? WHERE id=?",
                (self.db.utcnow(), order_id),
            )
            self.db.execute(
                "INSERT INTO ledger(user_id, delta, kind, reference, created_at) VALUES (?,?,?,?,?)",
                (user_id, -order["amount"], "order_payment", str(order_id), self.db.utcnow()),
            )
            return "paid"
    
    def quote(self, order_id: int, amount: int) -> dict | None:
        """Set quote amount for an order."""
        if amount <= 0:
            return None
        with self.db.transaction():
            cur = self.db.execute(
                "UPDATE orders SET amount=?, status='awaiting_payment', updated_at=? "
                "WHERE id=? AND status='awaiting_quote' AND paid=0",
                (amount, self.db.utcnow(), order_id),
            )
            return self.get(order_id) if cur.rowcount else None
    
    def set_status(self, order_id: int, next_status: str) -> dict | None:
        """Update order status with validation."""
        transitions = {
            "processing": ("pending_review", "pending_reconciliation"),
            "completed": ("processing",),
        }
        if next_status not in transitions:
            return None
        with self.db.transaction():
            order = self.get(order_id)
            if not order or order["status"] not in transitions[next_status]:
                return None
            self.db.execute(
                "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                (next_status, self.db.utcnow(), order_id),
            )
            return self.get(order_id)
    
    def reject(self, order_id: int) -> dict | None:
        """Reject an order and refund if paid."""
        with self.db.transaction():
            order = self.get(order_id)
            if not order or order["status"] in ("rejected", "completed"):
                return None
            self.db.execute("UPDATE orders SET status='rejected', updated_at=? WHERE id=?", (self.db.utcnow(), order_id))
            if order["paid"]:
                self.db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (order["amount"], order["user_id"]))
                self.db.execute(
                    "INSERT INTO ledger(user_id, delta, kind, reference, created_at) VALUES (?,?,?,?,?)",
                    (order["user_id"], order["amount"], "order_refund", str(order_id), self.db.utcnow()),
                )
            return self.get(order_id)
    
    def list_user_orders(self, user_id: int, limit: int = 10) -> list[dict]:
        """List user's orders."""
        return self.db.fetchall(
            "SELECT o.id, o.status, o.amount, s.title service_name FROM orders o "
            "LEFT JOIN services s ON s.id=o.service_id WHERE o.user_id=? ORDER BY o.id DESC LIMIT ?",
            (user_id, limit),
        )
    
    def list_all_orders(self, limit: int = 10) -> list[dict]:
        """List all orders (admin)."""
        return self.db.fetchall(
            "SELECT o.id, o.user_id, o.status, o.amount, s.title service_name FROM orders o "
            "LEFT JOIN services s ON s.id=o.service_id ORDER BY o.id DESC LIMIT ?",
            (limit,),
        )
    
    def list_tool_orders(self, user_id: int, limit: int = 10) -> list[dict]:
        """List user's tool orders."""
        return self.db.fetchall(
            "SELECT o.id, o.status, o.amount, s.title service_name FROM orders o "
            "JOIN services s ON s.id=o.service_id "
            "WHERE o.user_id=? AND s.platform='tools' ORDER BY o.id DESC LIMIT ?",
            (user_id, limit),
        )
    
    # Provider order operations
    def begin_provider_order(
        self,
        user_id: int,
        service_id: int,
        request_key: str,
        subject: str,
        evidence: str,
        amount: int,
    ) -> tuple[str, dict | None]:
        """Atomically create local order and debit wallet for provider order.

        Returns ``("duplicate", existing)`` when the request key already exists.
        A concurrent insert that loses the UNIQUE race is converted into a
        duplicate result after rollback; callers must not call the provider for
        a duplicate, because the winning request owns the provider call.
        """
        if amount <= 0 or not request_key:
            return "invalid", None
        try:
            with self.db.transaction():
                existing = self.db.fetchone("SELECT * FROM orders WHERE request_key=?", (request_key,))
                if existing:
                    return "duplicate", existing

                cur = self.db.execute(
                    "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                    (amount, user_id, amount),
                )
                if cur.rowcount == 0:
                    return "insufficient", None

                cur = self.db.execute(
                    "INSERT INTO orders(user_id, service_id, request_key, subject, evidence_kind, evidence, amount, paid, status, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (user_id, service_id, request_key, subject, "provider_order", evidence, amount, 1, "processing", self.db.utcnow(), self.db.utcnow()),
                )
                order_id = cur.lastrowid
                self.db.execute(
                    "INSERT INTO ledger(user_id, delta, kind, reference, created_at) VALUES (?,?,?,?,?)",
                    (user_id, -amount, "provider_payment", f"order:{order_id}", self.db.utcnow()),
                )
                return "ok", self.db.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
        except Exception:
            # The transaction may have lost the request_key race, or the COMMIT
            # response may have been lost.  Never guess: if the order exists,
            # report a duplicate so the caller does not call the provider twice.
            try:
                existing = self.db.fetchone("SELECT * FROM orders WHERE request_key=?", (request_key,))
            except Exception:
                existing = None
            if existing:
                return "duplicate", existing
            raise
    
    def attach_provider_order(
        self,
        order_id: int,
        provider_name: str,
        provider_service_id: str,
        provider_order_id: str,
        quantity: int,
        link: str,
        unit_price_milli: int,
        markup_percent: int,
        api_price_per_1000_milli: int,
        api_response: dict | None = None,
    ) -> int:
        """Persist provider order confirmation (idempotent)."""
        import json
        with self.db.transaction():
            existing = self.db.fetchone("SELECT id FROM provider_orders WHERE order_id=?", (order_id,))
            if existing:
                return existing["id"]
            
            cur = self.db.execute(
                "INSERT INTO provider_orders(order_id, provider_name, provider_service_id, provider_order_id, quantity, link, unit_price_milli, markup_percent, api_price_per_1000_milli, status, api_response, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (order_id, provider_name, provider_service_id, provider_order_id, quantity, link, unit_price_milli, markup_percent, api_price_per_1000_milli, "processing", json.dumps(api_response or {}, ensure_ascii=False), self.db.utcnow(), self.db.utcnow()),
            )
            self.db.execute("UPDATE orders SET status='processing', updated_at=? WHERE id=?", (self.db.utcnow(), order_id))
            return cur.lastrowid
    
    def mark_pending_reconciliation(self, order_id: int) -> bool:
        """Keep the debit and flag the order for manual/provider reconciliation."""
        with self.db.transaction():
            cur = self.db.execute(
                "UPDATE orders SET status='pending_reconciliation', updated_at=? "
                "WHERE id=? AND status NOT IN ('rejected','completed')",
                (self.db.utcnow(), order_id),
            )
            return cur.rowcount == 1

    def refund_provider_order(self, order_id: int, reason: str = "") -> dict | None:
        """Reject a provider order and refund exactly once.

        The status transition and the wallet credit happen in one transaction.
        The ledger's UNIQUE(kind, reference) is the final double-refund guard.
        """
        with self.db.transaction():
            order = self.get(order_id)
            if not order:
                return None
            if order["status"] in ("rejected", "completed"):
                return order

            cur = self.db.execute(
                "UPDATE orders SET status='rejected', updated_at=? "
                "WHERE id=? AND status NOT IN ('rejected','completed')",
                (self.db.utcnow(), order_id),
            )
            if cur.rowcount == 0:
                return self.get(order_id)

            if order["paid"]:
                already = self.db.fetchone(
                    "SELECT 1 FROM ledger WHERE kind='order_refund' AND reference=?",
                    (str(order_id),),
                )
                if not already:
                    self.db.execute(
                        "UPDATE users SET balance=balance+? WHERE user_id=?",
                        (order["amount"], order["user_id"]),
                    )
                    self.db.execute(
                        "INSERT INTO ledger(user_id, delta, kind, reference, created_at) "
                        "VALUES (?,?,?,?,?)",
                        (order["user_id"], order["amount"], "order_refund", str(order_id), self.db.utcnow()),
                    )
            return self.get(order_id)

    def update_provider_order_status(
        self,
        provider_name: str,
        provider_order_id: str,
        status: str,
        api_response: dict | None = None,
    ) -> None:
        """Update a provider order and mirror the status to the local order."""
        import json

        with self.db.transaction():
            row = self.db.fetchone(
                "SELECT * FROM provider_orders WHERE provider_name=? AND provider_order_id=?",
                (provider_name, provider_order_id),
            )
            if not row:
                return
            self.db.execute(
                "UPDATE provider_orders SET status=?, api_response=?, updated_at=? "
                "WHERE provider_name=? AND provider_order_id=?",
                (status, json.dumps(api_response or {}, ensure_ascii=False), self.db.utcnow(), provider_name, provider_order_id),
            )
            self.db.execute(
                "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                (status, self.db.utcnow(), row["order_id"]),
            )