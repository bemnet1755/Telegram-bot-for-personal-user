"""Display formatting shared across the bot UI.

Money and dates are rendered here so every screen stays consistent, and
currency/timezone are never hard-coded in handlers.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def money(value, currency: str) -> str:
    """``35000`` -> ``35,000 ETB`` (2dp only when needed)."""
    if value is None:
        value = 0
    if isinstance(value, float):
        value = Decimal(str(value))
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except InvalidOperation:
            value = Decimal("0")
    if value == value.to_integral_value():
        digits = f"{value:,.0f}"
    else:
        digits = f"{value:,.2f}"
    return f"{digits} {currency}"


def pct(value) -> str:
    """``40.0`` -> ``40%``; ``36.9`` -> ``36.9%``."""
    if value is None:
        return "0%"
    value = round(float(value), 1)
    if value == int(value):
        return f"{int(value)}%"
    return f"{value}%"


def get_timezone(name: str) -> dt.tzinfo:
    """Resolve a tz name, falling back to UTC (and logging) on error."""
    try:
        return ZoneInfo(name)
    except Exception:  # pragma: no cover - defensive
        logger.warning("Invalid timezone %r; using UTC", name)
        return dt.timezone.utc


def format_date(value: dt.datetime, tz: dt.tzinfo | None = None) -> str:
    """Format a UTC datetime for display in the user's timezone."""
    if value is None:
        return "?"
    if tz is not None:
        value = value.astimezone(tz)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M")


def format_day(value: dt.datetime, tz: dt.tzinfo | None = None) -> str:
    """Short day for history lists, e.g. 'Oct 27' or 'Today'/'Yesterday'."""
    if tz is None:
        tz = dt.timezone.utc
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    local = value.astimezone(tz)
    today = dt.datetime.now(tz).date()
    if local.date() == today:
        return "Today"
    if local.date() == today - dt.timedelta(days=1):
        return "Yesterday"
    return local.strftime("%b %d")


def stock_emoji(status: str) -> str:
    return {"ok": "🟢", "low": "🟡", "out": "🔴"}.get(status, "⚪️")


def movement_emoji(movement_type) -> str:
    from app.database.models.enums import MovementType

    return {
        MovementType.PURCHASE: "➕",
        MovementType.SALE: "💰",
        MovementType.RETURN: "↩️",
        MovementType.ADJUSTMENT_IN: "➕",
        MovementType.ADJUSTMENT_OUT: "➖",
        MovementType.DAMAGE: "🔥",
    }.get(movement_type, "•")
