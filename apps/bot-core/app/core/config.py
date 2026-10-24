"""Configuration management for Bot Core."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BotConfig:
    """Bot configuration loaded from environment variables."""
    
    # Telegram
    bot_token: str
    admin_ids: set[int]
    bot_name: str
    support_username: str
    
    # Database
    db_path: str
    db_backend: str | None
    
    # Banking (for deposits)
    bank_name: str
    bank_account: str
    bank_owner: str
    
    # Engagement API
    engagement_api_url: str
    engagement_api_token: str
    
    # Logging
    log_level: str
    
    @classmethod
    def load(cls, env_file: str = ".env") -> "BotConfig":
        """Load configuration from environment and .env file."""
        # Load .env file if exists
        if Path(env_file).exists():
            for line in Path(env_file).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name = name.strip()
                if name.isupper() and name.replace("_", "").isalnum():
                    os.environ.setdefault(name, value.strip().strip('"').strip("'"))
        
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or ":" not in token:
            raise ValueError("BOT_TOKEN must be set from @BotFather")
        
        admin_ids = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
        if not admin_ids:
            raise ValueError("ADMIN_IDS must be set with at least one admin user ID")
        
        return cls(
            bot_token=token,
            admin_ids=admin_ids,
            bot_name=os.getenv("BOT_NAME", "ToolNet Services")[:48],
            support_username=os.getenv("SUPPORT_USERNAME", "").lstrip("@"),
            db_path=os.getenv("DB_PATH", "./data/bot.sqlite3"),
            db_backend=os.getenv("DB_BACKEND", "").strip().lower() or None,
            bank_name=os.getenv("BANK_NAME", "").strip(),
            bank_account=os.getenv("BANK_ACCOUNT", "").strip(),
            bank_owner=os.getenv("BANK_OWNER", "").strip(),
            engagement_api_url=os.getenv("ENGAGEMENT_API_URL", "http://toolnet-engagement:8000"),
            engagement_api_token=os.getenv("ENGAGEMENT_API_TOKEN", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
    
    @property
    def bank_configured(self) -> bool:
        return all([self.bank_name, self.bank_account, self.bank_owner])