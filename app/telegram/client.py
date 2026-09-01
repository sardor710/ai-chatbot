"""Telethon client wrapper with connection management and interactive authentication."""

import logging

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import User

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramClientManager:
    """Manages the MTProto Telethon client lifecycle and authentication."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: TelegramClient | None = None
        self.me: User | None = None

    def create_client(self) -> TelegramClient:
        """Create a Telethon TelegramClient instance."""
        if not self.settings.TELEGRAM_API_ID or not self.settings.TELEGRAM_API_HASH:
            raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be configured.")

        self.client = TelegramClient(
            session=self.settings.TELEGRAM_SESSION,
            api_id=int(self.settings.TELEGRAM_API_ID),
            api_hash=self.settings.TELEGRAM_API_HASH,
            auto_reconnect=True,
            connection_retries=5,
            retry_delay=3,
        )
        return self.client

    async def start(self) -> TelegramClient:
        """Connect and authenticate the client interactively if needed."""
        if not self.client:
            self.create_client()

        assert self.client is not None
        await self.client.connect()

        if not await self.client.is_user_authorized():
            logger.info("First-time login detected: interactive MTProto authentication required.")
            phone = self.settings.TELEGRAM_PHONE or input(
                "Enter Telegram phone number (international format): "
            )
            await self.client.send_code_request(phone)
            code = input("Enter Telegram verification code received: ")

            try:
                await self.client.sign_in(phone, code)
            except SessionPasswordNeededError:
                password = input("Enter 2FA password: ")
                await self.client.sign_in(password=password)

        self.me = await self.client.get_me()
        logger.info(
            f"Telegram MTProto client authenticated as @{self.me.username or 'unknown'} (ID: {self.me.id})"
        )

        # Update owner ID if not set
        if not self.settings.OWNER_USER_ID and self.me:
            self.settings.OWNER_USER_ID = self.me.id

        return self.client

    async def stop(self) -> None:
        """Gracefully disconnect the Telegram client."""
        if self.client and self.client.is_connected():
            logger.info("Disconnecting Telegram client...")
            await self.client.disconnect()
            logger.info("Telegram client disconnected.")
