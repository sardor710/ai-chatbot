"""State machine for anonymous chat partner evaluation and workflow progression."""

import logging
from dataclasses import dataclass

from app.database.models import ConversationStateEnum
from app.utils.text import (
    detect_gender_from_response,
    extract_age,
    is_asking_for_gender,
    is_greeting_only,
    match_owner_age,
)

logger = logging.getLogger(__name__)


@dataclass
class TransitionResult:
    """Outcome of evaluating an incoming message in the state machine."""

    next_state: ConversationStateEnum
    outgoing_messages: list[str]
    should_invoke_llm: bool
    should_send_next: bool
    is_stopped: bool
    detected_gender: str | None = None


class AnonymousStateMachine:
    """Manages explicit state transitions for @anonrubot conversations."""

    @staticmethod
    def process_new_conversation() -> TransitionResult:
        """
        Action when a brand new anonymous chat is opened.
        Sends greeting 'Привет.' then 'М или Д?' and waits for gender response.
        """
        return TransitionResult(
            next_state=ConversationStateEnum.WAITING_FOR_GENDER,
            outgoing_messages=["Привет.", "М или Д?"],
            should_invoke_llm=False,
            should_send_next=False,
            is_stopped=False,
        )

    @staticmethod
    def process_waiting_for_gender(incoming_text: str) -> TransitionResult:
        """
        Evaluate partner response to 'М или Д?'.
        - Male ('M'): skip via /next, stop this conversation.
        - Female ('F'): promote to ACTIVE, immediately reply with gender M and age (or ask age).
        - Partner asks our gender ('мд', 'м или д', 'пол?', etc.): answer 'М'.
        - Other: do not send any clarification prompt. Wait for gender.
        """
        gender = detect_gender_from_response(incoming_text)

        if gender == "M":
            logger.info("Participant identified as Male. Skipping with /next.")
            return TransitionResult(
                next_state=ConversationStateEnum.STOPPED,
                outgoing_messages=["/next"],
                should_invoke_llm=False,
                should_send_next=True,
                is_stopped=True,
                detected_gender="M",
            )
        elif gender == "F":
            logger.info("Participant identified as Female. Transitioning to ACTIVE.")
            detected_age = extract_age(incoming_text)
            if detected_age:
                my_age = match_owner_age(detected_age)
                replies = [f"Я М, мне {my_age})", "Чем занимаешься?"]
            else:
                replies = ["Я М)", "Сколько тебе лет?"]

            return TransitionResult(
                next_state=ConversationStateEnum.ACTIVE,
                outgoing_messages=replies,
                should_invoke_llm=False,
                should_send_next=False,
                is_stopped=False,
                detected_gender="F",
            )
        elif is_asking_for_gender(incoming_text):
            logger.info("Participant asked for our gender ('мд' / 'м или д'). Answering 'М'.")
            return TransitionResult(
                next_state=ConversationStateEnum.WAITING_FOR_GENDER,
                outgoing_messages=["М"],
                should_invoke_llm=False,
                should_send_next=False,
                is_stopped=False,
                detected_gender=None,
            )
        else:
            logger.info("Participant response does not specify gender. Waiting without repeating prompts.")
            return TransitionResult(
                next_state=ConversationStateEnum.WAITING_FOR_GENDER,
                outgoing_messages=[],
                should_invoke_llm=False,
                should_send_next=False,
                is_stopped=False,
                detected_gender=None,
            )

    @staticmethod
    def process_enough() -> TransitionResult:
        """
        Handle /enough hard stop:
        - Immediately mark conversation as STOPPED
        - Do not send /next
        - Do not invoke LLM
        """
        logger.info("/enough triggered: hard stopping conversation.")
        return TransitionResult(
            next_state=ConversationStateEnum.STOPPED,
            outgoing_messages=[],
            should_invoke_llm=False,
            should_send_next=False,
            is_stopped=True,
        )
