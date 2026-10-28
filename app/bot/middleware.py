"""Bot middleware: authentication + global error guard.

* :class:`AuthMiddleware` rejects every update from anyone who is not the
  configured ``ALLOWED_TELEGRAM_USER_ID`` and hands them a generic message.
* :class:`ErrorHandler` is a safety net so a bug never takes the whole bot
  down or leaks stack traces to the user.
"""
from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.types import Update

from app.config.settings import Settings

logger = logging.getLogger(__name__)

PRIVATE_MESSAGE = "Sorry, this bot is private."


class AuthMiddleware(BaseMiddleware):
    """Only the configured user may use the bot."""

    def __init__(self, settings: Settings):
        self._allowed = settings.allowed_telegram_user_id

    async def __call__(self, handler, update: Update, **kwargs):
        user = update.user
        if user is None or user.id != self._allowed:
            # Inform unauthorized senders with a generic, information-free reply.
            if update.message:
                await update.message.answer(PRIVATE_MESSAGE)
            elif update.callback_query:
                try:
                    await update.callback_query.answer()
                    if update.callback_query.message:
                        await update.callback_query.message.answer(PRIVATE_MESSAGE)
                except Exception:  # message may be inaccessible
                    pass
            logger.warning(
                "Rejected unauthorized access user_id=%s update=%s",
                user.id if user else None,
                type(update).__name__,
            )
            return None
        return await handler(update, **kwargs)


class ErrorHandler(BaseMiddleware):
    """Catch-all: log real errors, show a friendly message, keep serving."""

    async def __call__(self, handler, update: Update, **kwargs):
        try:
            return await handler(update, **kwargs)
        except Exception:
            logger.exception("Unhandled error while processing update")
            if update.message:
                await update.message.answer("⚠️ Something went wrong. Please try again.")
            elif update.callback_query:
                await update.callback_query.answer("⚠️ Something went wrong. Try again.")
            return None
