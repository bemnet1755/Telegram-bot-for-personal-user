"""Conversational FSM flows: add product, add stock, sell, adjust, search.

Each ``start_*`` function is entered from a button/command and drives a
step-by-step FSM. All writes happen in the service layer; these handlers
only collect input and render screens.

Cancellation is handled by /cancel and the ❌ Cancel button (see callbacks).
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import (
    back_cancel,
    confirm_cancel,
    main_menu_inline,
)
from app.database.session import Database
from app.services import inventory_service, product_service, sales_service
from app.services.exceptions import (
    DomainError,
    InsufficientStockError,
    InvalidPriceError,
    InvalidQuantityError,
)
from app.services import nlp_service
from app.services.sales_service import SaleLine
from app.utils.formatting import money, stock_emoji

from app.bot.states import (
    AdjustStates,
    AddProductStates,
    AddStockStates,
    CancelStates,
    SearchStates,
    SellStates,
)

logger = logging.getLogger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# Add product (photo -> name -> sku -> category -> price -> threshold)
# ---------------------------------------------------------------------------


async def start_add_product(message: Message, state: FSMContext) -> None:
    await state.set_state(AddProductStates.awaiting_photo)
    await state.update_data(flow={"kind": "add_product", "data": {}})
    await message.answer(
        "📸 ADD PRODUCT\n\nSend a photo, or send **Skip** if no photo.",
        reply_markup=back_cancel("menu:addproduct"),
    )


@router.message(
    AddProductStates.awaiting_photo,
)
async def ap_photo(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    if message.photo:
        largest = message.photo[-1]
        data["photo_file_id"] = largest.file_id
        await state.update_data(flow={"kind": "add_product", "data": data})
        await state.set_state(AddProductStates.awaiting_name)
        await message.answer(
            "📸 Photo received. What is the product name?",
            reply_markup=back_cancel("menu:addproduct"),
        )
    elif message.text and message.text.strip().lower() == "skip":
        await state.update_data(flow={"kind": "add_product", "data": data})
        await state.set_state(AddProductStates.awaiting_name)
        await message.answer(
            "Okay, no photo.\nWhat is the product name?",
            reply_markup=back_cancel("menu:addproduct"),
        )
    else:
        # Treat the first text as the name directly.
        await _ap_name_direct(message, state, data)


async def _ap_name_direct(message: Message, state: FSMContext, data: dict) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Please send the product name or a photo.")
        return
    data["name"] = name
    await state.set_state(AddProductStates.awaiting_sku)
    await state.update_data(flow={"kind": "add_product", "data": data})
    await message.answer(
        f"✅ {name}\n\nWhat is the SKU? (Optional — send **-** to skip)",
        reply_markup=back_cancel("menu:addproduct"),
    )


@router.message(AddProductStates.awaiting_name)
async def ap_name(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    if message.photo and "photo_file_id" not in data:
        data["photo_file_id"] = message.photo[-1].file_id
    name = (message.text or "").strip()
    if not name:
        await message.answer("Please send the product name.")
        return
    data["name"] = name
    await state.set_state(AddProductStates.awaiting_sku)
    await state.update_data(flow={"kind": "add_product", "data": data})
    await message.answer(
        f"✅ {name}\n\nWhat is the SKU? (Optional — send **-** to skip)",
        reply_markup=back_cancel("menu:addproduct"),
    )


@router.message(AddProductStates.awaiting_sku)
async def ap_sku(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    sku = (message.text or "").strip()
    data["sku"] = None if sku in ("-", "") else sku
    await state.set_state(AddProductStates.awaiting_category)
    await state.update_data(flow={"kind": "add_product", "data": data})
    await message.answer(
        "What category? (Optional — send **-** to skip)",
        reply_markup=back_cancel("menu:addproduct"),
    )


@router.message(AddProductStates.awaiting_category)
async def ap_category(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    cat = (message.text or "").strip()
    data["category"] = None if cat in ("-", "") else cat
    await state.set_state(AddProductStates.awaiting_price)
    await state.update_data(flow={"kind": "add_product", "data": data})
    await message.answer(
        "What is the selling price? (or **-** for none)",
        reply_markup=back_cancel("menu:addproduct"),
    )


@router.message(AddProductStates.awaiting_price)
async def ap_price(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    raw = (message.text or "").strip()
    if raw in ("-", ""):
        price = None
    else:
        price = _parse_money(raw)
        if price is None:
            await message.answer("That's not a valid number. Try again (or **-**).")
            return
    data["default_selling_price"] = price
    await state.set_state(AddProductStates.awaiting_threshold)
    await state.update_data(flow={"kind": "add_product", "data": data})
    await message.answer(
        "Low-stock alert level? (e.g. 3 — send 0 to disable)",
        reply_markup=back_cancel("menu:addproduct"),
    )


@router.message(AddProductStates.awaiting_threshold)
async def ap_threshold(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    raw = (message.text or "").strip()
    try:
        threshold = int(raw) if raw not in ("-", "") else 0
    except ValueError:
        await message.answer("That's not a valid number. Try again.")
        return

    async with Database.session_scope() as db:
        product = await product_service.create_product(
            db,
            data["name"],
            sku=data.get("sku"),
            category=data.get("category"),
            photo_file_id=data.get("photo_file_id"),
            default_selling_price=data.get("default_selling_price"),
            low_stock_threshold=threshold,
        )

    await state.clear()
    await message.answer(
        f"✅ Product created: **{product.name}**\n"
        f"(id {product.id})",
        reply_markup=main_menu_inline(),
    )


# ---------------------------------------------------------------------------
# Add stock
# ---------------------------------------------------------------------------


async def start_add_stock(
    message: Message, state: FSMContext, preset_product: int | None = None
) -> None:
    if preset_product:
        await _ask_quantity(message, state, preset_product)
        return

    from app.bot.helpers import product_picker

    async with Database.session_scope() as db:
        kb = await product_picker(db, "stock:pick", with_status=True)
    await state.set_state(AddStockStates.awaiting_product)
    await message.answer(
        "📦 ADD STOCK\n\nSelect product:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("stock:pick"), AddStockStates.awaiting_product)
async def stock_pick(call, state: FSMContext) -> None:
    pid = int(call.data.split(":")[2])
    await call.answer()
    await _ask_quantity(call.message, state, pid)


async def _ask_quantity(message: Message, state: FSMContext, pid: int) -> None:
    await state.set_state(AddStockStates.awaiting_quantity)
    await state.update_data(flow={"kind": "add_stock", "data": {"product_id": pid}})
    await message.answer("How many units?", reply_markup=back_cancel("menu:addstock"))


@router.message(AddStockStates.awaiting_quantity)
async def stock_qty(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    q = _parse_int(message.text)
    if q is None or q <= 0:
        await message.answer("Please enter a positive number of units.")
        return
    data["quantity"] = q
    await state.set_state(AddStockStates.awaiting_cost)
    await state.update_data(flow={"kind": "add_stock", "data": data})
    await message.answer("What was the purchase cost per unit?",
                        reply_markup=back_cancel("menu:addstock"))


@router.message(AddStockStates.awaiting_cost)
async def stock_cost(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    cost = _parse_money(message.text)
    if cost is None:
        await message.answer("Please enter a valid cost (e.g. 3500).")
        return
    data["unit_cost"] = cost
    await state.set_state(AddStockStates.awaiting_supplier)
    await state.update_data(flow={"kind": "add_stock", "data": data})
    await message.answer("Supplier? (Optional — send **-** to skip)",
                        reply_markup=back_cancel("menu:addstock"))


@router.message(AddStockStates.awaiting_supplier)
async def stock_supplier(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    sup = (message.text or "").strip()
    data["supplier"] = None if sup in ("-", "") else sup
    await state.set_state(AddStockStates.awaiting_note)
    await state.update_data(flow={"kind": "add_stock", "data": data})
    await message.answer("Note? (Optional — send **-** to skip)",
                        reply_markup=back_cancel("menu:addstock"))


@router.message(AddStockStates.awaiting_note)
async def stock_note(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    note = (message.text or "").strip()
    data["note"] = None if note in ("-", "") else note
    await state.update_data(flow={"kind": "add_stock", "data": data})
    await _confirm_stock(message, state)


async def _confirm_stock(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    currency = _currency()
    total = data["quantity"] * data["unit_cost"]
    pid = data["product_id"]
    async with Database.session_scope() as db:
        product = await product_service.get_product(db, pid)
        units = await _stock(db, pid)
    await state.set_state(AddStockStates.awaiting_confirm)
    await message.answer(
        "📦 STOCK RECEIPT\n\n"
        f"{product.name}\n\n"
        f"Quantity: {data['quantity']}\n"
        f"Cost/unit: {money(data['unit_cost'], currency)}\n"
        f"Total cost: {money(total, currency)}\n\n"
        f"Current stock: {units}",
        reply_markup=confirm_cancel(f"stock:confirm:{pid}"),
    )


@router.callback_query(F.data.startswith("stock:confirm:"))
async def stock_confirm(call, state: FSMContext) -> None:
    data = await _flow_data(state)
    pid = int(call.data.split(":")[2])
    async with Database.session_scope() as db:
        batch = await inventory_service.add_purchase(
            db,
            pid,
            data["quantity"],
            data["unit_cost"],
            supplier=data.get("supplier"),
            note=data.get("note"),
        )
        units = await _stock(db, pid)
        product = await product_service.get_product(db, pid)

    await state.clear()
    currency = _currency()
    await call.message.edit_text(
        f"✅ Received {data['quantity']} × {money(data['unit_cost'], currency)}.\n"
        f"Now {units} in stock.  (batch #{batch.id})",
        reply_markup=main_menu_inline(),
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Sell
# ---------------------------------------------------------------------------


async def start_sell(
    message: Message, state: FSMContext, preset_product: int | None = None
) -> None:
    if preset_product:
        await _sell_ask_qty(message, state, preset_product)
        return

    from app.bot.helpers import product_picker

    async with Database.session_scope() as db:
        kb = await product_picker(db, "sell:pick", with_status=True)
    await state.set_state(SellStates.awaiting_product)
    await message.answer("💰 NEW SALE\n\nSelect product:", reply_markup=kb)


@router.callback_query(F.data.startswith("sell:pick"), SellStates.awaiting_product)
async def sell_pick(call, state: FSMContext) -> None:
    pid = int(call.data.split(":")[2])
    await call.answer()
    await _sell_ask_qty(call.message, state, pid)


async def _sell_ask_qty(message: Message, state: FSMContext, pid: int) -> None:
    currency = _currency()
    async with Database.session_scope() as db:
        product = await product_service.get_product(db, pid)
        units = await _stock(db, pid)
    default = product.default_selling_price
    await state.set_state(SellStates.awaiting_quantity)
    await state.update_data(
        flow={"kind": "sell", "data": {"product_id": pid, "price": float(default) if default is not None else None}}
    )
    price_line = (
        f"Selling price: {money(default, currency)}\n" if default is not None else ""
    )
    await message.answer(
        f"💰 {product.name}\n\nAvailable: {units}\n{price_line}Quantity?",
        reply_markup=back_cancel("menu:sell"),
    )


@router.message(SellStates.awaiting_quantity)
async def sell_qty(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    q = _parse_int(message.text)
    if q is None or q <= 0:
        await message.answer("Please enter a positive quantity.")
        return
    data["quantity"] = q
    currency = _currency()
    await state.set_state(SellStates.awaiting_price)
    await state.update_data(flow={"kind": "sell", "data": data})
    price = data.get("price")
    prompt = (
        f"Confirm price: {money(price, currency)} (or send a different price)"
        if price is not None
        else "What price? (or **-** to use 0)"
    )
    await message.answer(prompt, reply_markup=back_cancel("menu:sell"))


@router.message(SellStates.awaiting_price)
async def sell_price(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    raw = (message.text or "").strip()
    if raw not in ("-", "", "ok", "confirm"):
        price = _parse_money(raw)
        if price is None:
            await message.answer("That's not a valid price. Try again.")
            return
        data["price"] = price

    currency = _currency()
    async with Database.session_scope() as db:
        product = await product_service.get_product(db, data["product_id"])
        units = await _stock(db, data["product_id"])
        price = data.get("price") or 0.0
        revenue = price * data["quantity"]
        # estimate COGS by FIFO (dry-run) for the confirmation screen
        from app.services.fifo_service import FifoEngine

        try:
            batches = await FifoEngine._open_batches(db, data["product_id"])
            allocations = FifoEngine.allocate(batches, data["quantity"])
            cogs = float(sum(a.cogs for a in allocations))
        except InsufficientStockError:
            cogs = 0.0

    gross = revenue - cogs
    margin = (gross / revenue * 100) if revenue else 0.0
    await state.set_state(SellStates.awaiting_confirm)
    await state.update_data(flow={"kind": "sell", "data": data})
    await message.answer(
        "🧾 SALE\n\n"
        f"{product.name}\n"
        f"{data['quantity']} × {money(price, currency)}\n\n"
        f"Revenue: {money(revenue, currency)}\n"
        f"COGS: {money(cogs, currency)}\n"
        f"Gross profit: {money(gross, currency)}\n"
        f"Margin: {margin:.1f}%\n\n"
        f"Remaining stock: {units - data['quantity']}",
        reply_markup=confirm_cancel(
            f"sell:confirm:{data['product_id']}:{data['quantity']}:{int(data.get('price') or 0) if (data.get('price') or 0) == int(data.get('price') or 0) else data.get('price') or 0}"
        ),
    )


@router.callback_query(F.data.startswith("sell:confirm:"))
async def sell_confirm(call, state: FSMContext) -> None:
    parts = call.data.split(":")
    # sell:confirm:{pid}:{qty}:{price}
    pid = int(parts[2])
    qty = int(parts[3])
    price = float(parts[4])
    lines = [SaleLine(pid, qty, price)]

    from app.config.settings import get_settings

    allow_neg = get_settings().allow_negative_stock
    try:
        async with Database.session_scope() as db:
            confirmed = await sales_service.record_sale(
                db, lines, allow_negative_stock=allow_neg
            )
            names = {
                p.id: p.name for p in await product_service.list_active_products(db, 200)
            }
    except InsufficientStockError as e:
        await state.clear()
        await call.message.edit_text(
            f"⚠️ Not enough stock. Only {e.available} available "
            f"(asked {e.requested}).\nTop up with ➕ Add Stock.",
            reply_markup=main_menu_inline(),
        )
        await call.answer()
        return

    await state.clear()
    currency = _currency()
    tzinfo = tz()
    from app.bot import text as txt

    receipt = txt.sale_receipt(
        confirmed.sale, confirmed.items, names,
        confirmed.remaining_by_product, currency, tzinfo,
    )
    await call.message.edit_text(receipt, reply_markup=main_menu_inline())

    # Low-stock alerts.
    if confirmed.low_stock:
        for product, remaining in confirmed.low_stock:
            await call.message.answer(
                txt.low_stock_block(product, remaining, currency),
                reply_markup=back_cancel("menu:addstock"),
            )
    await call.answer()


# ---------------------------------------------------------------------------
# Adjust stock
# ---------------------------------------------------------------------------


async def start_adjust(
    message: Message, state: FSMContext, preset_product: int | None = None
) -> None:
    from app.bot.helpers import product_picker

    if preset_product:
        await state.update_data(flow={"kind": "adjust", "data": {"product_id": preset_product}})
        await _adjust_delta(message, state, preset_product)
        return

    async with Database.session_scope() as db:
        kb = await product_picker(db, "adj:pick", with_status=True)
    await state.set_state(AdjustStates.awaiting_delta)
    await state.update_data(flow={"kind": "adjust", "data": {"product_id": 0}})
    await message.answer(
        "⚙️ ADJUST STOCK\n\nSelect product:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("adj:pick"), AdjustStates.awaiting_delta)
async def adj_pick(call, state: FSMContext) -> None:
    pid = int(call.data.split(":")[2])
    data = await _flow_data(state)
    data["product_id"] = pid
    await state.update_data(flow={"kind": "adjust", "data": data})
    await call.answer()
    await _adjust_delta(call.message, state, pid)


async def _adjust_delta(message, state, pid) -> None:
    async with Database.session_scope() as db:
        units = await _stock(db, pid)
    await state.set_state(AdjustStates.awaiting_delta)
    await message.answer(
        f"Current stock: {units}\nAdjustment? (e.g. -2, +5, or a new count)",
        reply_markup=back_cancel("menu:inventory"),
    )


@router.message(AdjustStates.awaiting_delta)
async def adj_delta(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    delta = _parse_int(message.text)
    if delta is None:
        await message.answer("Please enter a valid number (e.g. -2 or +5).")
        return
    data["delta"] = delta
    await state.set_state(AdjustStates.awaiting_reason)
    await state.update_data(flow={"kind": "adjust", "data": data})
    await message.answer("Reason? (e.g. Damaged item — or **-**)",
                        reply_markup=back_cancel("menu:inventory"))


@router.message(AdjustStates.awaiting_reason)
async def adj_reason(message: Message, state: FSMContext) -> None:
    data = await _flow_data(state)
    reason = (message.text or "").strip()
    data["reason"] = None if reason in ("-", "") else reason
    data["damage"] = "damage" in (reason or "").lower()
    await state.set_state(AdjustStates.awaiting_confirm)
    await state.update_data(flow={"kind": "adjust", "data": data})
    await message.answer(
        f"Apply adjustment {data['delta']:+d} ({data.get('reason') or 'no reason'})?",
        reply_markup=confirm_cancel(f"adj:confirm:{data['product_id']}"),
    )


@router.callback_query(F.data.startswith("adj:confirm:"))
async def adj_confirm(call, state: FSMContext) -> None:
    data = await _flow_data(state)
    pid = data["product_id"]
    try:
        async with Database.session_scope() as db:
            movement = await inventory_service.apply_adjustment(
                db, pid, data["delta"], reason=data.get("reason"),
                damage=data.get("damage", False),
            )
            units = await _stock(db, pid)
    except InsufficientStockError as e:
        await call.message.edit_text(
            f"⚠️ Cannot remove {e.requested} — only {e.available} in stock."
        )
        await call.answer()
        return

    await state.clear()
    await call.message.edit_text(
        f"✅ Adjustment {data['delta']:+d} applied. Now {units} in stock.",
        reply_markup=main_menu_inline(),
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def start_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchStates.awaiting_query)
    await message.answer("🔎 Search products\n\nSend a term (name / SKU / brand / category):")


@router.message(SearchStates.awaiting_query)
async def search_query(message: Message, state: FSMContext) -> None:
    query = (message.text or "").strip()

    async with Database.session_scope() as db:
        products = await product_service.search_products(db, query)
    if not products:
        await message.answer("No products matched.", reply_markup=main_menu_inline())
        await state.clear()
        return

    lines = ["🔎 SEARCH RESULTS\n"]
    buttons = []
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    for p in products:
        lines.append(f"• {p.name}{' (' + str(p.sku) + ')' if p.sku else ''}")
        buttons.append([InlineKeyboardButton(text=p.name, callback_data=f"prod:{p.id}")])

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else main_menu_inline()
    await message.answer("\n".join(lines) + "\nTap a product:", reply_markup=kb)


# ---------------------------------------------------------------------------
# Free-text natural language (opt-in; structured flows always available)
# ---------------------------------------------------------------------------


@router.message(~F.text.startswith("/"), F.text != "")
async def free_text(message: Message, state: FSMContext) -> None:
    """Catch-all for non-command text. Try to parse buy/sell intents."""
    # Skip if we're in an active FSM state (handled by other routers)
    current_state = await state.get_state()
    if current_state is not None:
        return

    intent = nlp_service.parse(message.text)
    if intent.kind == "unknown" or not intent.product_query:
        await message.answer(
            "I didn't understand. You can always use the buttons, or try:\n"
            "  'bought 20 <product> for <cost> each'\n"
            "  'sold <n> <product>'"
        )
        return

    currency = _currency()
    async with Database.session_scope() as db:
        matches = await product_service.search_products(db, intent.product_query, limit=5)

    if not matches:
        await message.answer(f"Product '{intent.product_query}' not found. Use ➕ Add Product first.")
        return

    if len(matches) > 1:
        await message.answer(
            f"Multiple matches: {', '.join(p.name for p in matches)}.\n"
            "Please be more specific, or pick one with the buttons."
        )
        return

    product = matches[0]

    if intent.kind == "buy":
        if intent.unit_cost is None:
            await message.answer(
                f"Parsed: **{product.name}** × {intent.quantity}.\n"
                f"Missing cost — use ➕ Add Stock to enter it."
            )
            return
        await state.update_data(
            flow={"kind": "add_stock", "data": {
                "product_id": product.id,
                "quantity": intent.quantity,
                "unit_cost": intent.unit_cost,
            }}
        )
        await _confirm_stock(message, state)
        return

    # sell
    if intent.quantity is None:
        await message.answer("How many? Reply with a number.")
        await state.set_state(SellStates.awaiting_quantity)
        await state.update_data(
            flow={"kind": "sell", "data": {
                "product_id": product.id,
                "price": float(product.default_selling_price) if product.default_selling_price else None,
            }}
        )
        return
    await _sell_ask_qty(message, state, product.id)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


async def _flow_data(state: FSMContext) -> dict:
    """Return the mutable data dict for the current flow."""
    raw = await state.get_data()
    flow = raw.get("flow") or {"kind": "", "data": {}}
    return flow.get("data", {}) if isinstance(flow.get("data"), dict) else {}


def _parse_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw.strip().replace(",", "").replace("+", ""))
    except ValueError:
        return None


def _parse_money(raw: str | None) -> float | None:
    if raw is None:
        return None
    raw = raw.strip().replace(",", "").replace(" ", "")
    if raw in ("", "-"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _currency() -> str:
    from app.config.settings import get_settings
    return get_settings().currency


def tz():
    from app.config.settings import get_settings
    from app.utils.formatting import get_timezone
    return get_timezone(get_settings().timezone)


async def _stock(db, product_id: int) -> int:
    from app.database.models import product_stock
    return await product_stock(db, product_id)
