"""Unit tests for memory management, summarization, and AI response validation."""

from unittest.mock import AsyncMock

import pytest

from app.ai.provider import LLMProvider
from app.ai.response import (
    ActionType,
    AIResponse,
    ResponseSafetyValidator,
    parse_ai_json_output,
)
from app.conversations.memory import MemoryManager
from app.database.database import close_db, get_db_session, init_db
from app.database.models import (
    ConversationTypeEnum,
    MessageDirectionEnum,
    SenderTypeEnum,
)
from app.database.repository import Repository


@pytest.fixture
async def db_setup(tmp_path):
    db_file = tmp_path / "memory_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    await init_db(db_url)
    yield db_url
    await close_db()


@pytest.mark.asyncio
async def test_memory_sliding_window(db_setup):
    async with get_db_session(db_setup) as session:
        repo = Repository(session)
        conv = await repo.get_or_create_conversation(1001, ConversationTypeEnum.ANONYMOUS_CHAT)

        for i in range(10):
            await repo.add_message(
                conversation_id=conv.id,
                telegram_message_id=i,
                sender_id=1001,
                sender_type=SenderTypeEnum.PARTICIPANT,
                text=f"Message {i}",
                direction=MessageDirectionEnum.INCOMING,
            )

        mgr = MemoryManager(max_history=5)
        _summary, history = await mgr.get_recent_history(repo, conv.id)

        assert len(history) == 5
        assert history[0]["text"] == "Message 5"
        assert history[-1]["text"] == "Message 9"


@pytest.mark.asyncio
async def test_summarization_trigger(db_setup):
    async with get_db_session(db_setup) as session:
        repo = Repository(session)
        conv = await repo.get_or_create_conversation(1002, ConversationTypeEnum.ANONYMOUS_CHAT)

        for i in range(15):
            await repo.add_message(
                conversation_id=conv.id,
                telegram_message_id=i,
                sender_id=1002,
                sender_type=SenderTypeEnum.PARTICIPANT,
                text=f"Chat message {i}",
                direction=MessageDirectionEnum.INCOMING,
            )

        llm_mock = AsyncMock(spec=LLMProvider)
        llm_mock.generate_summary.return_value = "Summary: Discussed various topics."

        mgr = MemoryManager(max_history=5)
        await mgr.check_and_summarize(repo, llm_mock, conv.id)

        llm_mock.generate_summary.assert_called_once()
        saved_summary = await repo.get_conversation_summary(conv.id)
        assert saved_summary == "Summary: Discussed various topics."


def test_parse_ai_json_output():
    # Raw JSON
    raw_1 = '{"action": "reply", "text": "Привет! Как дела?", "confidence": 0.9}'
    parsed_1 = parse_ai_json_output(raw_1)
    assert parsed_1 is not None
    assert parsed_1.action == ActionType.REPLY
    assert parsed_1.text == "Привет! Как дела?"

    # Markdown fenced JSON
    raw_2 = '```json\n{"action": "next", "reason": "Not interested"}\n```'
    parsed_2 = parse_ai_json_output(raw_2)
    assert parsed_2 is not None
    assert parsed_2.action == ActionType.NEXT
    assert parsed_2.reason == "Not interested"

    # Plain text fallback
    raw_3 = "Just some text with no json"
    parsed_3 = parse_ai_json_output(raw_3)
    assert parsed_3 is not None
    assert parsed_3.action == ActionType.REPLY
    assert parsed_3.text == "Just some text with no json"

    # Empty string
    assert parse_ai_json_output("") is None


def test_safety_validator_leaks():
    validator = ResponseSafetyValidator(forbidden_secrets=["SECRET_API_KEY_12345"])

    # Normal clean message
    resp_clean = AIResponse(action=ActionType.REPLY, text="Привет, приятно познакомиться!")
    is_safe, _, _ = validator.validate_and_clean(resp_clean)
    assert is_safe is True

    # Leaking secret
    resp_leak = AIResponse(action=ActionType.REPLY, text="Here is key: SECRET_API_KEY_12345")
    is_safe, reason, _ = validator.validate_and_clean(resp_leak)
    assert is_safe is False
    assert "Secret leak" in reason

    # Leaking system prompt marker
    resp_marker = AIResponse(action=ActionType.REPLY, text="RULES: You must be friendly")
    is_safe, reason, _ = validator.validate_and_clean(resp_marker)
    assert is_safe is False
