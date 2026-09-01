"""Configuration management for Telegram Autonomous Conversation Assistant."""

from pathlib import Path
from typing import Any, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram Credentials
    TELEGRAM_API_ID: Optional[int] = Field(
        default=None, description="Telegram API ID from my.telegram.org"
    )
    TELEGRAM_API_HASH: Optional[str] = Field(
        default=None, description="Telegram API Hash from my.telegram.org"
    )
    TELEGRAM_PHONE: Optional[str] = Field(default=None, description="Phone number for Telegram login")
    TELEGRAM_SESSION: str = Field(default="telegram_ai", description="Session file name")

    @field_validator("TELEGRAM_API_ID", "OWNER_USER_ID", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: Any) -> Optional[int]:
        if v is None or v == "":
            return None
        return int(v)

    # LLM Settings
    LLM_API_KEY: str | None = Field(default=None, description="LLM Provider API Key")
    LLM_BASE_URL: str = Field(default="https://api.openai.com/v1", description="LLM base URL")
    LLM_MODEL: str = Field(default="gpt-4o-mini", description="LLM model name")
    MAX_RESPONSE_TOKENS: int = Field(default=300, description="Max generation tokens for LLM")
    LLM_REQUEST_TIMEOUT: float = Field(default=30.0, description="LLM API timeout in seconds")

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///data/app.db", description="Database connection URL"
    )

    # Autopilot & Modes
    AUTOPILOT_ENABLED: bool = Field(default=False, description="Global autopilot switch")
    DRY_RUN: bool = Field(default=True, description="Dry run mode (logs only, no sends)")
    DRAFT_MODE: bool = Field(default=False, description="Draft responses without sending")

    # Specific chat automations
    PRIVATE_CHAT_AUTOPILOT: bool = Field(
        default=False, description="Autonomous replies in private chats"
    )
    GROUP_CHAT_AUTOPILOT: bool = Field(
        default=False, description="Autonomous replies in group chats"
    )

    # Owner & Target Identities
    OWNER_USERNAME: str = Field(default="@mlsv06", description="Owner Telegram username")
    OWNER_USER_ID: int | None = Field(
        default=None, description="Owner Telegram user ID for control verification"
    )
    ANONYMOUS_BOT_USERNAMES: Any = Field(
        default=["anonrubot", "anonim", "chatxanonbot"],
        description="List of target anonymous chat bot usernames",
    )
    ANONYMOUS_BOT_USERNAME: str = Field(
        default="anonrubot", description="Target anonymous chat bot username (backwards compatibility)"
    )
    ANONYMOUS_BOT_IDS: list[int] = Field(
        default=[660309226, 8103812978],
        description="Known anonymous bot Telegram IDs (anonrubot: 660309226, anonim: 8103812978)",
    )

    @field_validator("ANONYMOUS_BOT_USERNAMES", mode="after")
    @classmethod
    def parse_anonymous_bot_usernames(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                import json

                try:
                    parsed = json.loads(v_stripped)
                    if isinstance(parsed, list):
                        return [
                            str(b).lstrip("@").strip().lower() for b in parsed if str(b).strip()
                        ]
                except Exception:
                    pass
            return [b.lstrip("@").strip().lower() for b in v_stripped.split(",") if b.strip()]
        elif isinstance(v, (list, tuple, set)):
            return [str(b).lstrip("@").strip().lower() for b in v if str(b).strip()]
        return ["anonrubot", "anonim", "chatxanonbot"]

    def get_anonymous_bot_ids(self) -> list[int]:
        """Return list of known anonymous bot chat IDs."""
        return list(self.ANONYMOUS_BOT_IDS)

    def is_anonymous_bot(
        self,
        username_or_usernames: str | list[str] | None = None,
        chat_id: int | None = None,
    ) -> bool:
        """Check if username(s) or chat ID match any configured anonymous dating bot."""
        if chat_id and chat_id in self.get_anonymous_bot_ids():
            return True
        if not username_or_usernames:
            return False
        if isinstance(username_or_usernames, str):
            names = [username_or_usernames]
        else:
            names = list(username_or_usernames)

        configured = set(self.get_anonymous_bot_usernames())
        for name in names:
            if not name:
                continue
            clean = name.lstrip("@").strip().lower()
            if clean in configured:
                return True
        return False

    def get_anonymous_bot_usernames(self) -> list[str]:
        """Return list of cleaned unique anonymous bot usernames."""
        bots: list[str] = ["anonrubot", "anonim", "chatxanonbot"]
        for b in self.ANONYMOUS_BOT_USERNAMES:
            clean = b.lstrip("@").strip().lower()
            if clean and clean not in bots:
                bots.append(clean)
        if self.ANONYMOUS_BOT_USERNAME:
            clean_single = self.ANONYMOUS_BOT_USERNAME.lstrip("@").strip().lower()
            if clean_single and clean_single not in bots:
                bots.append(clean_single)
        return bots

    # Notifications
    NOTIFY_ON_FEMALE_FOUND: bool = Field(
        default=True, description="Whether to notify when a female partner is found"
    )
    NOTIFY_FEMALE_USERNAME: str = Field(
        default="@theilerr", description="Telegram username to notify when female partner is found"
    )

    # Pacing and Memory Limits
    MIN_REPLY_DELAY_SECONDS: float = Field(default=3.0, description="Min human-like reply delay")
    MAX_REPLY_DELAY_SECONDS: float = Field(default=10.0, description="Max human-like reply delay")
    MAX_HISTORY_MESSAGES: int = Field(default=30, description="Maximum short-term history window")

    # Paths & Logging
    SOUL_PATH: Path = Field(default=Path("soul.md"), description="Path to soul.md instructions")
    LOG_LEVEL: str = Field(
        default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )

    # Web Dashboard Settings
    DASHBOARD_ENABLED: bool = Field(
        default=True, description="Enable local web dashboard to view live chats"
    )
    DASHBOARD_HOST: str = Field(
        default="127.0.0.1", description="Web dashboard host address"
    )
    DASHBOARD_PORT: int = Field(
        default=8080, description="Web dashboard HTTP port"
    )

    def validate_for_startup(self) -> list[str]:
        """Validate critical configuration before running. Returns list of errors if any."""
        errors: list[str] = []
        if not self.TELEGRAM_API_ID:
            errors.append("TELEGRAM_API_ID is required in .env or environment")
        if not self.TELEGRAM_API_HASH:
            errors.append("TELEGRAM_API_HASH is required in .env or environment")
        if not self.LLM_MODEL:
            errors.append("LLM_MODEL is required")
        if not self.SOUL_PATH.exists():
            errors.append(f"Soul file does not exist at path: {self.SOUL_PATH}")
        return errors


# Global settings singleton
settings = Settings()
