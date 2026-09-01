"""Safe Telegram message sender with rate limiting, human pacing, dry-run, and flood protection."""

import asyncio
import logging
import random

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

from app.config import Settings
from app.telegram.media import MediaManager

logger = logging.getLogger(__name__)


class TelegramSender:
    """Sends messages and media through Telethon with pacing, dry-run checks, and error handling."""

    def __init__(
        self,
        client: TelegramClient,
        settings: Settings,
        media_manager: MediaManager,
    ) -> None:
        self.client = client
        self.settings = settings
        self.media_manager = media_manager

    def _calculate_typing_delay(self, text: str) -> float:
        """
        Calculate realistic human typing pause:
        3 to 10 seconds depending on message length and complexity.
        - Short messages (~1-15 chars, e.g. 'М', 'Привет.'): ~3.0 - 4.0s
        - Medium messages (~15-50 chars, e.g. 'Я М) Сколько тебе лет?'): ~4.0 - 6.5s
        - Long messages (50+ chars, e.g. 'Как дела? Какие планы на вечер?'): ~6.5 - 10.0s
        """
        length = len(text.strip()) if text else 0
        min_sec = max(3.0, self.settings.MIN_REPLY_DELAY_SECONDS)
        max_sec = max(10.0, self.settings.MAX_REPLY_DELAY_SECONDS)

        # Baseline reading / thinking latency before starting to type: 2.0 to 3.0 seconds
        base_latency = random.uniform(2.0, 3.0)

        # Typing rate: roughly 10-14 characters per second (0.07 - 0.11s per char) with jitter
        char_time = length * random.uniform(0.07, 0.11)

        total_delay = base_latency + char_time
        return max(min_sec, min(max_sec, total_delay))

    async def _apply_human_delay(self, chat_id: int | str, text: str = "") -> None:
        """Simulate realistic typing delay before message dispatch."""
        delay = self._calculate_typing_delay(text)
        logger.info(
            f"Simulating human typing delay ({delay:.1f}s for {len(text)} chars) to chat {chat_id}..."
        )
        try:
            # Simulate typing action on Telegram
            if not self.settings.DRY_RUN and self.client.is_connected():
                async with self.client.action(chat_id, "typing"):
                    await asyncio.sleep(delay)
            else:
                await asyncio.sleep(delay)
        except Exception:
            await asyncio.sleep(delay)

    async def send_text(self, chat_id: int | str, text: str) -> bool:
        """
        Send text message to a chat.
        Respects DRY_RUN, DRAFT_MODE, AUTOPILOT_ENABLED, and handles FloodWait.
        """
        if not text:
            return False

        # Autopilot Check
        if not self.settings.AUTOPILOT_ENABLED and not self.settings.DRY_RUN:
            logger.info(
                f"[AUTOPILOT DISABLED] Suppressed outgoing message to chat {chat_id}: {text}"
            )
            return False

        # Dry Run Mode Check
        if self.settings.DRY_RUN:
            logger.info(f"[DRY_RUN] Would send to chat {chat_id}: '{text}'")
            return True

        # Draft Mode Check
        if self.settings.DRAFT_MODE:
            logger.info(f"[DRAFT_MODE] Draft saved for chat {chat_id}: '{text}'")
            return True

        # Apply human typing delay only for non-command messages
        if not text.startswith("/"):
            await self._apply_human_delay(chat_id, text)

        # Send via Telethon
        try:
            await self.client.send_message(chat_id, text)
            logger.info(f"Message sent to chat {chat_id}: '{text[:50]}'")
            return True
        except FloodWaitError as e:
            logger.warning(
                f"Telegram FloodWaitError: sleeping {e.seconds} seconds before retrying..."
            )
            await asyncio.sleep(e.seconds + 1)
            try:
                await self.client.send_message(chat_id, text)
                logger.info(f"Message sent successfully after FloodWait to chat {chat_id}.")
                return True
            except Exception as retry_err:
                logger.error(f"Failed to send message after FloodWait: {retry_err}")
                return False
        except RPCError as e:
            logger.error(f"Telethon RPCError sending to {chat_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending message to {chat_id}: {e}")
            return False

    async def send_photo(self, chat_id: int, photo_alias: str) -> bool:
        """Send an authorized photo by alias."""
        target_path = await self.media_manager.get_photo_target(photo_alias)
        if not target_path:
            logger.error(f"Cannot send photo: alias '{photo_alias}' is not registered.")
            return False

        if not self.settings.AUTOPILOT_ENABLED and not self.settings.DRY_RUN:
            logger.info(
                f"[AUTOPILOT DISABLED] Suppressed sending photo {photo_alias} to chat {chat_id}"
            )
            return False

        if self.settings.DRY_RUN:
            logger.info(
                f"[DRY_RUN] Would send photo '{photo_alias}' ({target_path}) to chat {chat_id}"
            )
            return True

        if self.settings.DRAFT_MODE:
            logger.info(f"[DRAFT_MODE] Draft photo '{photo_alias}' for chat {chat_id}")
            return True

        await self._apply_human_delay(chat_id)

        try:
            await self.client.send_file(chat_id, target_path)
            logger.info(f"Photo '{photo_alias}' sent to chat {chat_id}")
            return True
        except FloodWaitError as e:
            logger.warning(f"Telegram FloodWaitError on photo send: sleeping {e.seconds}s...")
            await asyncio.sleep(e.seconds + 1)
            await self.client.send_file(chat_id, target_path)
            return True
        except Exception as e:
            logger.error(f"Failed to send photo '{photo_alias}' to {chat_id}: {e}")
            return False
