"""Data access layer isolating SQL operations."""

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    ControlEvent,
    Conversation,
    ConversationStateDetails,
    ConversationStateEnum,
    ConversationSummary,
    ConversationTypeEnum,
    MediaRegistry,
    Message,
    MessageDirectionEnum,
    ProcessedUpdate,
    SenderTypeEnum,
    utc_now,
)

logger = logging.getLogger(__name__)


class Repository:
    """Repository wrapping database interactions for conversations, messages, and state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------ Deduplication ------------------
    async def is_message_processed(self, chat_id: int, message_id: int) -> bool:
        stmt = select(ProcessedUpdate).where(
            ProcessedUpdate.chat_id == chat_id,
            ProcessedUpdate.message_id == message_id,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none() is not None

    async def mark_message_processed(self, chat_id: int, message_id: int) -> None:
        processed = ProcessedUpdate(chat_id=chat_id, message_id=message_id)
        self.session.add(processed)
        await self.session.flush()

    # ------------------ Conversations ------------------
    async def get_or_create_conversation(
        self,
        telegram_chat_id: int,
        conv_type: ConversationTypeEnum,
    ) -> Conversation:
        """Fetch the latest active/open conversation for this chat or create a new one."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.telegram_chat_id == telegram_chat_id,
                Conversation.state.notin_([ConversationStateEnum.STOPPED]),
            )
            .order_by(Conversation.id.desc())
            .options(
                selectinload(Conversation.details),
                selectinload(Conversation.summary),
            )
        )
        res = await self.session.execute(stmt)
        conv = res.scalars().first()

        if not conv:
            conv = await self.create_new_conversation(telegram_chat_id, conv_type)
        elif conv.type != conv_type:
            logger.info(
                f"Upgrading conversation {conv.id} type from {conv.type.value} to {conv_type.value}"
            )
            conv.type = conv_type
            await self.session.flush()

        return conv

    async def create_new_conversation(
        self,
        telegram_chat_id: int,
        conv_type: ConversationTypeEnum,
    ) -> Conversation:
        """Explicitly create a brand new conversation instance, stopping any prior open ones."""
        # Stop any older open conversations for this chat
        stmt = (
            select(Conversation)
            .where(
                Conversation.telegram_chat_id == telegram_chat_id,
                Conversation.state.notin_([ConversationStateEnum.STOPPED]),
            )
        )
        res = await self.session.execute(stmt)
        for old_conv in res.scalars().all():
            old_conv.state = ConversationStateEnum.STOPPED
        await self.session.flush()

        conv = Conversation(
            telegram_chat_id=telegram_chat_id,
            type=conv_type,
            state=ConversationStateEnum.NEW,
        )
        self.session.add(conv)
        await self.session.flush()

        details = ConversationStateDetails(conversation_id=conv.id)
        self.session.add(details)
        await self.session.flush()
        conv.details = details
        return conv

    async def get_conversation_by_id(self, conv_id: int) -> Conversation | None:
        stmt = (
            select(Conversation)
            .where(Conversation.id == conv_id)
            .options(
                selectinload(Conversation.details),
                selectinload(Conversation.summary),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_conversation_state(self, conv_id: int, state: ConversationStateEnum) -> None:
        stopped_at = utc_now() if state == ConversationStateEnum.STOPPED else None
        stmt = (
            update(Conversation)
            .where(Conversation.id == conv_id)
            .values(state=state, updated_at=utc_now(), stopped_at=stopped_at)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_conversation_details(
        self,
        conv_id: int,
        gender: str | None = None,
        intent: str | None = None,
        participant_age: int | None = None,
        telegram_username: str | None = None,
        telegram_shared: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        stmt = select(ConversationStateDetails).where(
            ConversationStateDetails.conversation_id == conv_id
        )
        res = await self.session.execute(stmt)
        details = res.scalar_one_or_none()

        if not details:
            details = ConversationStateDetails(conversation_id=conv_id)
            self.session.add(details)

        if gender is not None:
            details.gender = gender
        if intent is not None:
            details.intent = intent
        if participant_age is not None:
            details.participant_age = participant_age
        if telegram_username is not None:
            details.telegram_username = telegram_username
        if telegram_shared is not None:
            details.telegram_shared = telegram_shared
        if metadata is not None:
            details.set_metadata(metadata)

        await self.session.flush()

    # ------------------ Messages ------------------
    async def add_message(
        self,
        conversation_id: int,
        telegram_message_id: int,
        sender_id: int,
        sender_type: SenderTypeEnum,
        text: str,
        direction: MessageDirectionEnum,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            telegram_message_id=telegram_message_id,
            sender_id=sender_id,
            sender_type=sender_type,
            text=text,
            direction=direction,
            timestamp=utc_now(),
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def get_recent_messages(self, conversation_id: int, limit: int = 30) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        messages = list(res.scalars().all())
        messages.reverse()  # Return in chronological order
        return messages

    # ------------------ Summaries ------------------
    async def get_conversation_summary(self, conversation_id: int) -> str | None:
        stmt = select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id
        )
        res = await self.session.execute(stmt)
        summary = res.scalar_one_or_none()
        return summary.summary_text if summary else None

    async def save_conversation_summary(
        self,
        conversation_id: int,
        summary_text: str,
        last_message_id: int | None = None,
    ) -> None:
        stmt = select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id
        )
        res = await self.session.execute(stmt)
        summary = res.scalar_one_or_none()

        if not summary:
            summary = ConversationSummary(
                conversation_id=conversation_id,
                summary_text=summary_text,
                last_summarized_message_id=last_message_id,
            )
            self.session.add(summary)
        else:
            summary.summary_text = summary_text
            summary.last_summarized_message_id = last_message_id
            summary.updated_at = utc_now()

        await self.session.flush()

    # ------------------ Media Registry ------------------
    async def get_media_by_alias(self, alias: str) -> MediaRegistry | None:
        stmt = select(MediaRegistry).where(MediaRegistry.alias == alias)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def register_media(
        self,
        alias: str,
        file_id_or_path: str,
        media_type: str = "photo",
        description: str | None = None,
    ) -> MediaRegistry:
        existing = await self.get_media_by_alias(alias)
        if existing:
            existing.file_id_or_path = file_id_or_path
            existing.media_type = media_type
            existing.description = description
            await self.session.flush()
            return existing

        media = MediaRegistry(
            alias=alias,
            file_id_or_path=file_id_or_path,
            media_type=media_type,
            description=description,
        )
        self.session.add(media)
        await self.session.flush()
        return media

    # ------------------ Control Events ------------------
    async def log_control_event(
        self, command: str, user_id: int, details: str | None = None
    ) -> None:
        event = ControlEvent(command=command, user_id=user_id, details=details, timestamp=utc_now())
        self.session.add(event)
        await self.session.flush()
