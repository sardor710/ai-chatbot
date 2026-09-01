"""CLI entry point for Telegram Autonomous Conversation Assistant."""

import argparse
import asyncio
import logging
import sys

from app.config import settings
from app.database.database import init_db
from app.main import TelegramAIApp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Telegram Autonomous Conversation Assistant powered by Telethon & LLM"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Run in dry-run mode (log outgoing messages without sending to Telegram)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Disable dry-run mode (send real messages according to AUTOPILOT setting)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG level logging",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Initialize database tables and exit",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate current configuration (.env) and exit",
    )
    return parser.parse_args()


async def main() -> None:
    # Ensure stdout/stderr handles UTF-8 on Windows
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_args()

    # Handle --check-config
    if args.check_config:
        print("[*] Checking configuration...")
        errors = settings.validate_for_startup()
        if errors:
            print("[X] Configuration validation failed:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        else:
            print("[OK] Configuration is valid!")
            print(f"  * Model: {settings.LLM_MODEL}")
            print(f"  * Database URL: {settings.DATABASE_URL}")
            print(f"  * Owner Username: {settings.OWNER_USERNAME}")
            print(f"  * Autopilot: {settings.AUTOPILOT_ENABLED}")
            print(f"  * Dry Run: {settings.DRY_RUN}")
            sys.exit(0)

    # Handle --init-db
    if args.init_db:
        print(f"[*] Initializing database schema at {settings.DATABASE_URL}...")
        await init_db(settings.DATABASE_URL)
        print("[OK] Database initialized successfully.")
        sys.exit(0)

    # Apply CLI overrides
    if args.debug:
        settings.LOG_LEVEL = "DEBUG"

    if args.dry_run is True:
        settings.DRY_RUN = True
    elif args.no_dry_run:
        settings.DRY_RUN = False

    # Startup validation
    validation_errors = settings.validate_for_startup()
    if validation_errors:
        print("⚠️ Warning: Startup configuration issues detected:")
        for err in validation_errors:
            print(f"  - {err}")
        print("Please review your .env file before starting.")
        if not settings.DRY_RUN:
            sys.exit(1)

    app = TelegramAIApp(custom_settings=settings)
    try:
        await app.start()
    except KeyboardInterrupt:
        print("\nExiting on user interrupt...")
    except Exception:
        logging.getLogger(__name__).exception("Fatal error running application:")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
