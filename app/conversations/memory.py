"""Memory management supporting sliding short-term history and periodic summarization."""

import logging

from app.ai.prompts import build_summarization_prompt
from app.ai.provider import LLMProvider
from app.database.repository import Repository

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages short-term history retrieval and background/incremental summarization."""

    def __init__(self, max_history: int = 30) -> None:
        self.max_history = max_history

    async def get_recent_history(
        self,
        repo: Repository,
        conversation_id: int,
    ) -> tuple[str | None, list[dict[str, str]]]:
        """
        Get existing summary and formatted recent messages list.
        Returns: (summary_text, [{'direction': 'INCOMING'|'OUTGOING', 'text': '...'}])
        """
        summary = await repo.get_conversation_summary(conversation_id)
        db_messages = await repo.get_recent_messages(conversation_id, limit=self.max_history)

        formatted_messages = [
            {
                "id": str(msg.id),
                "direction": msg.direction.value,
                "text": msg.text,
                "timestamp": msg.timestamp.isoformat(),
            }
            for msg in db_messages
        ]

        return summary, formatted_messages

    async def check_and_summarize(
        self,
        repo: Repository,
        llm: LLMProvider,
        conversation_id: int,
    ) -> None:
        """
        If total messages exceed threshold, summarize older messages and update summary.
        """
        recent = await repo.get_recent_messages(conversation_id, limit=self.max_history + 10)
        if len(recent) <= self.max_history:
            return  # Within short-term limit

        # Older messages are the prefix before the last max_history
        older_messages = recent[: len(recent) - self.max_history]
        if not older_messages:
            return

        logs = [
            f"{'Me' if m.direction.value == 'OUTGOING' else 'Partner'}: {m.text}"
            for m in older_messages
        ]

        existing_summary = await repo.get_conversation_summary(conversation_id)
        prompt = build_summarization_prompt(existing_summary, logs)

        logger.info(
            f"Summarizing {len(older_messages)} older messages for conversation {conversation_id}..."
        )
        new_summary = await llm.generate_summary(prompt)

        if new_summary:
            last_msg_id = older_messages[-1].id
            await repo.save_conversation_summary(
                conversation_id=conversation_id,
                summary_text=new_summary,
                last_message_id=last_msg_id,
            )
            logger.info(f"Updated summary saved for conversation {conversation_id}.")
