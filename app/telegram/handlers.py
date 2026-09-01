"""Telegram event handlers connecting Telethon events to the application router."""

import logging

from telethon import TelegramClient, events

from app.conversations.router import MessageRouter

logger = logging.getLogger(__name__)


def register_telegram_handlers(
    client: TelegramClient,
    router: MessageRouter,
) -> None:
    """Register Telethon event listeners on the client instance."""

    @client.on(events.NewMessage)
    async def on_new_message(event: events.NewMessage.Event) -> None:
        try:
            # Basic event metadata
            chat_id = event.chat_id
            message_id = event.id
            text = event.raw_text or ""
            is_self = event.out  # True if message was sent by the logged-in user account
            is_private = event.is_private
            is_group = event.is_group

            sender = await event.get_sender()
            sender_id = sender.id if sender else chat_id

            all_usernames: list[str] = []
            if sender:
                if getattr(sender, "username", None):
                    all_usernames.append(sender.username)
                for u in getattr(sender, "usernames", []) or []:
                    if getattr(u, "username", None):
                        all_usernames.append(u.username)

            if is_private:
                chat = await event.get_chat()
                if chat:
                    if getattr(chat, "username", None):
                        all_usernames.append(chat.username)
                    for u in getattr(chat, "usernames", []) or []:
                        if getattr(u, "username", None):
                            all_usernames.append(u.username)

            sender_username: str | None = all_usernames[0] if all_usernames else None

            await router.route_incoming_message(
                chat_id=chat_id,
                message_id=message_id,
                sender_id=sender_id,
                sender_username=sender_username,
                text=text,
                is_private=is_private,
                is_group=is_group,
                is_self=is_self,
                all_usernames=all_usernames,
            )
        except Exception:
            logger.exception("Error handling Telegram event:")
