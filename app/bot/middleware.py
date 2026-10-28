"""Bot middleware: authentication + global error guard.

* :class:`AuthMiddleware` rejects every update from anyone who is not the
  configured ``ALLOWED_TELEGRAM_USER_ID`` and hands them a generic message.
* :class:`ErrorHandler` is a safety net so a bug never takes the whole bot
  down or leaks stack traces to the user.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.config.settings import Settings

logger = logging.getLogger(__name__)

PRIVATE_MESSAGE = "Sorry, this bot is private."


class AuthMiddleware(BaseMiddleware):
    """Only the configured user may use the bot."""

    def __init__(self, settings: Settings):
        self._allowed = int(settings.allowed_telegram_user_id)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None and isinstance(event, Update):
            if event.message:
                user = event.message.from_user
            elif event.callback_query:
                user = event.callback_query.from_user

        if user is None or user.id != self._allowed:
            # Inform unauthorized senders with a generic, information-free reply.
            if isinstance(event, Update):
                if event.message:
                    await event.message.answer(PRIVATE_MESSAGE)
                elif event.callback_query:
                    try:
                        await event.callback_query.answer(PRIVATE_MESSAGE, show_alert=True)
                    except Exception:
                        pass
            logger.warning(
                "Rejected unauthorized access user_id=%s update=%s (expected %s)",
                user.id if user else None,
                type(event).__name__,
                self._allowed,
            )
            return None
        return await handler(event, data)


class ErrorHandler(BaseMiddleware):
    """Catch-all: log real errors, show a friendly message, keep serving."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            logger.exception("Unhandled error while processing update")
            if isinstance(event, Update):
                if event.message:
                    await event.message.answer("⚠️ Something went wrong. Please try again.")
                elif event.callback_query:
                    try:
                        await event.callback_query.answer("⚠️ Something went wrong. Try again.")
                    except Exception:
                        pass
            return None
