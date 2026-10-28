"""Command handlers: /start, /help, /cancel and the slash-command shortcuts.

These are thin; heavy lifting is in services + the callback/flow modules.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import main_menu_inline, main_menu_reply

router = Router()


def _welcome() -> str:
    return (
        "👋 Welcome to your Business Manager\n\n"
        "What would you like to do?"
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(_welcome(), reply_markup=main_menu_inline())
    await message.answer(
        "Use the buttons — or /commands anytime.",
        reply_markup=main_menu_reply(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = (
        "📖 HELP\n\n"
        "Commands (optional shortcuts):\n"
        " /dashboard · /products · /stock · /sell · /addstock · /reports · "
        "/search <term> · /settings · /cancel\n\n"
        "You can do everything with the buttons too.\n\n"
        "💡 Natural language works as well, e.g.\n"
        "  'Bought 20 black shirts for 400 each, selling for 700'\n"
        "  'Sold 3 black shirts'"
    )
    await message.answer(text)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled. Tap the menu to start over.",
                        reply_markup=main_menu_inline())


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message) -> None:
    from app.bot.callbacks import show_dashboard
    await show_dashboard(message)


@router.message(Command("products"))
@router.message(Command("stock"))
async def cmd_products(message: Message) -> None:
    from app.bot.callbacks import show_inventory
    await show_inventory(message)


@router.message(Command("sell"))
async def cmd_sell(message: Message, state: FSMContext) -> None:
    from app.bot.flows import start_sell
    await start_sell(message, state)


@router.message(Command("addstock"))
async def cmd_addstock(message: Message, state: FSMContext) -> None:
    from app.bot.flows import start_add_stock
    await start_add_stock(message, state)


@router.message(Command("reports"))
async def cmd_reports(message: Message) -> None:
    from app.bot.callbacks import show_reports
    await show_reports(message)


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    from app.bot.callbacks import show_settings
    await show_settings(message)


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext) -> None:
    from app.bot.flows import start_search
    await start_search(message, state)
