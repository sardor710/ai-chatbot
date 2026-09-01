"""Owner-only global control commands and runtime state manipulation."""

import asyncio
import logging
from collections.abc import Callable

from app.ai.provider import LLMProvider
from app.ai.soul_loader import SoulLoader
from app.config import Settings
from app.database.repository import Repository

logger = logging.getLogger(__name__)


class ControlManager:
    """Manages runtime application state, pausing, reloading, and owner commands."""

    def __init__(
        self,
        settings: Settings,
        soul_loader: SoulLoader,
        llm: LLMProvider | None = None,
        stop_callback: Callable[[], None] | None = None,
    ) -> None:
        self.settings = settings
        self.soul_loader = soul_loader
        self.llm = llm
        self.stop_callback = stop_callback
        self.is_paused: bool = False
        self.last_received_msg_time: str | None = None
        self.last_response_time: str | None = None
        self.last_error: str | None = None

    def is_owner(self, user_id: int, username: str | None = None) -> bool:
        """Check if user matches configured OWNER_USER_ID or OWNER_USERNAME."""
        if self.settings.OWNER_USER_ID and user_id == self.settings.OWNER_USER_ID:
            return True
        if username and self.settings.OWNER_USERNAME:
            clean_configured = self.settings.OWNER_USERNAME.lstrip("@").lower()
            if username.lstrip("@").lower() == clean_configured:
                return True
        return False

    async def handle_control_command(
        self,
        command_text: str,
        user_id: int,
        username: str | None,
        repo: Repository,
    ) -> tuple[bool, str]:
        """
        Evaluate command.
        Returns: (was_command_handled: bool, response_message: str)
        """
        cmd = command_text.strip().lower()
        valid_commands = {
            "/autopilot_on",
            "/autopilot_off",
            "/status",
            "/pause",
            "/resume",
            "/reload_soul",
            "/reload_config",
            "/stop",
        }

        if not any(cmd.startswith(c) for c in valid_commands):
            return False, ""

        # Authorization check
        if not self.is_owner(user_id, username):
            logger.warning(f"Unauthorized user {user_id} attempted control command: {cmd}")
            return True, "Access denied: this command is restricted to the account owner."

        # Log authorized command event
        await repo.log_control_event(command=cmd, user_id=user_id)

        if cmd == "/autopilot_on":
            self.settings.AUTOPILOT_ENABLED = True
            self.settings.DRY_RUN = False  # Switch to real live sending
            logger.info("Control: Autopilot enabled and DRY_RUN disabled.")

            # Generate live AI test response to confirm API connection
            ai_test_text = ""
            if self.llm:
                try:
                    res = await self.llm.generate_response(
                        system_prompt=(
                            "You are a conversational assistant. Respond with a short, natural, single-sentence greeting in Russian "
                            "confirming you are online and ready to chat."
                        ),
                        user_prompt="Say a quick greeting.",
                        max_tokens=60,
                    )
                    if res and res.text:
                        ai_test_text = res.text
                except Exception as e:
                    ai_test_text = f"(Ошибка LLM API: {e})"

            if ai_test_text:
                return True, (
                    f"🚀 Автопилот ВКЛЮЧЕН!\n\n"
                    f"🤖 [AI тест подключения ({self.settings.LLM_MODEL})]:\n"
                    f"«{ai_test_text}»"
                )
            return True, "Autopilot ENABLED. Autonomous replies are now active."

        elif cmd == "/autopilot_off":
            self.settings.AUTOPILOT_ENABLED = False
            logger.info("Control: Autopilot disabled.")
            return True, "Autopilot DISABLED. Autonomous replies are stopped."

        elif cmd == "/pause":
            self.is_paused = True
            logger.info("Control: Message processing paused.")
            return True, "Processing PAUSED. Incoming messages will be ignored until /resume."

        elif cmd == "/resume":
            self.is_paused = False
            logger.info("Control: Message processing resumed.")
            return True, "Processing RESUMED. Resumed normal operations."

        elif cmd == "/reload_soul":
            reloaded = self.soul_loader.reload()
            logger.info("Control: Soul reloaded.")
            return True, f"Soul reloaded successfully ({len(reloaded)} chars)."

        elif cmd == "/reload_config":
            # Re-read .env settings safely
            new_settings = Settings()
            self.settings.AUTOPILOT_ENABLED = new_settings.AUTOPILOT_ENABLED
            self.settings.DRY_RUN = new_settings.DRY_RUN
            self.settings.DRAFT_MODE = new_settings.DRAFT_MODE
            self.settings.MIN_REPLY_DELAY_SECONDS = new_settings.MIN_REPLY_DELAY_SECONDS
            self.settings.MAX_REPLY_DELAY_SECONDS = new_settings.MAX_REPLY_DELAY_SECONDS
            self.settings.ANONYMOUS_BOT_USERNAMES = new_settings.ANONYMOUS_BOT_USERNAMES
            self.settings.ANONYMOUS_BOT_USERNAME = new_settings.ANONYMOUS_BOT_USERNAME
            logger.info("Control: Runtime config reloaded.")
            return True, "Configuration reloaded from environment/settings."

        elif cmd == "/status":
            status_text = (
                "=== Telegram AI Status ===\n"
                f"• Autopilot: {'ENABLED' if self.settings.AUTOPILOT_ENABLED else 'DISABLED'}\n"
                f"• Dry Run: {'YES' if self.settings.DRY_RUN else 'NO'}\n"
                f"• Draft Mode: {'YES' if self.settings.DRAFT_MODE else 'NO'}\n"
                f"• Paused: {'YES' if self.is_paused else 'NO'}\n"
                f"• Model: {self.settings.LLM_MODEL}\n"
                f"• Last Error: {self.last_error or 'None'}\n"
            )
            return True, status_text

        elif cmd == "/stop":
            logger.info("Control: Termination requested via /stop.")
            if self.stop_callback:
                asyncio.get_running_loop().call_soon(self.stop_callback)
            return True, "Stopping application..."

        return False, ""
