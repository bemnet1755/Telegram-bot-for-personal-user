"""Application bootstrap: build the bot, wire routers, run with polling."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.bot.callbacks import router as callbacks_router
from app.bot.flows import router as flows_router
from app.bot.handlers import router as commands_router
from app.bot.middleware import AuthMiddleware, ErrorHandler
from app.config.settings import Settings
from app.database.session import Database

logger = logging.getLogger(__name__)


def _register_commands(bot: Bot) -> None:
    bot.set_my_commands(
        [
            BotCommand(command="start", description="Open the main menu"),
            BotCommand(command="help", description="Show help"),
            BotCommand(command="dashboard", description="Dashboard"),
            BotCommand(command="products", description="Inventory list"),
            BotCommand(command="stock", description="Inventory list"),
            BotCommand(command="sell", description="Record a sale"),
            BotCommand(command="addstock", description="Receive stock"),
            BotCommand(command="reports", description="Reports"),
            BotCommand(command="search", description="Search products"),
            BotCommand(command="settings", description="Settings"),
            BotCommand(command="cancel", description="Cancel current flow"),
        ]
    )


async def run(settings: Settings) -> None:
    Database.configure(settings.database_url)
    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # Middleware order matters: auth first, then error catch-all.
    dp.update.outer_middleware(AuthMiddleware(settings))
    dp.update.outer_middleware(ErrorHandler())

    dp.include_router(commands_router)
    dp.include_router(callbacks_router)
    dp.include_router(flows_router)

    try:
        await _register_commands(bot)
    except Exception:  # pragma: no cover - non-fatal
        logger.exception("Could not register bot commands; continuing")

    logger.info("Bot is starting long-polling…")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await Database.dispose()
