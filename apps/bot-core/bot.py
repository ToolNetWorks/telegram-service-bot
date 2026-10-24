#!/usr/bin/env python3
"""ToolNet Bot Core - Telegram Bot API entry point."""

from __future__ import annotations

import logging
import signal
import sys
import time

from app.core.config import BotConfig
from app.core.logging import setup_logging
from app.core.state import StateManager
from app.database.connection import Database
from app.database.migrations import init_database
from app.modules.users.repository import UserRepository
from app.modules.wallet.repository import WalletRepository
from app.modules.deposits.repository import DepositRepository
from app.modules.orders.repository import OrderRepository
from app.modules.orders.services_repository import ServicesRepository
from app.modules.engagement.repository import EngagementRepository
from app.modules.admin.repository import SettingsRepository
from app.telegram.handlers import Handlers, Update
from app.clients.engagement import EngagementClient
from app.core.telegram import TelegramClient, TelegramAPIError

LOG = logging.getLogger("botcore")


class BotCore:
    """Main Bot Core application."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.running = False

        # Initialize database
        self.db = Database(config)
        init_database(self.db)

        # Initialize Telegram client
        self.tg = TelegramClient(config)
        self._setup_bot_info()

        # Initialize repositories
        self.user_repo = UserRepository(self.db)
        self.wallet_repo = WalletRepository(self.db)
        self.deposit_repo = DepositRepository(self.db)
        self.order_repo = OrderRepository(self.db)
        self.services_repo = ServicesRepository(self.db)
        self.engagement_repo = EngagementRepository(self.db)
        self.settings_repo = SettingsRepository(self.db)

        # Initialize state manager
        self.state_manager = StateManager(self.db)

        # Initialize Engagement API client
        self.engagement_client = EngagementClient(config)

        # Initialize handlers
        self.handlers = Handlers(
            config=config,
            db=self.db,
            tg_client=self.tg,
            user_repo=self.user_repo,
            wallet_repo=self.wallet_repo,
            deposit_repo=self.deposit_repo,
            order_repo=self.order_repo,
            services_repo=self.services_repo,
            engagement_repo=self.engagement_repo,
            settings_repo=self.settings_repo,
            state_manager=self.state_manager,
            engagement_client=self.engagement_client,
        )

        self.poll_offset = self.settings_repo.get_poll_offset()

    def _setup_bot_info(self) -> None:
        """Get bot info and delete webhook."""
        try:
            self.tg.delete_webhook(drop_pending_updates=True)
            me = self.tg.get_me()
            self.tg.username = me.get("username", "")
            LOG.info("Bot initialized: @%s", self.tg.username)
        except TelegramAPIError as exc:
            LOG.error("Failed to initialize bot: %s", exc)
            raise

    def run(self) -> None:
        """Start the long polling loop."""
        self.running = True
        LOG.info("Starting Bot Core long polling...")

        # Signal handling
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        while self.running:
            try:
                updates = self.tg.get_updates(self.poll_offset, timeout=25, limit=50)
                for update in updates:
                    self.poll_offset = update["update_id"] + 1
                    self.settings_repo.set_poll_offset(self.poll_offset)
                    self._process_update(update)
            except TelegramAPIError as exc:
                LOG.warning("Telegram API error: %s", exc)
                time.sleep(5)
            except Exception:
                LOG.exception("Unexpected error in polling loop")
                time.sleep(5)

        self._cleanup()

    def _process_update(self, raw_update: dict) -> None:
        """Parse and handle a raw Telegram update."""
        try:
            if "message" in raw_update:
                msg = raw_update["message"]
                update = Update(
                    user_id=msg["from"]["id"],
                    username=msg["from"].get("username", ""),
                    display_name=msg["from"].get("first_name", "") + " " + msg["from"].get("last_name", ""),
                    message_id=msg.get("message_id"),
                    text=msg.get("text"),
                    callback_query_id=None,
                    callback_data=None,
                    is_callback=False,
                )
            elif "callback_query" in raw_update:
                cb = raw_update["callback_query"]
                msg = cb.get("message")
                update = Update(
                    user_id=cb["from"]["id"],
                    username=cb["from"].get("username", ""),
                    display_name=cb["from"].get("first_name", "") + " " + cb["from"].get("last_name", ""),
                    message_id=msg.get("message_id") if msg else None,
                    text=None,
                    callback_query_id=cb["id"],
                    callback_data=cb.get("data"),
                    is_callback=True,
                )
            else:
                return

            self.handlers.handle_update(update)

        except Exception:
            LOG.exception("Error processing update")

    def _shutdown(self, signum, frame) -> None:
        LOG.info("Shutdown signal received")
        self.running = False

    def _cleanup(self) -> None:
        LOG.info("Cleaning up...")
        self.db.close()
        LOG.info("Bot Core stopped")


def main() -> int:
    """Main entry point."""
    try:
        config = BotConfig.load()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    setup_logging(config.log_level)

    try:
        bot = BotCore(config)
        bot.run()
        return 0
    except Exception as exc:
        LOG.exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())