"""Typed state management for Bot Core."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.database.connection import Database

LOG = logging.getLogger("botcore.state")


@dataclass
class UserState:
    """Represents a user's current state."""
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    expires_at: float = 0
    
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() >= self.expires_at
    
    def to_db_format(self) -> tuple[str, str]:
        return self.name, json.dumps({
            **self.data,
            "_expires": self.expires_at,
        })
    
    @classmethod
    def from_db(cls, state: str, data: str) -> "UserState":
        if not state:
            return cls(name="", data={})
        try:
            parsed = json.loads(data)
            expires = parsed.pop("_expires", 0)
            return cls(name=state, data=parsed, expires_at=expires)
        except (json.JSONDecodeError, TypeError):
            return cls(name=state, data={})


class StateManager:
    """Manages user state with atomic operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def set_state(self, user_id: int, name: str, expires_in: int = 0, **data) -> None:
        """Set user state with optional expiration."""
        expires_at = time.time() + expires_in if expires_in > 0 else 0
        state = UserState(name=name, data=data, expires_at=expires_at)
        state_name, state_data = state.to_db_format()
        self.db.conn.execute(
            "UPDATE users SET state=?, state_data=? WHERE user_id=?",
            (state_name, state_data, user_id),
        )
    
    def get_state(self, user_id: int) -> UserState:
        """Get current user state."""
        row = self.db.fetchone(
            "SELECT state, state_data FROM users WHERE user_id=?",
            (user_id,),
        )
        if not row:
            return UserState(name="", data={})
        state = UserState.from_db(row["state"], row["state_data"])
        if state.is_expired():
            self.clear_state(user_id)
            return UserState(name="", data={})
        return state
    
    def clear_state(self, user_id: int) -> None:
        """Clear user state."""
        self.db.conn.execute(
            "UPDATE users SET state='', state_data='{}' WHERE user_id=?",
            (user_id,),
        )
    
    def claim_state(self, user_id: int, expected: str) -> bool:
        """Atomically consume a one-shot state (prevents double-submit)."""
        cur = self.db.conn.execute(
            "UPDATE users SET state='', state_data='{}' WHERE user_id=? AND state=?",
            (user_id, expected),
        )
        return cur.rowcount == 1
    
    def extend_expiry(self, user_id: int, additional_seconds: int) -> bool:
        """Extend state expiration."""
        state = self.get_state(user_id)
        if state.name:
            state.expires_at = time.time() + additional_seconds
            state_name, state_data = state.to_db_format()
            self.db.conn.execute(
                "UPDATE users SET state=?, state_data=? WHERE user_id=?",
                (state_name, state_data, user_id),
            )
            return True
        return False


# State name constants
class States:
    CAPTCHA = "captcha"
    ORDER_TARGET = "order_target"
    ORDER_REASON = "order_reason"
    ORDER_SUBJECT = "order_subject"
    ORDER_EVIDENCE = "order_evidence"
    DEPOSIT_AMOUNT = "deposit_amount"
    DEPOSIT_PROOF = "deposit_proof"
    SUPPORT = "support"
    TG_MEMBER_LINK = "tg_member_link"
    TG_MEMBER_QTY = "tg_member_qty"
    TG_MEMBER_CONFIRM = "tg_member_confirm"
    ENGAGEMENT_LINK = "engagement_link"
    ENGAGEMENT_QTY = "engagement_qty"
    ENGAGEMENT_CONFIRM = "engagement_confirm"