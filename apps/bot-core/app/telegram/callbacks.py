"""Type-safe callback router for Bot Core."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.core.config import BotConfig
from app.database.connection import Database
from app.telegram.keyboards import keyboard

LOG = logging.getLogger("botcore.callbacks")


@dataclass(frozen=True)
class CallbackData:
    """Parsed callback data with type safety."""
    action: str
    params: dict[str, str]


class CallbackRouter:
    """Routes callback queries to handlers with type-safe parsing."""
    
    def __init__(self):
        self._routes: dict[str, Callable] = {}
        self._prefix_routes: list[tuple[str, Callable]] = []
        self._regex_routes: list[tuple[re.Pattern, Callable]] = []
    
    def register(self, pattern: str) -> Callable:
        """Decorator to register a callback handler."""
        def decorator(func: Callable) -> Callable:
            if pattern.endswith(":*") or pattern.endswith(":") or pattern.endswith("**"):
                # Prefix route
                prefix = pattern.rstrip(":*").rstrip(":").rstrip("*")
                self._prefix_routes.append((prefix, func))
            elif ":" in pattern and pattern.count(":") == pattern.count("{") + 1:
                # Regex-like route with parameters
                regex_pattern = pattern.replace(":", r"\:").replace("{", "(?P<").replace("}", ">[^:]+)")
                self._regex_routes.append((re.compile(f"^{regex_pattern}$"), func))
            else:
                # Exact match
                self._routes[pattern] = func
            return func
        return decorator
    
    def parse(self, data: str) -> CallbackData:
        """Parse callback data into action and parameters."""
        parts = data.split(":")
        action = parts[0]
        params = {}
        
        # Handle known patterns
        if action == "engagement":
            if len(parts) >= 3:
                params["sub_action"] = parts[1]
                params["value"] = ":".join(parts[2:])
        elif action in ("platform", "service", "new", "target", "order", "pay", "lang", "tg_member_select", "tg_member_confirm_pay"):
            if len(parts) >= 2:
                params["id"] = parts[1]
            if len(parts) >= 3:
                params["extra"] = ":".join(parts[2:])
        elif action in ("tools", "platform", "engagement:platform", "engagement:category", "engagement:coming_soon"):
            if len(parts) >= 2:
                params["value"] = ":".join(parts[1:])
        
        return CallbackData(action=action, params=params)
    
    def route(self, data: str) -> tuple[Optional[Callable], CallbackData]:
        """Find handler for callback data."""
        # Exact match
        if data in self._routes:
            return self._routes[data], self.parse(data)
        
        # Regex routes
        for pattern, handler in self._regex_routes:
            match = pattern.match(data)
            if match:
                parsed = self.parse(data)
                parsed.params.update(match.groupdict())
                return handler, parsed
        
        # Prefix routes
        for prefix, handler in self._prefix_routes:
            if data.startswith(prefix + ":"):
                return handler, self.parse(data)
        
        return None, self.parse(data)


# Global router instance
router = CallbackRouter()