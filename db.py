"""Persistence for Telegram service catalog, wallet, orders and support.

Two backends are supported:
  * Turso (remote libSQL) when TURSO_URL and TURSO_TOKEN are set.  This is
    the production backend and is selected strictly -- there is no silent
    fallback to local SQLite.
  * Local SQLite otherwise (development, tests and offline rollback).

All money amounts are integers (VND); transitions are guarded and idempotent.
Run only one polling instance for each bot token/database.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import uuid

from turso_client import TursoConnection, TursoError

LOG = logging.getLogger("servicebot.db")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _turso_config():
    url = os.getenv("TURSO_URL", "").strip()
    token = os.getenv("TURSO_TOKEN", "").strip()
    if not url and not token:
        return None
    if not url or not token:
        raise RuntimeError("TURSO_URL và TURSO_TOKEN phải được thiết lập cùng nhau")
    return url, token


CATALOG = (
    ("Rà soát vi phạm TikTok", "Tiếp nhận bằng chứng về nội dung vi phạm để đánh giá và hỗ trợ báo cáo hợp lệ.", "tiktok"),
    ("Rà soát vi phạm Telegram", "Tiếp nhận bằng chứng về nội dung/nhóm vi phạm quy định Telegram.", "telegram"),
    ("Hỗ trợ khiếu nại", "Hỗ trợ chủ tài khoản chuẩn bị hồ sơ khiếu nại hoặc khôi phục quyền truy cập.", "other"),
    ("Tool Access", "Tiếp nhận nhu cầu thuê/mua quyền sử dụng phần mềm hợp pháp.", "tools"),
    ("Rà soát vi phạm YouTube", "Tiếp nhận đường dẫn YouTube và tài liệu chứng minh dấu hiệu vi phạm.", "youtube"),
    ("Rà soát vi phạm Facebook", "Tiếp nhận báo cáo chính sách có bằng chứng về nội dung Facebook.", "facebook"),
    ("Rà soát vi phạm Instagram", "Tiếp nhận báo cáo chính sách có bằng chứng về nội dung Instagram.", "instagram"),
)


class Database:
    def __init__(self, filename: str, backend: str | None = None):
        if backend not in (None, "sqlite", "turso"):
            raise ValueError("backend phải là 'sqlite' hoặc 'turso'")
        turso = _turso_config() if backend in (None, "turso") else None
        if backend == "turso" and not turso:
            raise RuntimeError("TURSO_URL và TURSO_TOKEN chưa được thiết lập")
        if turso:
            url, token = turso
            try:
                self.conn = TursoConnection(url, token)
            except TursoError as exc:
                raise RuntimeError(f"Không kết nối được Turso: {exc}") from exc
            self.backend = "turso"
            LOG.info("Database backend: Turso (remote)")
        else:
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(filename, isolation_level=None, timeout=10)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=10000")
            self.backend = "sqlite"
            LOG.info("Database backend: SQLite (%s)", filename)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '', balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
                referred_by INTEGER REFERENCES users(user_id), state TEXT NOT NULL DEFAULT '',
                state_data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL, price INTEGER NOT NULL DEFAULT 0 CHECK(price >= 0),
                enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
                service_id INTEGER NOT NULL REFERENCES services(id), request_key TEXT NOT NULL UNIQUE,
                subject TEXT NOT NULL, evidence_kind TEXT NOT NULL, evidence TEXT NOT NULL,
                amount INTEGER NOT NULL CHECK(amount >= 0), paid INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                provider_name TEXT NOT NULL DEFAULT 'vietnamfb',
                provider_service_id TEXT NOT NULL,
                provider_order_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                link TEXT NOT NULL,
                unit_price_milli INTEGER NOT NULL,  -- giá bán / 1000 đơn vị (milli VND)
                markup_percent INTEGER NOT NULL DEFAULT 0,  -- % markup từ giá gốc API
                api_price_per_1000_milli INTEGER NOT NULL,  -- giá API / 1000 đơn vị (milli VND)
                status TEXT NOT NULL DEFAULT 'pending',
                api_response TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(provider_name, provider_order_id)
            );
            CREATE INDEX IF NOT EXISTS idx_provider_orders_order ON provider_orders(order_id);
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
                amount INTEGER NOT NULL CHECK(amount >= 10000), status TEXT NOT NULL,
                proof_kind TEXT NOT NULL DEFAULT '', proof TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
                delta INTEGER NOT NULL, kind TEXT NOT NULL, reference TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(kind, reference)
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
                message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(user_id, created_at);
        """)
        # Automatic additive migrations: preserve existing wallets, orders and user IDs.
        user_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(users)")}
        if "verified_at" not in user_columns:
            self.conn.execute("ALTER TABLE users ADD COLUMN verified_at TEXT NOT NULL DEFAULT ''")
        if "language" not in user_columns:
            self.conn.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT ''")
        service_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(services)")}
        if "platform" not in service_columns:
            self.conn.execute("ALTER TABLE services ADD COLUMN platform TEXT NOT NULL DEFAULT 'other'")
        with self.transaction():
            for title, desc, platform in CATALOG:
                self.conn.execute(
                    "INSERT OR IGNORE INTO services(title,description,platform) VALUES (?,?,?)",
                    (title, desc, platform),
                )
                self.conn.execute(
                    "UPDATE services SET platform=? WHERE title=?", (platform, title)
                )
            # Default markup for provider orders (percent, e.g., 100 = 2x)
            self.conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES ('provider_markup_percent','100')"
            )

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.execute("COMMIT")
        except BaseException:
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                LOG.exception("Không thể rollback giao dịch; kết nối có thể đã mất")
            raise

    def one(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchall()

    def ensure_user(self, user_id: int, username: str, display_name: str, referral: int | None = None):
        if referral == user_id or not self.one("SELECT 1 FROM users WHERE user_id=?", (referral,)):
            referral = None
        with self.transaction():
            self.conn.execute(
                "INSERT OR IGNORE INTO users(user_id,username,display_name,referred_by,created_at) "
                "VALUES (?,?,?,?,?)", (user_id, username, display_name, referral, utcnow())
            )
            self.conn.execute(
                "UPDATE users SET username=?, display_name=? WHERE user_id=?",
                (username, display_name, user_id),
            )

    def get_user(self, user_id: int):
        return self.one("SELECT * FROM users WHERE user_id=?", (user_id,))

    def verify_user(self, user_id: int) -> None:
        self.conn.execute("UPDATE users SET verified_at=?,state='',state_data='{}' WHERE user_id=?",
                          (utcnow(), user_id))

    def set_language(self, user_id: int, language: str) -> bool:
        if language not in {"vi", "en", "ru", "ar", "fa", "es", "pt", "de", "fr", "hi", "id"}:
            return False
        return self.conn.execute("UPDATE users SET language=? WHERE user_id=?",
                                 (language, user_id)).rowcount == 1

    def set_state(self, user_id: int, state: str, **data):
        payload = json.dumps(data) if data else "{}"
        self.conn.execute("UPDATE users SET state=?,state_data=? WHERE user_id=?", (state, payload, user_id))

    def claim_state(self, user_id: int, expected: str) -> bool:
        """Atomically consume a one-shot state (prevents double-submit)."""
        cur = self.conn.execute(
            "UPDATE users SET state='',state_data='{}' WHERE user_id=? AND state=?",
            (user_id, expected),
        )
        return cur.rowcount == 1

    def get_state(self, user_id: int):
        user = self.get_user(user_id)
        if not user:
            return "", {}
        try:
            return user["state"], json.loads(user["state_data"])
        except (ValueError, TypeError):
            return "", {}

    def list_services(self, platform: str | None = None):
        if platform is None:
            return self.all("SELECT * FROM services WHERE enabled=1 ORDER BY id")
        return self.all("SELECT * FROM services WHERE enabled=1 AND platform=? ORDER BY id", (platform,))

    def get_service(self, service_id: int):
        return self.one("SELECT * FROM services WHERE id=? AND enabled=1", (service_id,))

    def get_service_by_title(self, title: str):
        return self.one("SELECT * FROM services WHERE title=?", (title,))

    def set_price(self, service_id: int, price: int) -> bool:
        if price < 0:
            return False
        return self.conn.execute("UPDATE services SET price=? WHERE id=?", (price, service_id)).rowcount == 1

    def count_active_orders(self, user_id: int):
        return self.one(
            "SELECT COUNT(*) c FROM orders WHERE user_id=? AND status IN "
            "('awaiting_quote','awaiting_payment','pending_review','processing','pending_reconciliation')", (user_id,)
        )["c"]

    def create_order(self, user_id: int, service_id: int, subject: str, kind: str, evidence: str,
                     request_key: str):
        with self.transaction():
            existing = self.one("SELECT * FROM orders WHERE request_key=?", (request_key,))
            if existing:
                return existing
            service = self.get_service(service_id)
            if not service:
                return None
            if self.count_active_orders(user_id) >= 5:
                return None
            price = int(service["price"])
            status = "awaiting_quote" if price == 0 else "awaiting_payment"
            cur = self.conn.execute(
                "INSERT INTO orders(user_id,service_id,request_key,subject,evidence_kind,evidence,amount,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (user_id, service_id, request_key, subject, kind, evidence, price, status, utcnow(), utcnow()),
            )
            return self.one("SELECT * FROM orders WHERE id=?", (cur.lastrowid,))

    def get_order(self, order_id: int):
        return self.one(
            "SELECT o.*,s.title service_name FROM orders o JOIN services s ON s.id=o.service_id "
            "WHERE o.id=?", (order_id,)
        )

    def pay_order(self, order_id: int, user_id: int) -> str:
        with self.transaction():
            order = self.get_order(order_id)
            if not order or order["user_id"] != user_id:
                return "missing"
            if order["status"] == "pending_review" and order["paid"]:
                return "already_paid"
            if order["status"] != "awaiting_payment" or order["paid"] or order["amount"] <= 0:
                return "not_payable"
            cur = self.conn.execute(
                "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                (order["amount"], user_id, order["amount"]),
            )
            if cur.rowcount == 0:
                return "insufficient"
            self.conn.execute(
                "UPDATE orders SET paid=1,status='pending_review',updated_at=? WHERE id=?",
                (utcnow(), order_id),
            )
            self.conn.execute(
                "INSERT INTO ledger(user_id,delta,kind,reference,created_at) VALUES (?,?,?,?,?)",
                (user_id, -order["amount"], "order_payment", str(order_id), utcnow()),
            )
            return "paid"

    def quote_order(self, order_id: int, amount: int):
        if amount <= 0:
            return None
        with self.transaction():
            cur = self.conn.execute(
                "UPDATE orders SET amount=?,status='awaiting_payment',updated_at=? "
                "WHERE id=? AND status='awaiting_quote' AND paid=0", (amount, utcnow(), order_id)
            )
            return self.get_order(order_id) if cur.rowcount else None

    def set_order_status(self, order_id: int, next_status: str):
        transitions = {
            "processing": ("pending_review", "pending_reconciliation"),
            "completed": ("processing",),
        }
        if next_status not in transitions:
            return None
        with self.transaction():
            order = self.get_order(order_id)
            if not order or order["status"] not in transitions[next_status]:
                return None
            self.conn.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                              (next_status, utcnow(), order_id))
            return self.get_order(order_id)

    def reject_order(self, order_id: int):
        with self.transaction():
            order = self.get_order(order_id)
            if not order or order["status"] in ("rejected", "completed"):
                return None
            self.conn.execute("UPDATE orders SET status='rejected',updated_at=? WHERE id=?",
                              (utcnow(), order_id))
            if order["paid"]:
                self.conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?",
                                  (order["amount"], order["user_id"]))
                self.conn.execute(
                    "INSERT INTO ledger(user_id,delta,kind,reference,created_at) VALUES (?,?,?,?,?)",
                    (order["user_id"], order["amount"], "order_refund", str(order_id), utcnow()),
                )
            return self.get_order(order_id)

    def list_orders(self, user_id: int | None = None, limit: int = 10):
        if user_id is None:
            return self.all("SELECT o.id,o.user_id,o.status,o.amount,s.title service_name FROM orders o "
                            "LEFT JOIN services s ON s.id=o.service_id ORDER BY o.id DESC LIMIT ?", (limit,))
        return self.all("SELECT o.id,o.user_id,o.status,o.amount,s.title service_name FROM orders o "
                        "LEFT JOIN services s ON s.id=o.service_id WHERE o.user_id=? ORDER BY o.id DESC LIMIT ?",
                        (user_id, limit))

    def list_tool_orders(self, user_id: int, limit: int = 10):
        return self.all(
            "SELECT o.id,o.status,o.amount,s.title service_name FROM orders o "
            "JOIN services s ON s.id=o.service_id "
            "WHERE o.user_id=? AND s.platform='tools' ORDER BY o.id DESC LIMIT ?",
            (user_id, limit),
        )

    def begin_provider_order(self, user_id: int, service_id: int, request_key: str,
                             subject: str, evidence: str, amount: int):
        """Atomically create a local order and debit the wallet once.

        Returns ``(outcome, order)`` where outcome is ``ok``, ``duplicate``,
        ``insufficient`` or ``invalid``.  The unique ``request_key`` makes a
        double-submitted confirmation harmless even if the state claim races.
        """
        if amount <= 0 or not request_key:
            return "invalid", None
        with self.transaction():
            existing = self.one("SELECT * FROM orders WHERE request_key=?", (request_key,))
            if existing:
                return "duplicate", existing
            cur = self.conn.execute(
                "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                (amount, user_id, amount),
            )
            if cur.rowcount == 0:
                return "insufficient", None
            cur = self.conn.execute(
                "INSERT INTO orders(user_id,service_id,request_key,subject,evidence_kind,evidence,"
                "amount,paid,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, service_id, request_key, subject, "provider_order", evidence,
                 amount, 1, "processing", utcnow(), utcnow()),
            )
            order_id = cur.lastrowid
            self.conn.execute(
                "INSERT INTO ledger(user_id,delta,kind,reference,created_at) VALUES (?,?,?,?,?)",
                (user_id, -amount, "provider_payment", f"order:{order_id}", utcnow()),
            )
            return "ok", self.one("SELECT * FROM orders WHERE id=?", (order_id,))

    def attach_provider_order(self, order_id: int, provider_name: str,
                              provider_service_id: str, provider_order_id: str,
                              quantity: int, link: str, unit_price_milli: int,
                              markup_percent: int, api_price_per_1000_milli: int,
                              api_response: dict | None = None) -> int:
        """Persist the provider's confirmation for an existing local order.

        Idempotent: a retry after a lost response returns the existing row.
        """
        with self.transaction():
            existing = self.one("SELECT id FROM provider_orders WHERE order_id=?", (order_id,))
            if existing:
                return existing["id"]
            cur = self.conn.execute(
                "INSERT INTO provider_orders(order_id,provider_name,provider_service_id,provider_order_id,"
                "quantity,link,unit_price_milli,markup_percent,api_price_per_1000_milli,status,api_response,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (order_id, provider_name, provider_service_id, provider_order_id,
                 quantity, link, unit_price_milli, markup_percent,
                 api_price_per_1000_milli, "processing",
                 json.dumps(api_response or {}, ensure_ascii=False), utcnow(), utcnow()),
            )
            self.conn.execute(
                "UPDATE orders SET status='processing',updated_at=? WHERE id=?",
                (utcnow(), order_id),
            )
            return cur.lastrowid

    def mark_order_pending_reconciliation(self, order_id: int) -> bool:
        """Keep the debit but flag the order for manual/provider reconciliation."""
        with self.transaction():
            cur = self.conn.execute(
                "UPDATE orders SET status='pending_reconciliation',updated_at=? "
                "WHERE id=? AND status NOT IN ('rejected','completed')",
                (utcnow(), order_id),
            )
            return cur.rowcount == 1

    def get_provider_order(self, order_id: int):
        return self.one(
            "SELECT po.*, o.user_id, o.amount, o.status as order_status FROM provider_orders po "
            "JOIN orders o ON o.id=po.order_id WHERE po.order_id=?", (order_id,)
        )

    def get_provider_order_by_provider_id(self, provider_name: str, provider_order_id: str):
        return self.one(
            "SELECT po.*, o.user_id, o.amount, o.status as order_status FROM provider_orders po "
            "JOIN orders o ON o.id=po.order_id WHERE po.provider_name=? AND po.provider_order_id=?",
            (provider_name, provider_order_id),
        )

    def update_provider_order_status(self, provider_name: str, provider_order_id: str, status: str, api_response: dict):
        import json
        with self.transaction():
            self.conn.execute(
                "UPDATE provider_orders SET status=?, api_response=?, updated_at=? WHERE provider_name=? AND provider_order_id=?",
                (status, json.dumps(api_response), utcnow(), provider_name, provider_order_id),
            )
            # Cập nhật order status tương ứng
            po = self.get_provider_order_by_provider_id(provider_name, provider_order_id)
            if po:
                self.conn.execute(
                    "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                    (status, utcnow(), po["order_id"]),
                )

    def get_markup_percent(self) -> int:
        val = self.get_setting("provider_markup_percent")
        try:
            return max(0, int(val))
        except (ValueError, TypeError):
            return 100  # default 2x

    def set_markup_percent(self, percent: int) -> bool:
        if percent < 0:
            return False
        return self.conn.execute("UPDATE settings SET value=? WHERE key='provider_markup_percent'", (str(percent),)).rowcount == 1

    # Engagement Services methods
    def list_engagement_platforms(self, enabled_only: bool = True):
        """Get all engagement platforms, optionally filtered by enabled status."""
        sql = "SELECT * FROM engagement_platforms"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY sort_order, id"
        return self.all(sql)

    def get_engagement_platform(self, platform_id: int):
        return self.one("SELECT * FROM engagement_platforms WHERE id=?", (platform_id,))

    def get_engagement_platform_by_slug(self, slug: str):
        return self.one("SELECT * FROM engagement_platforms WHERE slug=?", (slug,))

    def list_engagement_categories(self, platform_id: int, enabled_only: bool = True):
        """Get service categories for a platform."""
        sql = "SELECT * FROM engagement_categories WHERE platform_id=?"
        params = [platform_id]
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY sort_order, id"
        return self.all(sql, params)

    def get_engagement_category(self, category_id: int):
        return self.one("SELECT * FROM engagement_categories WHERE id=?", (category_id,))

    def get_engagement_category_by_slug(self, platform_id: int, slug: str):
        return self.one("SELECT * FROM engagement_categories WHERE platform_id=? AND slug=?", (platform_id, slug))

    def list_engagement_provider_services(self, category_id: int, enabled_only: bool = True):
        """Get provider services for a category."""
        sql = "SELECT * FROM engagement_provider_services WHERE category_id=?"
        params = [category_id]
        if enabled_only:
            sql += " AND status='active'"
        sql += " ORDER BY id"
        return self.all(sql, params)

    def get_engagement_provider_service(self, service_id: int):
        return self.one("SELECT * FROM engagement_provider_services WHERE id=?", (service_id,))

    def get_engagement_provider_service_by_provider_id(self, provider_id: str, provider_service_id: str):
        return self.one(
            "SELECT * FROM engagement_provider_services WHERE provider_id=? AND provider_service_id=?",
            (provider_id, provider_service_id),
        )

    def create_deposit(self, user_id: int, amount: int):
        if amount < 10000 or amount > 100000000:
            return None
        with self.transaction():
            c = self.one("SELECT COUNT(*) c FROM deposits WHERE user_id=? AND status IN ('waiting_proof','pending')",
                         (user_id,))["c"]
            if c >= 3:
                return None
            cur = self.conn.execute(
                "INSERT INTO deposits(user_id,amount,status,created_at,updated_at) VALUES (?,?,?,?,?)",
                (user_id, amount, "waiting_proof", utcnow(), utcnow()),
            )
            return self.one("SELECT * FROM deposits WHERE id=?", (cur.lastrowid,))

    def submit_proof(self, deposit_id: int, user_id: int, kind: str, proof: str):
        with self.transaction():
            cur = self.conn.execute(
                "UPDATE deposits SET proof_kind=?,proof=?,status='pending',updated_at=? "
                "WHERE id=? AND user_id=? AND status='waiting_proof'",
                (kind, proof, utcnow(), deposit_id, user_id),
            )
            return self.one("SELECT * FROM deposits WHERE id=?", (deposit_id,)) if cur.rowcount else None

    def deposit_action(self, deposit_id: int, approve: bool):
        with self.transaction():
            dep = self.one("SELECT * FROM deposits WHERE id=?", (deposit_id,))
            if not dep or dep["status"] != "pending":
                return None
            status = "approved" if approve else "rejected"
            self.conn.execute("UPDATE deposits SET status=?,updated_at=? WHERE id=?", (status, utcnow(), deposit_id))
            if approve:
                self.conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (dep["amount"], dep["user_id"]))
                self.conn.execute(
                    "INSERT INTO ledger(user_id,delta,kind,reference,created_at) VALUES (?,?,?,?,?)",
                    (dep["user_id"], dep["amount"], "deposit", str(deposit_id), utcnow()),
                )
            return self.one("SELECT * FROM deposits WHERE id=?", (deposit_id,))

    def cancel_deposit(self, deposit_id: int, user_id: int) -> bool:
        with self.transaction():
            cur = self.conn.execute(
                "UPDATE deposits SET status='cancelled',updated_at=? "
                "WHERE id=? AND user_id=? AND status='waiting_proof'",
                (utcnow(), deposit_id, user_id),
            )
            return cur.rowcount == 1

    def list_user_deposits(self, user_id: int):
        return self.all(
            "SELECT id,amount,status FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,)
        )

    def list_deposits(self):
        return self.all("SELECT id,user_id,amount,status FROM deposits WHERE status='pending' ORDER BY id DESC LIMIT 20")

    def credit(self, user_id: int, amount: int):
        if amount <= 0 or amount > 100000000:
            return False
        with self.transaction():
            cur = self.conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
            if not cur.rowcount:
                return False
            self.conn.execute("INSERT INTO ledger(user_id,delta,kind,reference,created_at) VALUES (?,?,?,?,?)",
                              (user_id, amount, "admin_credit", uuid.uuid4().hex, utcnow()))
            return True

    def referrals(self, user_id: int):
        return self.one("SELECT COUNT(*) c FROM users WHERE referred_by=?", (user_id,))["c"]

    def create_ticket(self, user_id: int, msg: str):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        recent = self.one("SELECT COUNT(*) c FROM tickets WHERE user_id=? AND created_at>=?",
                          (user_id, cutoff))["c"]
        if recent >= 5:
            return None
        cur = self.conn.execute("INSERT INTO tickets(user_id,message,created_at) VALUES (?,?,?)",
                                (user_id, msg, utcnow()))
        return self.one("SELECT * FROM tickets WHERE id=?", (cur.lastrowid,))

    def ticket(self, ticket_id: int):
        return self.one("SELECT * FROM tickets WHERE id=?", (ticket_id,))

    def get_setting(self, key: str) -> str:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else ""

    def set_setting(self, key: str, value: str):
        self.conn.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, value))

    def stats(self):
        return {
            "users": self.one("SELECT COUNT(*) c FROM users")["c"],
            "orders": self.one("SELECT COUNT(*) c FROM orders")["c"],
            "pending_deposits": self.one("SELECT COUNT(*) c FROM deposits WHERE status='pending'")["c"],
        }

    def close(self):
        self.conn.close()
