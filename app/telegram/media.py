"""Media registry and authorized photo manager."""

import logging
from pathlib import Path

from app.database.repository import Repository

logger = logging.getLogger(__name__)


class MediaManager:
    """Manages authorized photos and media assets."""

    def __init__(self, media_dir: str = "media") -> None:
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        # Default authorized photos from specification
        self._registry: dict[str, str] = {
            "PHOTO_1": "https://t.me/mywagent/4",
            "PHOTO_2": "https://t.me/mywagent/3",
        }

    async def register_photo(
        self,
        alias: str,
        path_or_file_id: str,
        description: str | None = None,
        repo: Repository | None = None,
    ) -> None:
        """Register an authorized photo with an alias (e.g. PHOTO_1)."""
        self._registry[alias.upper()] = path_or_file_id
        if repo:
            await repo.register_media(
                alias=alias.upper(),
                file_id_or_path=path_or_file_id,
                media_type="photo",
                description=description,
            )
        logger.info(f"Registered authorized media alias: {alias.upper()} -> {path_or_file_id}")

    async def get_photo_target(self, alias: str, repo: Repository | None = None) -> str | None:
        """Resolve alias to valid file path or Telegram file ID."""
        alias_upper = alias.upper()
        if repo:
            db_media = await repo.get_media_by_alias(alias_upper)
            if db_media:
                return db_media.file_id_or_path

        if alias_upper in self._registry:
            return self._registry[alias_upper]

        # Check local media folder fallback
        possible_local = self.media_dir / f"{alias_upper.lower()}.jpg"
        if possible_local.exists():
            return str(possible_local)

        return None
