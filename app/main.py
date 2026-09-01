"""Main application orchestrator."""

import asyncio
import logging

from app.ai.provider import OpenAICompatibleProvider
from app.ai.response import ResponseSafetyValidator
from app.ai.soul_loader import SoulLoader
from app.anonymous.handler import AnonymousHandler
from app.config import Settings
from app.config import settings as default_settings
from app.control.commands import ControlManager
from app.conversations.manager import ConversationManager
from app.conversations.memory import MemoryManager
from app.conversations.router import MessageRouter
from app.database.database import close_db, init_db
from app.telegram.client import TelegramClientManager
from app.telegram.handlers import register_telegram_handlers
from app.telegram.media import MediaManager
from app.telegram.sender import TelegramSender
from app.utils.logging import setup_logging
from app.web.server import WebDashboardServer

logger = logging.getLogger(__name__)


class TelegramAIApp:
    """Core application coordinating Telegram, Database, LLM, and Routing."""

    def __init__(self, custom_settings: Settings | None = None) -> None:
        self.settings = custom_settings or default_settings
        self.running = False
        self._stop_event = asyncio.Event()

        # Known secrets list for log masking & output validation
        secrets_to_mask = [
            self.settings.TELEGRAM_API_HASH,
            self.settings.LLM_API_KEY,
            self.settings.TELEGRAM_PHONE,
        ]

        # 1. Setup Logging
        setup_logging(
            log_level_str=self.settings.LOG_LEVEL,
            known_secrets=secrets_to_mask,
        )

        # 2. Initialize Core Subsystems
        self.soul_loader = SoulLoader(self.settings.SOUL_PATH)
        self.safety_validator = ResponseSafetyValidator(forbidden_secrets=secrets_to_mask)
        self.media_manager = MediaManager()

        self.llm_provider = OpenAICompatibleProvider(
            api_key=self.settings.LLM_API_KEY,
            base_url=self.settings.LLM_BASE_URL,
            model=self.settings.LLM_MODEL,
            timeout=self.settings.LLM_REQUEST_TIMEOUT,
        )

        self.memory_manager = MemoryManager(max_history=self.settings.MAX_HISTORY_MESSAGES)
        self.conversation_manager = ConversationManager()

        self.control_manager = ControlManager(
            settings=self.settings,
            soul_loader=self.soul_loader,
            llm=self.llm_provider,
            stop_callback=self.stop,
        )

        self.anonymous_handler = AnonymousHandler(
            settings=self.settings,
            soul_loader=self.soul_loader,
            llm=self.llm_provider,
            memory_manager=self.memory_manager,
            safety_validator=self.safety_validator,
        )

        self.telegram_client_manager = TelegramClientManager(self.settings)
        self.sender: TelegramSender | None = None
        self.router: MessageRouter | None = None
        self.dashboard_server: WebDashboardServer | None = None

    def stop(self) -> None:
        """Signal application to stop gracefully."""
        logger.info("Application stop requested.")
        self.running = False
        self._stop_event.set()

    async def start(self) -> None:
        """Start database, Telegram client, event listeners, and run event loop."""
        self.running = True
        logger.info("Starting Telegram Autonomous Conversation Assistant...")
        logger.info(
            f"Mode: DRY_RUN={self.settings.DRY_RUN}, AUTOPILOT={self.settings.AUTOPILOT_ENABLED}"
        )

        # Initialize Database
        await init_db(self.settings.DATABASE_URL)

        # Pre-load Soul
        self.soul_loader.load()

        # Start Telethon Client
        client = await self.telegram_client_manager.start()

        # Initialize Sender and Router
        self.sender = TelegramSender(
            client=client,
            settings=self.settings,
            media_manager=self.media_manager,
        )

        self.router = MessageRouter(
            settings=self.settings,
            control_manager=self.control_manager,
            conversation_manager=self.conversation_manager,
            anonymous_handler=self.anonymous_handler,
            telegram_sender=self.sender,
            soul_loader=self.soul_loader,
            llm=self.llm_provider,
            memory_manager=self.memory_manager,
            safety_validator=self.safety_validator,
        )

        # Initialize and launch Web Dashboard if enabled
        if self.settings.DASHBOARD_ENABLED:
            self.dashboard_server = WebDashboardServer(
                settings=self.settings,
                control_manager=self.control_manager,
                sender=self.sender,
            )
            await self.dashboard_server.start()
            self.anonymous_handler.dashboard_server = self.dashboard_server

        # Register Event Listeners
        register_telegram_handlers(client, self.router)
        logger.info(
            "Telegram event handlers registered. Assistant is listening for incoming messages."
        )

        # Pre-resolve and register anonymous bot IDs
        for bot_username in self.settings.get_anonymous_bot_usernames():
            try:
                entity = await client.get_entity(bot_username)
                if entity:
                    self.router.register_anonymous_bot_id(entity.id)
                    logger.info(f"Resolved anonymous bot @{bot_username} -> ID {entity.id}")
            except Exception as e:
                logger.warning(f"Could not resolve entity for @{bot_username}: {e}")

        # Auto-initiate anonymous search if autopilot is enabled
        if self.settings.AUTOPILOT_ENABLED and not self.settings.DRY_RUN:
            for bot_username in self.settings.get_anonymous_bot_usernames():
                try:
                    logger.info(f"Auto-initiating search: sending /search to @{bot_username}...")
                    await self.sender.send_text(bot_username, "/search")
                except Exception as e:
                    logger.warning(f"Could not send initial /search to @{bot_username}: {e}")

        # Wait until stop event is signaled
        try:
            await self._stop_event.wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Termination signal received.")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Clean shutdown of all network and database connections."""
        logger.info("Shutting down subsystems...")
        if self.dashboard_server:
            await self.dashboard_server.stop()
        await self.telegram_client_manager.stop()
        await close_db()
        logger.info("Shutdown completed cleanly.")
