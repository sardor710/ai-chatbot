"""Message router directing incoming Telegram events through deduplication, safety, and handlers."""

import logging

from app.ai.prompts import build_conversation_context, build_system_prompt
from app.ai.provider import LLMProvider
from app.ai.response import ActionType, ResponseSafetyValidator
from app.ai.soul_loader import SoulLoader
from app.anonymous.commands import CMD_ENOUGH
from app.anonymous.handler import AnonymousHandler
from app.config import Settings
from app.control.commands import ControlManager
from app.conversations.manager import ConversationManager
from app.conversations.memory import MemoryManager
from app.database.database import get_db_session
from app.database.models import (
    Conversation,
    ConversationStateEnum,
    ConversationTypeEnum,
    MessageDirectionEnum,
    SenderTypeEnum,
)
from app.database.repository import Repository
from app.telegram.sender import TelegramSender

logger = logging.getLogger(__name__)


class MessageRouter:
    """Classifies incoming Telegram messages and delegates them to specialized handlers."""

    def __init__(
        self,
        settings: Settings,
        control_manager: ControlManager,
        conversation_manager: ConversationManager,
        anonymous_handler: AnonymousHandler,
        telegram_sender: TelegramSender,
        soul_loader: SoulLoader,
        llm: LLMProvider,
        memory_manager: MemoryManager,
        safety_validator: ResponseSafetyValidator,
    ) -> None:
        self.settings = settings
        self.control_manager = control_manager
        self.conversation_manager = conversation_manager
        self.anonymous_handler = anonymous_handler
        self.telegram_sender = telegram_sender
        self.soul_loader = soul_loader
        self.llm = llm
        self.memory_manager = memory_manager
        self.safety_validator = safety_validator
        self.anonymous_bot_ids: set[int] = set(self.settings.get_anonymous_bot_ids())

    def register_anonymous_bot_id(self, bot_id: int) -> None:
        """Register a known anonymous bot Telegram chat/user ID."""
        self.anonymous_bot_ids.add(bot_id)

    async def route_incoming_message(
        self,
        chat_id: int,
        message_id: int,
        sender_id: int,
        sender_username: str | None,
        text: str,
        is_private: bool,
        is_group: bool,
        is_self: bool,
        all_usernames: list[str] | None = None,
    ) -> None:
        """Route an incoming message event."""
        # Check for owner commands even if sent from own account (e.g. in Saved Messages or any chat)
        if text.startswith("/"):
            async with get_db_session(self.settings.DATABASE_URL) as session:
                repo = Repository(session)
                handled, reply = await self.control_manager.handle_control_command(
                    command_text=text,
                    user_id=sender_id,
                    username=sender_username,
                    repo=repo,
                )
                if handled:
                    if reply:
                        await self.telegram_sender.send_text(chat_id, reply)
                    return

        # 1. Do not process ordinary conversational messages sent by our own account
        if is_self:
            return

        async with get_db_session(self.settings.DATABASE_URL) as session:
            repo = Repository(session)

            # 2. Message Deduplication
            if await repo.is_message_processed(chat_id, message_id):
                logger.debug(f"Ignoring duplicate update for chat {chat_id}, message {message_id}")
                return
            await repo.mark_message_processed(chat_id, message_id)

            # 4. Check if application is paused
            if self.control_manager.is_paused:
                logger.info(f"App is paused. Skipping message from chat {chat_id}")
                return

            # 5. Determine Conversation Type
            is_anon_bot = (
                chat_id in self.anonymous_bot_ids
                or sender_id in self.anonymous_bot_ids
                or self.settings.is_anonymous_bot(sender_username, chat_id=chat_id)
                or (
                    all_usernames
                    and any(self.settings.is_anonymous_bot(u) for u in all_usernames)
                )
                or (
                    is_private
                    and (
                        "t.me/anonim" in text.lower()
                        or "t.me/anonrubot" in text.lower()
                        or "t.me/chatxanonbot" in text.lower()
                    )
                )
            )

            if is_anon_bot:
                self.anonymous_bot_ids.add(chat_id)
                self.anonymous_bot_ids.add(sender_id)
                conv_type = ConversationTypeEnum.ANONYMOUS_CHAT
            elif is_private:
                conv_type = ConversationTypeEnum.PRIVATE_CHAT
            elif is_group:
                conv_type = ConversationTypeEnum.GROUP_CHAT
            else:
                conv_type = ConversationTypeEnum.UNKNOWN

            # Ignore unknown or disabled group chats
            if conv_type == ConversationTypeEnum.UNKNOWN:
                return

            if (
                conv_type == ConversationTypeEnum.GROUP_CHAT
                and not self.settings.GROUP_CHAT_AUTOPILOT
            ):
                logger.debug(
                    f"Group chat message from {chat_id} ignored (GROUP_CHAT_AUTOPILOT is disabled)."
                )
                return

            # 6. Retrieve or Create Conversation
            conversation = await repo.get_or_create_conversation(chat_id, conv_type)

            # Record incoming message in database
            await repo.add_message(
                conversation_id=conversation.id,
                telegram_message_id=message_id,
                sender_id=sender_id,
                sender_type=SenderTypeEnum.PARTICIPANT if not is_anon_bot else SenderTypeEnum.BOT,
                text=text,
                direction=MessageDirectionEnum.INCOMING,
            )

            # 7. Route to Handler with Conversation Lock
            lock = self.conversation_manager.get_lock(conversation.id)
            async with lock:
                if conv_type == ConversationTypeEnum.ANONYMOUS_CHAT:
                    await self.anonymous_handler.handle_message(
                        repo=repo,
                        conversation=conversation,
                        incoming_text=text,
                        sender=self.telegram_sender,
                    )
                elif conv_type == ConversationTypeEnum.PRIVATE_CHAT:
                    await self._handle_private_chat(repo, conversation, text)

    async def _handle_private_chat(
        self,
        repo: Repository,
        conversation: Conversation,
        text: str,
    ) -> None:
        """Handle normal Telegram private chats."""
        if not self.settings.PRIVATE_CHAT_AUTOPILOT:
            logger.info(
                f"[PRIVATE CHAT] Received message in chat {conversation.telegram_chat_id} (Autopilot disabled, message stored)."
            )
            return

        if text.strip().lower() == CMD_ENOUGH:
            await repo.update_conversation_state(conversation.id, ConversationStateEnum.STOPPED)
            logger.info(f"Private conversation {conversation.id} stopped via {CMD_ENOUGH}.")
            return

        # Prepare context and LLM response
        summary, recent_history = await self.memory_manager.get_recent_history(
            repo, conversation.id
        )
        state_info = {
            "type": conversation.type.value,
            "state": conversation.state.value,
            "gender": conversation.details.gender if conversation.details else None,
        }

        system_prompt = build_system_prompt(self.soul_loader.content)
        user_context = build_conversation_context(
            state_info=state_info,
            summary=summary,
            recent_messages=recent_history,
            owner_username=self.settings.OWNER_USERNAME,
        )

        ai_response = await self.llm.generate_response(
            system_prompt=system_prompt,
            user_prompt=user_context,
            max_tokens=self.settings.MAX_RESPONSE_TOKENS,
        )

        if not ai_response:
            return

        is_safe, reason, cleaned = self.safety_validator.validate_and_clean(ai_response)
        if not is_safe:
            logger.error(f"Private chat response safety violation: {reason}")
            return

        if cleaned.action == ActionType.REPLY and cleaned.text:
            await self.telegram_sender.send_text(conversation.telegram_chat_id, cleaned.text)
            await repo.add_message(
                conversation_id=conversation.id,
                telegram_message_id=0,
                sender_id=conversation.telegram_chat_id,
                sender_type=SenderTypeEnum.OWNER,
                text=cleaned.text,
                direction=MessageDirectionEnum.OUTGOING,
            )
