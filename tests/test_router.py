"""Unit tests for message routing, deduplication, and dispatching."""

from unittest.mock import AsyncMock

import pytest

from app.ai.provider import LLMProvider
from app.ai.response import ResponseSafetyValidator
from app.ai.soul_loader import SoulLoader
from app.anonymous.handler import AnonymousHandler
from app.config import Settings
from app.control.commands import ControlManager
from app.conversations.manager import ConversationManager
from app.conversations.memory import MemoryManager
from app.conversations.router import MessageRouter
from app.database.database import close_db, init_db


@pytest.fixture
async def router_setup(tmp_path):
    db_file = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    await init_db(db_url)

    soul_file = tmp_path / "soul.md"
    soul_file.write_text("Test Soul", encoding="utf-8")

    settings = Settings(
        DATABASE_URL=db_url,
        SOUL_PATH=soul_file,
        ANONYMOUS_BOT_USERNAME="anonrubot",
        GROUP_CHAT_AUTOPILOT=False,
        PRIVATE_CHAT_AUTOPILOT=False,
    )

    soul_loader = SoulLoader(soul_file)
    control_mgr = ControlManager(settings, soul_loader)
    conv_mgr = ConversationManager()
    llm_mock = AsyncMock(spec=LLMProvider)
    memory_mgr = MemoryManager(max_history=10)
    safety = ResponseSafetyValidator()
    anon_handler = AsyncMock(spec=AnonymousHandler)
    sender_mock = AsyncMock()

    router = MessageRouter(
        settings=settings,
        control_manager=control_mgr,
        conversation_manager=conv_mgr,
        anonymous_handler=anon_handler,
        telegram_sender=sender_mock,
        soul_loader=soul_loader,
        llm=llm_mock,
        memory_manager=memory_mgr,
        safety_validator=safety,
    )

    yield router, anon_handler, sender_mock

    await close_db()


@pytest.mark.asyncio
async def test_own_messages_ignored(router_setup):
    router, anon_handler, _ = router_setup

    await router.route_incoming_message(
        chat_id=123,
        message_id=1,
        sender_id=123,
        sender_username="anonrubot",
        text="Hello",
        is_private=True,
        is_group=False,
        is_self=True,
    )
    anon_handler.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_message_deduplication(router_setup):
    router, anon_handler, _ = router_setup

    # First delivery
    await router.route_incoming_message(
        chat_id=123,
        message_id=101,
        sender_id=123,
        sender_username="anonrubot",
        text="Привет",
        is_private=True,
        is_group=False,
        is_self=False,
    )
    assert anon_handler.handle_message.call_count == 1

    # Duplicate delivery of the exact same message
    await router.route_incoming_message(
        chat_id=123,
        message_id=101,
        sender_id=123,
        sender_username="anonrubot",
        text="Привет",
        is_private=True,
        is_group=False,
        is_self=False,
    )
    # Call count must still be 1
    assert anon_handler.handle_message.call_count == 1


@pytest.mark.asyncio
async def test_group_chat_ignored_when_disabled(router_setup):
    router, anon_handler, _ = router_setup

    await router.route_incoming_message(
        chat_id=456,
        message_id=201,
        sender_id=789,
        sender_username="user1",
        text="Hello everyone",
        is_private=False,
        is_group=True,
        is_self=False,
    )
    anon_handler.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_anonymous_bots_routed(router_setup):
    router, anon_handler, _ = router_setup

    # Test bot 1: anonrubot
    await router.route_incoming_message(
        chat_id=1001,
        message_id=1,
        sender_id=1001,
        sender_username="anonrubot",
        text="Собеседник найден",
        is_private=True,
        is_group=False,
        is_self=False,
    )
    assert anon_handler.handle_message.call_count == 1

    # Test bot 2: anonim
    await router.route_incoming_message(
        chat_id=1002,
        message_id=1,
        sender_id=1002,
        sender_username="anonim",
        text="Собеседник найден",
        is_private=True,
        is_group=False,
        is_self=False,
    )
    assert anon_handler.handle_message.call_count == 2

    # Normal private user should not go to anonymous handler
    await router.route_incoming_message(
        chat_id=1003,
        message_id=1,
        sender_id=1003,
        sender_username="regular_user",
        text="Привет",
        is_private=True,
        is_group=False,
        is_self=False,
    )
    assert anon_handler.handle_message.call_count == 2

    # Test bot by ID 8103812978 even when sender_username is None (Telegram collectible username case)
    await router.route_incoming_message(
        chat_id=8103812978,
        message_id=2,
        sender_id=8103812978,
        sender_username=None,
        text="Собеседник найден! Можете начинать общение.\n\n/next – следующий собеседник\n\nhttps://t.me/anonim",
        is_private=True,
        is_group=False,
        is_self=False,
    )
    assert anon_handler.handle_message.call_count == 3

    # Test bot by all_usernames list (collectible usernames)
    await router.route_incoming_message(
        chat_id=9999,
        message_id=3,
        sender_id=9999,
        sender_username=None,
        text="Собеседник найден",
        is_private=True,
        is_group=False,
        is_self=False,
        all_usernames=["chatxanonbot"],
    )
    assert anon_handler.handle_message.call_count == 4
