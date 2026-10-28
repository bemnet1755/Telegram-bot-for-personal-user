"""Entry point: ``python -m app``."""
from __future__ import annotations

import asyncio
import logging

from app.config.settings import get_settings
from app.main import run


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = get_settings()
    except Exception as exc:
        logging.error("Configuration error: %s. Check your .env file.", exc)
        raise SystemExit(1)

    try:
        asyncio.run(run(settings))
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")


if __name__ == "__main__":
    main()
