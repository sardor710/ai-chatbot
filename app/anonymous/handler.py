"""Handler orchestrating anonymous chat messages, state transitions, and LLM responses."""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from app.ai.prompts import build_conversation_context, build_system_prompt
from app.ai.provider import LLMProvider
from app.ai.response import ActionType, ResponseSafetyValidator
from app.ai.soul_loader import SoulLoader
from app.anonymous.commands import (
    CMD_ENOUGH,
    CMD_NEXT,
    CMD_SEARCH,
    is_bot_connection_notice,
    is_bot_disconnection_notice,
    is_bot_service_notice,
)
from app.anonymous.state_machine import AnonymousStateMachine
from app.config import Settings
from app.conversations.memory import MemoryManager
from app.database.models import (
    Conversation,
    ConversationStateEnum,
    MessageDirectionEnum,
    SenderTypeEnum,
)
from app.database.repository import Repository
from app.utils.text import (
    extract_age,
    extract_name,
    extract_telegram_username,
    match_owner_age,
    split_into_messages,
)

logger = logging.getLogger(__name__)


class AnySenderInterface(Protocol):
    """Sender protocol for typing and decoupling."""

    async def send_text(self, chat_id: int | str, text: str) -> bool: ...
    async def send_photo(self, chat_id: int | str, photo_alias: str) -> bool: ...


class AnonymousHandler:
    """Handles messages within the anonymous chat bot context (@anonrubot)."""

    def __init__(
        self,
        settings: Settings,
        soul_loader: SoulLoader,
        llm: LLMProvider,
        memory_manager: MemoryManager,
        safety_validator: ResponseSafetyValidator,
        dashboard_server: Any = None,
    ) -> None:
        self.settings = settings
        self.soul_loader = soul_loader
        self.llm = llm
        self.memory_manager = memory_manager
        self.safety_validator = safety_validator
        self.dashboard_server = dashboard_server
        self._last_search_time: float = 0.0

    async def handle_message(
        self,
        repo: Repository,
        conversation: Conversation,
        incoming_text: str,
        sender: AnySenderInterface,
    ) -> None:
        """Process incoming anonymous chat message through the state machine and AI."""
        text = incoming_text.strip()
        logger.info(
            f"Processing anonymous chat (Conv ID: {conversation.id}, State: {conversation.state.value}): '{text[:60]}'"
        )

        # 1. Hard Stop Command (/enough)
        if text.lower() == CMD_ENOUGH:
            transition = AnonymousStateMachine.process_enough()
            await repo.update_conversation_state(conversation.id, transition.next_state)
            conversation.state = transition.next_state
            logger.info(f"Conversation {conversation.id} stopped via {CMD_ENOUGH}.")
            return

        # 2. Check for Bot System Disconnection Notice
        if is_bot_disconnection_notice(text):
            logger.info("Bot announced partner disconnected. Marking conversation as STOPPED and auto-searching next...")
            await repo.update_conversation_state(conversation.id, ConversationStateEnum.STOPPED)
            conversation.state = ConversationStateEnum.STOPPED

            now = time.monotonic()
            if now - self._last_search_time > 2.0:
                self._last_search_time = now
                logger.info(f"Sending {CMD_SEARCH} to start new conversation...")
                await sender.send_text(conversation.telegram_chat_id, CMD_SEARCH)
            else:
                logger.info(f"{CMD_SEARCH} recently sent, skipping duplicate trigger.")
            if self.dashboard_server:
                self.dashboard_server.broadcast_update(event_type="update")
            return

        # 3. Check for Bot System Connection Notice ("Собеседник найден", etc.)
        if is_bot_connection_notice(text):
            logger.info("Bot announced partner connected. Initializing new conversation flow...")
            # If current conversation already has history or wasn't NEW, create a fresh one
            if conversation.state != ConversationStateEnum.NEW:
                conversation = await repo.create_new_conversation(
                    conversation.telegram_chat_id, conversation.type
                )

            transition = AnonymousStateMachine.process_new_conversation()
            await repo.update_conversation_state(conversation.id, transition.next_state)
            conversation.state = transition.next_state
            for msg in transition.outgoing_messages:
                await sender.send_text(conversation.telegram_chat_id, msg)
                await repo.add_message(
                    conversation_id=conversation.id,
                    telegram_message_id=0,
                    sender_id=conversation.telegram_chat_id,
                    sender_type=SenderTypeEnum.BOT,
                    text=msg,
                    direction=MessageDirectionEnum.OUTGOING,
                )
            if self.dashboard_server:
                self.dashboard_server.broadcast_update(event_type="update")
            return

        # 4. Check for Bot Service/Status Notice ("Ищем собеседника...", feedback prompts, etc.)
        if is_bot_service_notice(text):
            logger.info(f"Bot service notice received: '{text[:60]}'. Ignoring.")
            return

        # 5. If conversation is STOPPED or WAITING_FOR_NEXT, wait for connection notice
        if conversation.state in (ConversationStateEnum.STOPPED, ConversationStateEnum.WAITING_FOR_NEXT):
            logger.info(f"Conversation {conversation.id} is {conversation.state.value}. Waiting for partner connection notice...")
            return

        # 6. State: NEW (Uninitiated conversation - waiting for bot connection notice)
        if conversation.state == ConversationStateEnum.NEW:
            logger.info(f"Conversation {conversation.id} is NEW. Waiting for partner connection notice...")
            return

        # 7. State: WAITING_FOR_GENDER
        if conversation.state == ConversationStateEnum.WAITING_FOR_GENDER:
            transition = AnonymousStateMachine.process_waiting_for_gender(text)
            await repo.update_conversation_state(conversation.id, transition.next_state)
            conversation.state = transition.next_state
            detected_age = extract_age(text)
            detected_name = extract_name(text)

            meta = conversation.details.get_metadata() if conversation.details else {}
            meta_updated = False
            if detected_name and "name" not in meta:
                meta["name"] = detected_name
                meta_updated = True
            if detected_age:
                meta["my_age"] = match_owner_age(detected_age)
                meta_updated = True

            if transition.detected_gender or detected_age or meta_updated:
                await repo.update_conversation_details(
                    conversation.id,
                    gender=transition.detected_gender,
                    participant_age=detected_age,
                    metadata=meta if meta_updated else None,
                )
                if conversation.details:
                    if transition.detected_gender:
                        conversation.details.gender = transition.detected_gender
                    if detected_age:
                        conversation.details.participant_age = detected_age
                    if meta_updated:
                        conversation.details.set_metadata(meta)

            # If female was identified, notify designated user (e.g. @theilerr)
            if transition.detected_gender == "F":
                name_to_report = detected_name or (
                    conversation.details.get_metadata().get("name") if conversation.details else None
                )
                age_to_report = detected_age or (
                    conversation.details.participant_age if conversation.details else None
                )
                await self._notify_female_found(
                    conversation=conversation,
                    name=name_to_report,
                    age=age_to_report,
                    sender=sender,
                )

            # Send state machine messages (e.g. /next or answer 'М')
            for msg in transition.outgoing_messages:
                # Do not repeat 'М' if already answered previously in this conversation
                if msg == "М":
                    recent = await repo.get_recent_messages(conversation.id, limit=10)
                    if any(
                        m.text == "М" and m.direction == MessageDirectionEnum.OUTGOING
                        for m in recent
                    ):
                        logger.info("Already answered 'М' in this conversation. Skipping repeat.")
                        continue

                await sender.send_text(conversation.telegram_chat_id, msg)
                await repo.add_message(
                    conversation_id=conversation.id,
                    telegram_message_id=0,
                    sender_id=conversation.telegram_chat_id,
                    sender_type=SenderTypeEnum.BOT,
                    text=msg,
                    direction=MessageDirectionEnum.OUTGOING,
                )

            # If promoted to ACTIVE on this same message, proceed to LLM generation
            if not transition.should_invoke_llm:
                if self.dashboard_server:
                    self.dashboard_server.broadcast_update(event_type="update")
                return

        # 8. State: ACTIVE (LLM-driven dialogue)
        if conversation.state == ConversationStateEnum.ACTIVE:
            # Check if participant voluntarily shared a Telegram username
            extracted_username = extract_telegram_username(text)
            if extracted_username:
                logger.info(f"Disclosed username detected: {extracted_username}")
                await repo.update_conversation_details(
                    conversation.id,
                    telegram_username=extracted_username,
                    telegram_shared=True,
                )

                closing_msg = (
                    f"Записал твой тг ({extracted_username})! Если что, мой контакт {self.settings.OWNER_USERNAME}. "
                    "Напишу туда, переходим в личку :)"
                )
                await sender.send_text(conversation.telegram_chat_id, closing_msg)
                await repo.add_message(
                    conversation_id=conversation.id,
                    telegram_message_id=0,
                    sender_id=conversation.telegram_chat_id,
                    sender_type=SenderTypeEnum.OWNER,
                    text=closing_msg,
                    direction=MessageDirectionEnum.OUTGOING,
                )

                # Send /next and close anonymous session
                await sender.send_text(conversation.telegram_chat_id, CMD_NEXT)
                await repo.update_conversation_state(conversation.id, ConversationStateEnum.STOPPED)
                return

            # Check if participant shared name or age during active conversation
            active_name = extract_name(text)
            active_age = extract_age(text)
            just_revealed_age = False
            if active_name or active_age:
                meta = conversation.details.get_metadata() if conversation.details else {}
                meta_updated = False
                if active_name and "name" not in meta:
                    meta["name"] = active_name
                    meta_updated = True
                if active_age:
                    meta["my_age"] = match_owner_age(active_age)
                    meta_updated = True
                    just_revealed_age = True

                await repo.update_conversation_details(
                    conversation.id,
                    participant_age=active_age if active_age else None,
                    metadata=meta if meta_updated else None,
                )
                if conversation.details:
                    if active_age:
                        conversation.details.participant_age = active_age
                    if meta_updated:
                        conversation.details.set_metadata(meta)

            # Ensure notification is sent if female gender is active
            if conversation.details and conversation.details.gender == "F":
                name_to_report = conversation.details.get_metadata().get("name")
                age_to_report = conversation.details.participant_age
                await self._notify_female_found(
                    conversation=conversation,
                    name=name_to_report,
                    age=age_to_report,
                    sender=sender,
                )

            # Retrieve context and memory
            summary, recent_history = await self.memory_manager.get_recent_history(
                repo, conversation.id
            )
            metadata = conversation.details.get_metadata() if conversation.details else {}
            state_info = {
                "type": conversation.type.value,
                "state": conversation.state.value,
                "gender": conversation.details.gender if conversation.details else None,
                "name": metadata.get("name"),
                "participant_age": (
                    conversation.details.participant_age if conversation.details else None
                ),
                "my_age": metadata.get("my_age"),
                "just_revealed_age": just_revealed_age,
                "intent": conversation.details.intent if conversation.details else None,
            }

            system_prompt = build_system_prompt(self.soul_loader.content)
            user_context = build_conversation_context(
                state_info=state_info,
                summary=summary,
                recent_messages=recent_history,
                owner_username=self.settings.OWNER_USERNAME,
            )

            # Generate structured response from LLM
            logger.info("Requesting LLM response...")
            ai_response = await self.llm.generate_response(
                system_prompt=system_prompt,
                user_prompt=user_context,
                max_tokens=self.settings.MAX_RESPONSE_TOKENS,
            )

            if not ai_response:
                logger.warning("No valid response returned from LLM provider.")
                return

            # Validate safety & anti-leak rules
            is_safe, reason, cleaned_response = self.safety_validator.validate_and_clean(
                ai_response
            )
            if not is_safe:
                logger.error(f"Response safety rejection: {reason}")
                return

            # Execute action
            await self._execute_action(repo, conversation, cleaned_response, sender)

            # Check if summarization is needed in the background
            try:
                await self.memory_manager.check_and_summarize(repo, self.llm, conversation.id)
            except Exception as e:
                logger.error(f"Summarization error: {e}")

    async def _execute_action(
        self,
        repo: Repository,
        conversation: Conversation,
        response: Any,
        sender: AnySenderInterface,
    ) -> None:
        """Execute validated AI action."""
        action = response.action

        if action == ActionType.REPLY:
            if response.text:
                msgs = split_into_messages(response.text)
                for msg in msgs:
                    await sender.send_text(conversation.telegram_chat_id, msg)
                    await repo.add_message(
                        conversation_id=conversation.id,
                        telegram_message_id=0,
                        sender_id=conversation.telegram_chat_id,
                        sender_type=SenderTypeEnum.OWNER,
                        text=msg,
                        direction=MessageDirectionEnum.OUTGOING,
                    )

        elif action == ActionType.SEND_AUTHORIZED_PHOTO:
            if response.photo_id:
                # Optionally send accompanying text if provided
                if response.text:
                    await sender.send_text(conversation.telegram_chat_id, response.text)
                    await repo.add_message(
                        conversation_id=conversation.id,
                        telegram_message_id=0,
                        sender_id=conversation.telegram_chat_id,
                        sender_type=SenderTypeEnum.OWNER,
                        text=response.text,
                        direction=MessageDirectionEnum.OUTGOING,
                    )
                await sender.send_photo(conversation.telegram_chat_id, response.photo_id)

        elif action == ActionType.NEXT:
            logger.info(f"AI requested NEXT: {response.reason}")
            await sender.send_text(conversation.telegram_chat_id, CMD_NEXT)
            await repo.update_conversation_state(conversation.id, ConversationStateEnum.STOPPED)

        elif action == ActionType.STOP:
            logger.info(f"AI requested STOP: {response.reason}")
            await repo.update_conversation_state(conversation.id, ConversationStateEnum.STOPPED)

        elif action == ActionType.IGNORE:
            logger.info("AI requested IGNORE.")

        if self.dashboard_server:
            self.dashboard_server.broadcast_update(event_type="update")

    async def _notify_female_found(
        self,
        conversation: Conversation,
        name: str | None,
        age: int | None,
        sender: AnySenderInterface,
    ) -> None:
        """Send notification to configured username when a female partner is identified."""
        if not self.settings.NOTIFY_ON_FEMALE_FOUND:
            return

        target = self.settings.NOTIFY_FEMALE_USERNAME
        if not target:
            return

        # Check if already notified for this conversation
        if conversation.details:
            metadata = conversation.details.get_metadata()
            if metadata.get("female_notified"):
                return
            metadata["female_notified"] = True
            conversation.details.set_metadata(metadata)

        info_items = []
        if name:
            info_items.append(f"Имя: {name}")
        if age:
            info_items.append(f"Возраст: {age}")
        info_str = f" ({', '.join(info_items)})" if info_items else ""

        notification_text = (
            f"Найдена девушка в анонимном чате!{info_str}\n"
            f"Диалог ID: {conversation.id}"
        )
        logger.info(f"Sending female-found alert to {target}: '{notification_text}'")
        if self.dashboard_server:
            bot_name = "anonrubot" if conversation.telegram_chat_id == 660309226 else "anonim"
            self.dashboard_server.broadcast_update(event_type="female_found", bot=bot_name)
        try:
            await sender.send_text(target, notification_text)
        except Exception as e:
            logger.warning(f"Could not send female notification to {target}: {e}")
