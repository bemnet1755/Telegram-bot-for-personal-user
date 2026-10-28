"""Inline-callback handlers: the button-driven core of the UX.

Routed by callback-data prefix (see :mod:`app.bot.keyboards`). Every handler
opens its own DB session and keeps business logic in the services layer.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputFile, Message

from app.bot import text as txt
from app.bot.keyboards import (
    back_cancel,
    dashboard_period_keyboard,
    export_keyboard,
    history_keyboard,
    main_menu_inline,
    product_detail_keyboard,
    reports_keyboard,
    settings_keyboard,
)
from app.database.session import Database
from app.services import (
    inventory_service,
    product_service,
    reporting_service,
    sales_service,
)
from app.services.settings_service import RuntimeSettings
from app.utils import export as exporter
from app.utils.formatting import format_date, money, pct, stock_emoji

from app.bot.helpers import inventory_grid, product_picker, tz

logger = logging.getLogger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# No-ops / cancel
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Cancelled.", reply_markup=main_menu_inline())
    await call.answer()


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "menu:main")
async def menu_main(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(
        "👋 What would you like to do?", reply_markup=main_menu_inline()
    )
    await call.answer()


@router.callback_query(F.data == "menu:search")
async def menu_search(call: CallbackQuery, state: FSMContext) -> None:
    from app.bot.flows import start_search

    await call.answer()
    await start_search(call.message, state)


@router.callback_query(F.data == "menu:settings")
async def menu_settings(call: CallbackQuery) -> None:
    await show_settings(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:inventory")
async def menu_inventory(call: CallbackQuery) -> None:
    await show_inventory(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:dashboard")
async def menu_dashboard(call: CallbackQuery) -> None:
    await show_dashboard(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:reports")
async def menu_reports(call: CallbackQuery) -> None:
    await show_reports(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:sell")
async def menu_sell(call: CallbackQuery, state: FSMContext) -> None:
    from app.bot.flows import start_sell

    await call.answer()
    await start_sell(call.message, state)


@router.callback_query(F.data == "menu:addstock")
async def menu_addstock(call: CallbackQuery, state: FSMContext) -> None:
    from app.bot.flows import start_add_stock

    await call.answer()
    await start_add_stock(call.message, state)


@router.callback_query(F.data == "menu:addproduct")
async def menu_addproduct(call: CallbackQuery, state: FSMContext) -> None:
    from app.bot.flows import start_add_product

    await call.answer()
    await start_add_product(call.message, state)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


async def show_dashboard(message: Message) -> None:
    tzinfo = tz()
    currency = RuntimeSettings().currency()

    async with Database.session_scope() as db:
        today = await reporting_service.today_summary(db, tzinfo)
        month = await reporting_service.this_month_summary(db, tzinfo)
        inv = await reporting_service.inventory_summary(db)

    await message.answer(
        txt.dashboard_message(today, month, inv, currency),
        reply_markup=dashboard_period_keyboard(),
    )


@router.callback_query(F.data == "dash:today")
async def dash_today(call: CallbackQuery) -> None:
    tzinfo = tz()
    currency = RuntimeSettings().currency()
    async with Database.session_scope() as db:
        s = await reporting_service.today_summary(db, tzinfo)
    await call.message.edit_text(txt.period_block("Today", s, currency), reply_markup=main_menu_inline())
    await call.answer()


@router.callback_query(F.data == "dash:week")
async def dash_week(call: CallbackQuery) -> None:
    tzinfo = tz()
    currency = RuntimeSettings().currency()
    async with Database.session_scope() as db:
        s = await reporting_service.week_summary(db, tzinfo)
    await call.message.edit_text(txt.period_block("This Week", s, currency), reply_markup=main_menu_inline())
    await call.answer()


@router.callback_query(F.data == "dash:month")
async def dash_month(call: CallbackQuery) -> None:
    tzinfo = tz()
    currency = RuntimeSettings().currency()
    async with Database.session_scope() as db:
        s = await reporting_service.this_month_summary(db, tzinfo)
    await call.message.edit_text(txt.period_block("This Month", s, currency), reply_markup=main_menu_inline())
    await call.answer()


@router.callback_query(F.data == "dash:custom")
async def dash_custom(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SellStates.awaiting_quantity)  # placeholder; see notes
    await call.message.edit_text(
        "📅 Custom range\n\nSend start date as ``YYYY-MM-DD`` (then end date).\n"
        "(Custom range is a stretch goal — Today/Week/Month cover most needs.)"
    )
    await call.answer("Not implemented yet")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


async def show_reports(message: Message) -> None:
    await message.answer("📈 Reports", reply_markup=reports_keyboard())


@router.callback_query(F.data == "rep:period")
async def rep_period(call: CallbackQuery) -> None:
    tzinfo = tz()
    currency = RuntimeSettings().currency()
    async with Database.session_scope() as db:
        today = await reporting_service.today_summary(db, tzinfo)
        month = await reporting_service.this_month_summary(db, tzinfo)
    await call.message.edit_text(
        "📈 PERIOD SUMMARY\n\n"
        + txt.period_block("Today", today, currency)
        + "\n\n"
        + txt.period_block("This Month", month, currency)
    )
    await call.answer()


@router.callback_query(F.data == "rep:top")
async def rep_top(call: CallbackQuery) -> None:
    currency = RuntimeSettings().currency()
    lines = ["🏆 TOP PRODUCTS\n"]
    async with Database.session_scope() as db:
        tops = await reporting_service.top_products(db, sort="revenue", limit=10)
    if not tops:
        lines.append("No sales yet.")
    for i, t in enumerate(tops, 1):
        lines.append(
            f"{i}. {t.name}\n"
            f"   Sold: {t.units}   Revenue: {money(t.revenue, currency)}   "
            f"Gross profit: {money(t.gross_profit, currency)}"
        )
    await call.message.edit_text("\n".join(lines))
    await call.answer()


@router.callback_query(F.data == "rep:sales")
async def rep_sales(call: CallbackQuery) -> None:
    currency = RuntimeSettings().currency()
    lines = ["🧾 RECENT SALES\n"]
    async with Database.session_scope() as db:
        sales = await reporting_service.sales_history(db, limit=10, offset=0)
    for s in sales:
        flag = "" if s.status.value == "ACTIVE" else "  (cancelled)"
        lines.append(
            f"{s.sale_number} · {format_date(s.created_at, tz())}\n"
            f"Revenue {money(s.total_revenue, currency)}   "
            f"Profit {money(s.total_gross_profit, currency)}{flag}"
        )
    await call.message.edit_text("\n".join(lines))
    await call.answer()


@router.callback_query(F.data == "rep:export")
async def rep_export(call: CallbackQuery) -> None:
    await call.message.edit_text("📤 Export", reply_markup=export_keyboard())
    await call.answer()


@router.callback_query(F.data == "exp:products")
async def exp_products(call: CallbackQuery) -> None:
    async with Database.session_scope() as db:
        data = await exporter.products_csv(db)
    await call.message.answer_document(
        InputFile(data, filename="products.csv"), caption="Products (CSV)"
    )
    await call.answer()


@router.callback_query(F.data == "exp:sales")
async def exp_sales(call: CallbackQuery) -> None:
    async with Database.session_scope() as db:
        data = await exporter.sales_csv(db)
    await call.message.answer_document(
        InputFile(data, filename="sales.csv"), caption="Sales (CSV)"
    )
    await call.answer()


@router.callback_query(F.data == "exp:movements")
async def exp_movements(call: CallbackQuery) -> None:
    async with Database.session_scope() as db:
        data = await exporter.movements_csv(db)
    await call.message.answer_document(
        InputFile(data, filename="movements.csv"), caption="Inventory movements (CSV)"
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Inventory screen
# ---------------------------------------------------------------------------


async def show_inventory(message: Message) -> None:
    async with Database.session_scope() as db:
        body, kb = await inventory_grid(db)
    await message.answer(body, reply_markup=kb)


@router.callback_query(F.data.startswith("prod:"))
async def product_detail(call: CallbackQuery) -> None:
    pid = int(call.data.split(":")[1])
    tzinfo = tz()
    currency = RuntimeSettings().currency()

    async with Database.session_scope() as db:
        product = await product_service.get_product(db, pid)
        units, newest_cost, cost_value, retail_value = await product_service.batch_summary(
            db, pid
        )
        month = await reporting_service.this_month_summary(db, tzinfo)
        # per-product month stats:
        from sqlalchemy import func, select

        from app.database.models import Sale, SaleItem, SaleStatus

        agg = (await db.execute(
            select(
                func.sum(SaleItem.quantity),
                func.sum(SaleItem.revenue),
                func.sum(SaleItem.gross_profit),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(
                SaleItem.product_id == pid,
                Sale.status == SaleStatus.ACTIVE,
                Sale.created_at >= _month_start_utc(),
            )
        )).one()
        sold_m, rev_m, prof_m = (int(agg[0] or 0), float(agg[1] or 0), float(agg[2] or 0))

    body = txt.product_detail_message(
        product, units, newest_cost, cost_value, retail_value,
        currency, tzinfo, sold_m, rev_m, prof_m,
    )
    if product.photo_file_id:
        await call.message.bot.send_photo(
            call.from_user.id,
            product.photo_file_id,
            caption=body,
            reply_markup=product_detail_keyboard(pid),
        )
    else:
        await call.message.edit_text(
            body, reply_markup=product_detail_keyboard(pid)
        )
    await call.answer()


def _month_start_utc():
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Product-detail actions
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("pd:Sell:"))
async def pd_sell(call: CallbackQuery, state: FSMContext) -> None:
    pid = int(call.data.split(":")[2])
    from app.bot.flows import start_sell

    await call.answer()
    await start_sell(call.message, state, preset_product=pid)


@router.callback_query(F.data.startswith("pd:AddStock:"))
async def pd_add_stock(call: CallbackQuery, state: FSMContext) -> None:
    pid = int(call.data.split(":")[2])
    from app.bot.flows import start_add_stock

    await call.answer()
    await start_add_stock(call.message, state, preset_product=pid)


@router.callback_query(F.data.startswith("pd:History:"))
async def pd_history(call: CallbackQuery) -> None:
    await show_history(call.message, int(call.data.split(":")[2]), 0)
    await call.answer()


@router.callback_query(F.data.startswith("pd:Edit:"))
async def pd_edit(call: CallbackQuery, state: FSMContext) -> None:
    pid = int(call.data.split(":")[2])
    await call.answer()
    await call.message.answer(
        "✏️ Edit product\n\nWhich field? (reply: name / price / threshold / category)",
        reply_markup=back_cancel(),
    )
    # For MVP simplicity we keep edit minimal; the user types a field + value.
    await state.update_data(flow={"kind": "edit", "product_id": pid, "step": "field"})


@router.callback_query(F.data.startswith("pd:Adjust:"))
async def pd_adjust(call: CallbackQuery, state: FSMContext) -> None:
    pid = int(call.data.split(":")[2])
    from app.bot.flows import start_adjust

    await call.answer()
    await start_adjust(call.message, state, preset_product=pid)


@router.callback_query(F.data.startswith("pd:Archive:"))
async def pd_archive(call: CallbackQuery) -> None:
    pid = int(call.data.split(":")[2])
    async with Database.session_scope() as db:
        product = await product_service.get_product(db, pid)
        await product_service.archive_product(db, product)
    await call.message.edit_text(
        f"🗑️ Archived {product.name}. Data is preserved.",
        reply_markup=main_menu_inline(),
    )
    await call.answer()


# ---------------------------------------------------------------------------
# History pagination
# ---------------------------------------------------------------------------


async def show_history(message: Message, product_id: int, offset: int) -> None:
    PAGE = 10
    currency = RuntimeSettings().currency()
    tzinfo = tz()

    async with Database.session_scope() as db:
        product = await product_service.get_product(db, product_id)
        movements = await inventory_service.history(db, product_id, limit=PAGE, offset=offset)
        total = await inventory_service.movements_count(db, product_id)

    if not movements:
        body = "📜 PRODUCT HISTORY\n\nNo movements yet."
        kb = product_detail_keyboard(product_id)
    else:
        lines = [f"📜 {product.name} — HISTORY\n"]
        for m in movements:
            lines.append(txt.history_entry(m, currency, tzinfo))
        body = "\n".join(lines)
        more = offset + PAGE < total
        kb = history_keyboard(product_id, offset + PAGE, more)

    await message.answer(body, reply_markup=kb)


@router.callback_query(F.data.startswith("hist:"))
async def hist_page(call: CallbackQuery) -> None:
    _, direction, pid, offset = call.data.split(":")
    PAGE = 10
    if direction == "next":
        offset = int(offset)
    else:  # older
        offset = max(0, int(offset) - 2 * PAGE)
    await show_history(call.message, int(pid), offset)
    await call.answer()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


async def show_settings(message: Message) -> None:
    settings = RuntimeSettings()
    currency = settings.currency()
    tzname = settings.timezone()
    await message.answer(
        "⚙️ SETTINGS\n\n"
        f"Currency: {currency}\n"
        f"Timezone: {tzname}\n"
        f"Low-stock notifications: ON",
        reply_markup=settings_keyboard(),
    )


@router.callback_query(F.data == "set:currency")
async def set_currency(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(flow={"kind": "set_currency"})
    await call.message.edit_text("💱 New currency code? (e.g. ETB)")
    await call.answer()


@router.callback_query(F.data == "set:timezone")
async def set_timezone(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(flow={"kind": "set_timezone"})
    await call.message.edit_text("🕒 New timezone? (e.g. Africa/Addis_Ababa)")
    await call.answer()


@router.callback_query(F.data == "set:lowstock")
async def set_lowstock(call: CallbackQuery) -> None:
    # Toggle stored flag; RuntimeSettings defaults ON, so just confirm for MVP.
    await call.message.edit_text("🔔 Low-stock notifications: ON")
    await call.answer()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
