"""SQLAlchemy database models for persistence."""

import enum
import json
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative model."""


class ConversationTypeEnum(str, enum.Enum):
    ANONYMOUS_CHAT = "ANONYMOUS_CHAT"
    PRIVATE_CHAT = "PRIVATE_CHAT"
    GROUP_CHAT = "GROUP_CHAT"
    UNKNOWN = "UNKNOWN"


class ConversationStateEnum(str, enum.Enum):
    NEW = "NEW"
    WAITING_FOR_GENDER = "WAITING_FOR_GENDER"
    ACTIVE = "ACTIVE"
    ENDING = "ENDING"
    STOPPED = "STOPPED"
    WAITING_FOR_NEXT = "WAITING_FOR_NEXT"


class MessageDirectionEnum(str, enum.Enum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"


class SenderTypeEnum(str, enum.Enum):
    OWNER = "OWNER"
    PARTICIPANT = "PARTICIPANT"
    BOT = "BOT"
    SYSTEM = "SYSTEM"


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    type: Mapped[ConversationTypeEnum] = mapped_column(
        SQLEnum(ConversationTypeEnum), default=ConversationTypeEnum.UNKNOWN
    )
    state: Mapped[ConversationStateEnum] = mapped_column(
        SQLEnum(ConversationStateEnum), default=ConversationStateEnum.NEW
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )
    details: Mapped[Optional["ConversationStateDetails"]] = relationship(
        "ConversationStateDetails",
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
    )
    summary: Mapped[Optional["ConversationSummary"]] = relationship(
        "ConversationSummary",
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ConversationStateDetails(Base):
    __tablename__ = "conversation_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    participant_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="details")

    def get_metadata(self) -> dict[str, Any]:
        try:
            return json.loads(self.metadata_json or "{}")
        except Exception:
            return {}

    def set_metadata(self, data: dict[str, Any]) -> None:
        self.metadata_json = json.dumps(data, ensure_ascii=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[int] = mapped_column(BigInteger)
    sender_type: Mapped[SenderTypeEnum] = mapped_column(SQLEnum(SenderTypeEnum))
    text: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    direction: Mapped[MessageDirectionEnum] = mapped_column(SQLEnum(MessageDirectionEnum))

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    summary_text: Mapped[str] = mapped_column(Text, default="")
    last_summarized_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="summary")


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class ControlEvent(Base):
    __tablename__ = "control_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    command: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(BigInteger)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)


class MediaRegistry(Base):
    __tablename__ = "media_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )  # e.g., 'PHOTO_1', 'PHOTO_2'
    file_id_or_path: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(32), default="photo")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
