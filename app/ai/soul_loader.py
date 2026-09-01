"""Soul.md file loader and live reloader."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SOUL = """# SOUL OF THE ASSISTANT
You are communicating via a 21-year-old male owner's Telegram account.
You are natural, casual, empathetic, and truthful about your automation if directly asked.
Keep responses concise and engaging.
"""


class SoulLoader:
    """Manages loading, caching, and hot-reloading soul.md."""

    def __init__(self, path: Path | str = Path("soul.md")) -> None:
        self.path = Path(path)
        self._cached_content: str | None = None

    def load(self) -> str:
        """Load soul content, caching result."""
        if self._cached_content is not None:
            return self._cached_content
        return self.reload()

    def reload(self) -> str:
        """Force reload soul.md from disk."""
        try:
            if not self.path.exists():
                logger.warning(f"Soul file {self.path} not found. Creating default soul.md.")
                self.path.write_text(DEFAULT_SOUL, encoding="utf-8")
                self._cached_content = DEFAULT_SOUL
                return self._cached_content

            content = self.path.read_text(encoding="utf-8").strip()
            if not content:
                logger.warning(f"Soul file {self.path} is empty, using fallback.")
                content = DEFAULT_SOUL

            self._cached_content = content
            logger.info(f"Loaded soul definition successfully ({len(content)} chars).")
            return self._cached_content
        except Exception as e:
            logger.error(f"Failed to read soul file at {self.path}: {e}")
            if self._cached_content:
                return self._cached_content
            return DEFAULT_SOUL

    @property
    def content(self) -> str:
        return self.load()
