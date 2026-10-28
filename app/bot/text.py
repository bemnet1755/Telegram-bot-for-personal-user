"""Build the text blocks shown on each screen.

Keeps handlers short: each function returns the exact Markdown-lite string
the user sees. Money/date formatting is delegated to :mod:`app.utils.formatting`.
"""
from __future__ import annotations

import datetime as dt

from app.database.models import (
    InventoryMovement,
    Product,
    Sale,
    SaleItem,
)
from app.services import reporting_service
from app.utils.formatting import format_date, format_day, money, pct, stock_emoji


def period_block(title: str, s: reporting_service.PeriodSummary, currency: str) -> str:
    return (
        f"{title}\n━━━━━━━━━━━━━━\n"
        f"Sales:        {s.sales_count}\n"
        f"Units:        {s.units_sold}\n"
        f"Revenue:      {money(s.revenue, currency)}\n"
        f"COGS:         {money(s.cogs, currency)}\n"
        f"Gross profit: {money(s.gross_profit, currency)}\n"
        f"Margin:       {pct(s.margin_pct)}"
    )


def inventory_block(s: reporting_service.InventorySummary, currency: str) -> str:
    return (
        "Inventory\n"
        "━━━━━━━━━━━━━━\n"
        f"Products:     {s.product_count}\n"
        f"Units:        {s.units}\n"
        f"Cost value:   {money(s.cost_value, currency)}\n"
        f"Retail value: {money(s.retail_value, currency)}\n\n"
        f"⚠️ Low stock: {s.low_stock_count} products"
    )


def dashboard_message(
    today: reporting_service.PeriodSummary,
    month: reporting_service.PeriodSummary,
    inv: reporting_service.InventorySummary,
    currency: str,
) -> str:
    return (
        "📊 BUSINESS DASHBOARD\n\n"
        + period_block("Today", today, currency)
        + "\n\n"
        + period_block("This Month", month, currency)
        + "\n\n"
        + inventory_block(inv, currency)
    )


def product_detail_message(
    p: Product,
    units: int,
    newest_cost,
    cost_value: float,
    retail_value: float,
    currency: str,
    tz: dt.tzinfo,
    sold_this_month: int,
    revenue_this_month: float,
    profit_this_month: float,
) -> str:
    price = float(p.default_selling_price) if p.default_selling_price is not None else 0.0
    potential = (price - float(newest_cost or 0)) * units
    cost_val = money(newest_cost if newest_cost is not None else 0, currency)
    return (
        "📸 PRODUCT\n\n"
        f"{p.name}\n"
        + (f"SKU: {p.sku}\n" if p.sku else "")
        + (f"Brand: {p.brand}\n" if p.brand else "")
        + (f"Category: {p.category}\n" if p.category else "")
        + "\n━━━━━━━━━━━━━━\n"
        f"Current stock: {units}\n\n"
        f"Cost value: {money(cost_value, currency)}\n"
        f"Retail value: {money(retail_value, currency)}\n\n"
        f"Purchase cost: {cost_val}\n"
        f"Selling price: {money(price, currency)}\n"
        f"Potential gross: {money(potential, currency)}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"Sold this month: {sold_this_month}\n"
        f"Revenue this month: {money(revenue_this_month, currency)}\n"
        f"Gross profit: {money(profit_this_month, currency)}"
    )


def sale_receipt(
    sale: Sale,
    items: list[SaleItem],
    names: dict[int, str],
    remaining_by_product: dict[int, int],
    currency: str,
    tz: dt.tzinfo,
) -> str:
    lines = ["🧾 SALE", f"#{sale.sale_number} · {format_date(sale.created_at, tz)}\n"]
    for item in items:
        name = names.get(item.product_id, f"Product {item.product_id}")
        remaining = remaining_by_product.get(item.product_id, "?")
        lines.append(
            f"{name}\n"
            f"{item.quantity} × {money(item.unit_selling_price, currency)}\n"
            f"  Revenue: {money(item.revenue, currency)}   "
            f"COGS: {money(item.cogs, currency)}   "
            f"Profit: {money(item.gross_profit, currency)}\n"
            f"  Remaining stock: {remaining}\n"
        )
    revenue = float(sale.total_revenue)
    cogs = float(sale.total_cogs)
    margin = (float(sale.total_gross_profit) / revenue * 100) if revenue else 0.0
    lines.append(
        "━━━━━━━━━━━━━━\n"
        f"Revenue: {money(revenue, currency)}\n"
        f"COGS: {money(cogs, currency)}\n"
        f"Gross profit: {money(float(sale.total_gross_profit), currency)}\n"
        f"Margin: {pct(margin)}"
    )
    return "\n".join(lines)


def _item_products(items: list[SaleItem]):
    # (unused) placeholder retained for backward-compat import; returns [].
    return []


def history_entry(
    m: InventoryMovement, currency: str, tz: dt.tzinfo
) -> str:
    from app.database.models.enums import MovementType

    day = format_day(m.created_at, tz)
    icon_map = {
        MovementType.PURCHASE: "➕ Stock",
        MovementType.SALE: "💰 Sold",
        MovementType.RETURN: "↩️ Return",
        MovementType.ADJUSTMENT_IN: "➕ Adjust",
        MovementType.ADJUSTMENT_OUT: "➖ Adjust",
        MovementType.DAMAGE: "🔥 Damaged",
    }
    label = icon_map.get(m.movement_type, "•")
    body = f"{day}\n{label} {m.quantity:+d}"
    if m.movement_type in (MovementType.PURCHASE,) and m.batch_id:
        body += "\n(cost in batch)"
    return body


def low_stock_block(product: Product, units: int, currency: str) -> str:
    return (
        "⚠️ LOW STOCK\n\n"
        f"{product.name}\n\n"
        f"Only {units} unit{'s' if units != 1 else ''} remaining."
    )
