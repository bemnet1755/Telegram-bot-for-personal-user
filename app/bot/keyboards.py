"""Inline keyboards & menus for the bot UI.

Callback data uses a compact ``section:action[:arg]`` scheme so handlers
can be small. Every conversational flow includes Back / Cancel.
"""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


# --- Main menu (also mirrored as a reply keyboard for one-tap access) ---


def main_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 New Sale", callback_data="menu:sell"),
                InlineKeyboardButton(text="➕ Add Stock", callback_data="menu:addstock"),
            ],
            [
                InlineKeyboardButton(text="📦 Inventory", callback_data="menu:inventory"),
                InlineKeyboardButton(text="📊 Dashboard", callback_data="menu:dashboard"),
            ],
            [
                InlineKeyboardButton(text="📈 Reports", callback_data="menu:reports"),
                InlineKeyboardButton(text="🔎 Search", callback_data="menu:search"),
            ],
            [
                InlineKeyboardButton(text="📦 Add Product", callback_data="menu:addproduct"),
                InlineKeyboardButton(text="⚙️ Settings", callback_data="menu:settings"),
            ],
        ]
    )


def main_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Sell"), KeyboardButton(text="➕ Add Stock")],
            [KeyboardButton(text="📦 Inventory"), KeyboardButton(text="📊 Dashboard")],
            [KeyboardButton(text="📈 Reports"), KeyboardButton(text="🔎 Search")],
            [KeyboardButton(text="⚙️ Settings")],
        ],
        resize_keyboard=True,
    )


def back_cancel(callback_prefix: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Back", callback_data=f"{callback_prefix}:back"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="cancel"),
            ]
        ]
    )


def confirm_cancel(on_confirm: str, on_cancel: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=on_confirm),
                InlineKeyboardButton(text="❌ Cancel", callback_data=on_cancel),
            ]
        ]
    )


def dashboard_period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Today", callback_data="dash:today"),
                InlineKeyboardButton(text="📅 This Week", callback_data="dash:week"),
            ],
            [
                InlineKeyboardButton(text="📅 This Month", callback_data="dash:month"),
                InlineKeyboardButton(text="📅 Custom Range", callback_data="dash:custom"),
            ],
        ]
    )


def reports_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📈 Period Summary", callback_data="rep:period"),
                InlineKeyboardButton(text="🏆 Top Products", callback_data="rep:top"),
            ],
            [
                InlineKeyboardButton(text="🧾 Recent Sales", callback_data="rep:sales"),
                InlineKeyboardButton(text="📤 Export", callback_data="rep:export"),
            ],
            [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="menu:main")],
        ]
    )


def export_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Products", callback_data="exp:products"),
                InlineKeyboardButton(text="Sales", callback_data="exp:sales"),
                InlineKeyboardButton(text="Movements", callback_data="exp:movements"),
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:reports")],
        ]
    )


def product_detail_keyboard(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Sell", callback_data=f"pd:Sell:{product_id}"),
                InlineKeyboardButton(text="➕ Add Stock", callback_data=f"pd:AddStock:{product_id}"),
            ],
            [
                InlineKeyboardButton(text="📜 History", callback_data=f"pd:History:{product_id}"),
                InlineKeyboardButton(text="✏️ Edit", callback_data=f"pd:Edit:{product_id}"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Adjust Stock", callback_data=f"pd:Adjust:{product_id}"),
                InlineKeyboardButton(text="🗑️ Archive", callback_data=f"pd:Archive:{product_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:inventory")],
        ]
    )


def history_keyboard(product_id: int, offset: int, more: bool) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    if offset > 0:
        row.append(InlineKeyboardButton(text="⬅️ Older", callback_data=f"hist:prev:{product_id}:{offset}"))
    if more:
        row.append(InlineKeyboardButton(text="➡️ Newer", callback_data=f"hist:next:{product_id}:{offset}"))
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"pd:History:{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💱 Currency", callback_data="set:currency"),
                InlineKeyboardButton(text="🕒 Timezone", callback_data="set:timezone"),
            ],
            [
                InlineKeyboardButton(
                    text="🔔 Low-stock alerts", callback_data="set:lowstock"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="menu:main")],
        ]
    )
