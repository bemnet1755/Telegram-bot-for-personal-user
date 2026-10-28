"""Shared bot helpers: product picker and inventory grid keyboards."""
from __future__ import annotations

import datetime as dt

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Product
from app.services import product_service
from app.utils.formatting import money, stock_emoji


async def product_picker(
    session, mode: str, query: str = "", active_only: bool = True, with_status: bool = False
) -> InlineKeyboardMarkup:
    """An inline keyboard of products to pick one.

    ``mode`` is a callback prefix (``sell``/``stock``) so the same picker can
    feed different flows.
    """
    products = await product_service.search_products(session, query, limit=50)
    if not products:
        products = await product_service.list_active_products(session, limit=50)

    buttons: list[list[InlineKeyboardButton]] = []
    for p in products:
        label = p.name
        if with_status:
            units = await _quick_stock(session, p.id)
            status = _status_of(p, units)
            label = f"{stock_emoji(status)} {p.name} · {units}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"{mode}:pick:{p.id}")])

    if not buttons:
        buttons = [[InlineKeyboardButton(text="No products yet", callback_data="noop")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def inventory_grid(session) -> tuple[str, InlineKeyboardMarkup]:
    """The 📦 Inventory screen: status-tinted product list as buttons."""
    products = await product_service.list_active_products(session, limit=50)
    if not products:
        return (
            "📦 INVENTORY\n\nNo active products yet.\nTap ➕ Add Product to create one.",
            InlineKeyboardMarkup(inline_keyboard=[]),
        )

    lines = ["📦 INVENTORY\n"]
    buttons: list[list[InlineKeyboardButton]] = []
    for p in products:
        units = await _quick_stock(session, p.id)
        status = _status_of(p, units)
        price = money(p.default_selling_price or 0, _currency())
        lines.append(f"{stock_emoji(status)} {p.name}\n{units} units · {price}\n")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{stock_emoji(status)} {p.name}", callback_data=f"prod:{p.id}"
                )
            ]
        )

    text = "\n".join(lines).strip()
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def _quick_stock(session, product_id: int) -> int:
    from app.database.models import product_stock

    return await product_stock(session, product_id)


def _status_of(p: Product, units: int) -> str:
    if units <= 0:
        return "out"
    if units <= (p.low_stock_threshold or 0):
        return "low"
    return "ok"


def _currency() -> str:
    from app.config.settings import get_settings

    return get_settings().currency


def tz() -> dt.tzinfo:
    from app.config.settings import get_settings
    from app.utils.formatting import get_timezone

    return get_timezone(get_settings().timezone)
