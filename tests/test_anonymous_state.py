"""Unit tests for the anonymous chat state machine and text detection."""

import pytest

from app.anonymous.commands import (
    is_bot_connection_notice,
    is_bot_disconnection_notice,
)
from app.anonymous.state_machine import AnonymousStateMachine
from app.database.models import ConversationStateEnum
from app.utils.text import extract_age, extract_telegram_username


def test_new_conversation_greetings():
    """Verify new anonymous conversations trigger greeting 'Привет.' and gender query 'М или Д?'."""
    result = AnonymousStateMachine.process_new_conversation()
    assert result.next_state == ConversationStateEnum.WAITING_FOR_GENDER
    assert result.outgoing_messages == ["Привет.", "М или Д?"]
    assert not result.should_invoke_llm
    assert not result.should_send_next


@pytest.mark.parametrize(
    "male_input",
    [
        "м",
        "М",
        "м 20",
        "м19",
        "м18",
        "м21",
        "привет М",
        "привет м",
        "Привет М",
        "привет м 20",
        "я парень",
        "пацан",
        "парнишка",
        "мужчина",
        "ищу очень пошлую д",
        "Влад",
        "влад",
        "я Влад",
        "меня зовут Влад",
        "Влад 20",
        "Дима",
    ],
)
def test_waiting_for_gender_male_skips(male_input):
    """Verify male participants receive /next and conversation is stopped."""
    result = AnonymousStateMachine.process_waiting_for_gender(male_input)
    assert result.next_state == ConversationStateEnum.STOPPED
    assert result.outgoing_messages == ["/next"]
    assert result.should_send_next is True
    assert result.is_stopped is True
    assert result.detected_gender == "M"
    assert not result.should_invoke_llm


@pytest.mark.parametrize(
    "female_input",
    [
        "д",
        "Д",
        "ж",
        "девушка",
        "девочка 19",
        "я тян",
        "привет Д 20",
        "привет д",
        "Привет Д",
        "Привет д 20",
        "д19",
        "Д19",
        "д20",
        "д 19",
        "ищу парня",
        "ищу м",
        "Кира",
        "кира",
        "Вика",
        "вика",
        "я Кира",
        "Вика 19",
        "меня зовут Кира",
        "Аня",
    ],
)
def test_waiting_for_gender_female_promotes_active(female_input):
    """Verify female participants transition state to ACTIVE and receive immediate gender and age question/matching as separate short messages."""
    from app.utils.text import extract_age, match_owner_age

    result = AnonymousStateMachine.process_waiting_for_gender(female_input)
    assert result.next_state == ConversationStateEnum.ACTIVE
    assert result.is_stopped is False
    assert result.detected_gender == "F"
    assert len(result.outgoing_messages) == 2

    age = extract_age(female_input)
    if age:
        expected_owner_age = match_owner_age(age)
        assert result.outgoing_messages == [f"Я М, мне {expected_owner_age})", "Чем занимаешься?"]
    else:
        assert result.outgoing_messages == ["Я М)", "Сколько тебе лет?"]


def test_split_into_messages():
    """Verify messages with newlines or multiple sentences are split into separate short chat bubbles."""
    from app.utils.text import split_into_messages

    assert split_into_messages("Я М)\nСколько тебе лет?") == ["Я М)", "Сколько тебе лет?"]
    assert split_into_messages("Да норм. А ты чем маешься?") == ["Да норм.", "А ты чем маешься?"]
    assert split_into_messages("Привет") == ["Привет"]
    assert split_into_messages("") == []


def test_match_owner_age():
    """Verify owner age matching produces natural ages matching female partner."""
    from app.utils.text import match_owner_age

    assert match_owner_age(17) == 18
    assert match_owner_age(18) == 19
    assert match_owner_age(19) == 20
    assert match_owner_age(20) == 21
    assert match_owner_age(21) == 22
    assert match_owner_age(22) == 23
    assert match_owner_age(23) == 24
    assert match_owner_age(24) == 25
    assert match_owner_age(25) == 25


def test_typing_delay():
    """Verify dynamic typing delay scales between 3.0 and 10.0 seconds based on length."""
    from unittest.mock import MagicMock
    from app.telegram.sender import TelegramSender

    settings = MagicMock()
    settings.MIN_REPLY_DELAY_SECONDS = 3.0
    settings.MAX_REPLY_DELAY_SECONDS = 10.0

    sender = TelegramSender(client=MagicMock(), settings=settings, media_manager=MagicMock())

    # Short message
    short_delay = sender._calculate_typing_delay("М")
    assert 3.0 <= short_delay <= 5.0

    # Long message
    long_msg = "Привет! Как твои дела? Чем занимаешься сегодня вечером? Какие планы на выходные?"
    long_delay = sender._calculate_typing_delay(long_msg)
    assert 6.0 <= long_delay <= 10.0
    assert long_delay >= short_delay


def test_extract_name():
    """Verify recognized Russian names are properly extracted."""
    from app.utils.text import extract_name

    assert extract_name("Кира") == "Кира"
    assert extract_name("я Кира") == "Кира"
    assert extract_name("меня зовут Вика") == "Вика"
    assert extract_name("Вика, 19") == "Вика"
    assert extract_name("Влад") == "Влад"
    assert extract_name("я Влад 20") == "Влад"
    assert extract_name("привет") is None


@pytest.mark.parametrize(
    "ask_input",
    [
        "мд",
        "МД",
        "м/д",
        "м или д",
        "м или д?",
        "м или ж",
        "пол?",
        "пол",
        "ты кто?",
        "парень или девушка?",
    ],
)
def test_waiting_for_gender_asks_gender_answers_m(ask_input):
    """Verify when partner asks 'мд' or 'м или д', assistant answers 'М' and waits."""
    result = AnonymousStateMachine.process_waiting_for_gender(ask_input)
    assert result.next_state == ConversationStateEnum.WAITING_FOR_GENDER
    assert result.outgoing_messages == ["М"]
    assert not result.should_invoke_llm
    assert result.detected_gender is None


@pytest.mark.parametrize("other_input", ["Привет, как дела?", "а ты откуда?", "хз", "18", "че делаешь?"])
def test_waiting_for_gender_other_text_silent_wait(other_input):
    """Verify non-gender answers do not trigger robotic clarification prompts, but wait silently."""
    result = AnonymousStateMachine.process_waiting_for_gender(other_input)
    assert result.next_state == ConversationStateEnum.WAITING_FOR_GENDER
    assert result.outgoing_messages == []
    assert not result.should_invoke_llm
    assert result.detected_gender is None


def test_extract_age():
    """Verify extraction of age from various user input formats."""
    assert extract_age("д19") == 19
    assert extract_age("Д19") == 19
    assert extract_age("привет Д 20") == 20
    assert extract_age("м18") == 18
    assert extract_age("девушка, 23 года") == 23
    assert extract_age("мне 21 год") == 21
    assert extract_age("просто текст") is None


@pytest.mark.parametrize(
    "disconnect_text",
    [
        "Напишите /search чтобы искать собеседника",
        "напишите /search чтобы искать собеседника",
        "Собеседник покинул диалог. Напишите /search чтобы искать собеседника",
        "Собеседник завершил диалог",
        "напишите /search чтобы найти следующего",
        "Диалог завершен",
        "связь прервана",
        "собеседник отключился",
    ],
)
def test_bot_disconnection_notices(disconnect_text):
    """Verify disconnection system messages from the anonymous bot are recognized."""
    assert is_bot_disconnection_notice(disconnect_text) is True


@pytest.mark.parametrize(
    "connect_text",
    [
        "Собеседник найден",
        "Собеседник найден\n\n/next — искать нового собеседника\n/stop",
        "Партнёр найден",
        "Партнер найден",
        "Вы подключились к диалогу",
        "диалог начат",
    ],
)
def test_bot_connection_notices(connect_text):
    """Verify connection system messages from the anonymous bot are recognized."""
    assert is_bot_connection_notice(connect_text) is True


@pytest.mark.parametrize(
    "service_text",
    [
        "Ищем собеседника...",
        "ищу собеседника",
        "Поиск собеседника",
        "Если хотите, оставьте мнение о вашем собеседнике. Это поможет...",
        "Оцените собеседника",
        "Остановить поиск",
        "У вас уже есть собеседник 🤔\n/next — искать нового собеседника",
        "помогу тебе \nSoni921\nне бот",
    ],
)
def test_bot_service_notices(service_text):
    """Verify intermediate bot service and status messages are recognized to prevent false replies."""
    from app.anonymous.commands import is_bot_service_notice

    assert is_bot_service_notice(service_text) is True


def test_enough_hard_stop():
    """Verify /enough immediately hard-stops without sending /next."""
    result = AnonymousStateMachine.process_enough()
    assert result.next_state == ConversationStateEnum.STOPPED
    assert result.outgoing_messages == []
    assert not result.should_send_next
    assert result.is_stopped is True


def test_username_extraction():
    """Verify extraction of Telegram handles from message text."""
    assert extract_telegram_username("пиши мне в телегу @ann_sweet") == "@ann_sweet"
    assert extract_telegram_username("мой тг t.me/alice_wonder") == "@alice_wonder"
    assert extract_telegram_username("просто текст без ников") is None


@pytest.mark.asyncio
async def test_notify_female_found():
    """Verify notification is sent to designated username when a female partner is found."""
    from unittest.mock import AsyncMock, MagicMock
    from app.anonymous.handler import AnonymousHandler
    from app.database.models import Conversation, ConversationStateDetails

    settings = MagicMock()
    settings.NOTIFY_ON_FEMALE_FOUND = True
    settings.NOTIFY_FEMALE_USERNAME = "@theilerr"

    handler = AnonymousHandler(
        settings=settings,
        soul_loader=MagicMock(),
        llm=MagicMock(),
        memory_manager=MagicMock(),
        safety_validator=MagicMock(),
    )

    conv = Conversation(id=42, telegram_chat_id=12345)
    conv.details = ConversationStateDetails(conversation_id=42)

    mock_sender = AsyncMock()

    # First notification should send message
    await handler._notify_female_found(conv, name="Кира", age=19, sender=mock_sender)
    assert mock_sender.send_text.call_count == 1
    call_args = mock_sender.send_text.call_args[0]
    assert call_args[0] == "@theilerr"
    assert "Кира" in call_args[1]
    assert "19" in call_args[1]
    assert "42" in call_args[1]

    # Second call should be deduplicated (not sent again)
    await handler._notify_female_found(conv, name="Кира", age=19, sender=mock_sender)
    assert mock_sender.send_text.call_count == 1
