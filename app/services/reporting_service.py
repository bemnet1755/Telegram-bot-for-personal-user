"""Reporting: period metrics, dashboard, top products, inventory value.

All figures are computed from ACTIVE sales only; cancelled sales are
excluded so reversing a sale removes it from every report.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    InventoryBatch,
    Product,
    Sale,
    SaleItem,
    SaleStatus,
    product_stock,
)
from app.services.exceptions import DomainError


@dataclass
class PeriodSummary:
    sales_count: int
    units_sold: int
    revenue: float
    cogs: float
    gross_profit: float
    margin_pct: float


@dataclass
class InventorySummary:
    product_count: int
    units: int
    cost_value: float
    retail_value: float
    low_stock_count: int
    out_of_stock_count: int


@dataclass
class TopProduct:
    product_id: int
    name: str
    units: int
    revenue: float
    gross_profit: float


def _pct(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


async def _period_sales(
    db: AsyncSession, start: dt.datetime, end: dt.datetime
) -> PeriodSummary:
    """Aggregate ACTIVE sales whose ``created_at`` is in [start, end)."""
    # totals from the sale rows
    totals = await db.execute(
        select(
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.total_revenue), 0),
            func.coalesce(func.sum(Sale.total_cogs), 0),
            func.coalesce(func.sum(Sale.total_gross_profit), 0),
        ).where(
            Sale.status == SaleStatus.ACTIVE,
            Sale.created_at >= start,
            Sale.created_at < end,
        )
    )
    row = totals.one()
    sales_count = int(row[0])
    revenue = float(row[1])
    cogs = float(row[2])
    gross = float(row[3])

    units = await db.execute(
        select(func.coalesce(func.sum(SaleItem.quantity), 0)).where(
            SaleItem.sale_id.in_(
                select(Sale.id).where(
                    Sale.status == SaleStatus.ACTIVE,
                    Sale.created_at >= start,
                    Sale.created_at < end,
                )
            )
        )
    )
    units_sold = int(units.scalar_one() or 0)

    return PeriodSummary(
        sales_count=sales_count,
        units_sold=units_sold,
        revenue=revenue,
        cogs=cogs,
        gross_profit=gross,
        margin_pct=_pct(gross, revenue),
    )


def start_of_today(tz: dt.tzinfo) -> dt.datetime:
    now = dt.datetime.now(tz)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def range_bounds(start: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """Given a tz-aware start, return [start, start + 1 day) in naive UTC."""
    start_utc = start.astimezone(dt.timezone.utc).replace(tzinfo=None)
    end_utc = start_utc + dt.timedelta(days=1)
    return start_utc, end_utc


def month_bounds(now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """Return naive-UTC bounds for the month containing ``now``."""
    naive = now if now.tzinfo is None else now.astimezone(dt.timezone.utc).replace(tzinfo=None)
    start = naive.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # add a month safely
    month_index = start.month + 1
    year = start.year + (1 if month_index > 12 else 0)
    end = start.replace(day=1, month=1, year=year) if month_index == 12 else start.replace(day=1, month=month_index)
    return start, end


async def period_summary(
    db: AsyncSession, start: dt.datetime, end: dt.datetime
) -> PeriodSummary:
    """Aggregates in naive-UTC bounds (convert before calling)."""
    return await _period_sales(db, start, end)


async def today_summary(db: AsyncSession, tz: dt.tzinfo) -> PeriodSummary:
    start, end = range_bounds(start_of_today(tz))
    return await _period_sales(db, start, end)


async def this_month_summary(db: AsyncSession, tz: dt.tzinfo) -> PeriodSummary:
    now = dt.datetime.now(tz).astimezone(dt.timezone.utc).replace(tzinfo=None)
    start, end = month_bounds(now)
    return await _period_sales(db, start, end)


async def week_summary(db: AsyncSession, tz: dt.tzinfo) -> PeriodSummary:
    """Monday-start week."""
    now = dt.datetime.now(tz)
    day_index = (now.weekday())  # 0=Monday
    start = (now - dt.timedelta(days=day_index)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_utc = start.astimezone(dt.timezone.utc).replace(tzinfo=None)
    end_utc = start_utc + dt.timedelta(days=7)
    return await _period_sales(db, start_utc, end_utc)


async def custom_range_summary(
    db: AsyncSession, start: dt.datetime, end: dt.datetime
) -> PeriodSummary:
    """Both bounds tz-aware; converted to naive UTC for the query."""
    s = start.astimezone(dt.timezone.utc).replace(tzinfo=None)
    e = end.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return await _period_sales(db, s, e)


async def inventory_summary(db: AsyncSession) -> InventorySummary:
    active = (
        await db.execute(select(Product.id).where(Product.is_active.is_(True)))
    ).scalars()
    product_ids = [p for p in active]
    product_count = len(product_ids)

    units_total = 0
    cost_value = Decimal("0")
    retail_value = Decimal("0")
    low_count = 0
    out_count = 0

    # cost & retail value in one pass over open batches joined to products.
    rows = await db.execute(
        select(
            InventoryBatch.product_id,
            InventoryBatch.qty_remaining,
            InventoryBatch.unit_cost,
            Product.default_selling_price,
            Product.low_stock_threshold,
        )
        .join(Product, Product.id == InventoryBatch.product_id)
        .where(InventoryBatch.qty_remaining > 0)
    )
    by_product: dict[int, dict] = {}
    for pid, rem, unit_cost, price, threshold in rows:
        d = by_product.setdefault(
            pid,
            {"units": 0, "cost": Decimal("0"), "retail": Decimal("0"), "threshold": threshold},
        )
        d["units"] += rem
        d["cost"] += (Decimal(str(unit_cost)) * rem)
        price_val = float(price) if price is not None else 0.0
        d["retail"] += Decimal(str(price_val)) * rem

    for pid in product_ids:
        d = by_product.get(pid, {"units": 0, "cost": Decimal("0"), "retail": Decimal("0"), "threshold": 0})
        units_total += d["units"]
        cost_value += d["cost"]
        retail_value += d["retail"]
        if d["units"] <= 0:
            out_count += 1
        elif d["units"] <= (d["threshold"] or 0):
            low_count += 1

    return InventorySummary(
        product_count=product_count,
        units=units_total,
        cost_value=float(cost_value),
        retail_value=float(retail_value),
        low_stock_count=low_count,
        out_of_stock_count=out_count,
    )


async def low_stock_products(
    db: AsyncSession, limit: int = 50
) -> list[tuple[Product, int]]:
    """Products at or below their threshold (excluding out-of-stock ones)."""
    products = (
        await db.execute(select(Product).where(Product.is_active.is_(True)))
    ).scalars()
    result: list[tuple[Product, int]] = []
    for p in products:
        units = await product_stock(db, p.id)
        if 0 < units <= (p.low_stock_threshold or 0):
            result.append((p, units))
    return result[:limit]


async def top_products(
    db: AsyncSession,
    sort: str = "revenue",
    limit: int = 10,
    start: Optional[dt.datetime] = None,
) -> list[TopProduct]:
    """Rank products over a period (default: all time) by units/revenue/profit."""
    where = [Sale.status == SaleStatus.ACTIVE]
    if start is not None:
        where.append(Sale.created_at >= start)

    order_map = {
        "units": func.sum(SaleItem.quantity),
        "revenue": func.sum(SaleItem.revenue),
        "gross": func.sum(SaleItem.gross_profit),
    }
    order_col = order_map.get(sort, order_map["revenue"])

    rows = (
        await db.execute(
            select(
                SaleItem.product_id,
                func.sum(SaleItem.quantity),
                func.sum(SaleItem.revenue),
                func.sum(SaleItem.gross_profit),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(*where)
            .group_by(SaleItem.product_id)
            .order_by(order_col.desc())
            .limit(limit)
        )
    ).all()

    result: list[TopProduct] = []
    for pid, units, revenue, gross in rows:
        product = await db.get(Product, pid)
        if product is None:
            continue
        result.append(
            TopProduct(
                product_id=pid,
                name=product.name,
                units=int(units or 0),
                revenue=float(revenue or 0),
                gross_profit=float(gross or 0),
            )
        )
    return result


async def sales_history(
    db: AsyncSession, limit: int = 20, offset: int = 0
) -> list[Sale]:
    result = await db.execute(
        select(Sale)
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(limit)
        .offset(offset)
    )
    sales = list(result.scalars().all())
    for s in sales:
        await db.refresh(s, ["items"])
    return sales
