"""Conversation lock and concurrency manager."""

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConversationManager:
    """Provides per-conversation asyncio locking to prevent race conditions and double responses."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get_lock(self, conversation_id: int) -> asyncio.Lock:
        """Get or create the asyncio Lock for this conversation ID."""
        return self._locks[conversation_id]
