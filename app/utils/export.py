"""CSV export for backup. One function per exportable dataset.

Each returns a byte string so the bot can send it straight to Telegram as a
document without writing to disk.
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    InventoryMovement,
    Product,
    Sale,
    SaleItem,
)


def _to_csv(rows: Iterable[tuple]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return buffer.getvalue()


async def products_csv(db: AsyncSession) -> bytes:
    rows = [
        (
            p.id,
            p.name,
            p.sku or "",
            p.brand or "",
            p.category or "",
            p.default_selling_price,
            p.low_stock_threshold,
            p.is_active,
            p.photo_file_id or "",
            p.created_at,
        )
        for p in (await db.execute(select(Product))).scalars()
    ]
    header = [
        "id", "name", "sku", "brand", "category",
        "default_selling_price", "low_stock_threshold", "is_active",
        "photo_file_id", "created_at",
    ]
    return _to_csv([header, *rows]).encode("utf-8")


async def sales_csv(db: AsyncSession) -> bytes:
    """One row per sale item, including its sale number and financials."""
    result = await db.execute(
        select(
            Sale.sale_number,
            Sale.created_at,
            Sale.payment_method,
            Sale.status,
            SaleItem.product_id,
            SaleItem.quantity,
            SaleItem.unit_selling_price,
            SaleItem.revenue,
            SaleItem.cogs,
            SaleItem.gross_profit,
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .order_by(Sale.created_at, Sale.id)
    )
    rows = []
    for (
        number, created, payment, status, pid, qty, price, revenue, cogs, gross
    ) in result:
        rows.append(
            (
                number,
                created,
                payment.value,
                status.value,
                pid,
                qty,
                _dec(price),
                _dec(revenue),
                _dec(cogs),
                _dec(gross),
            )
        )
    header = [
        "sale_number", "created_at", "payment_method", "status",
        "product_id", "quantity", "unit_price", "revenue", "cogs", "gross_profit",
    ]
    return _to_csv([header, *rows]).encode("utf-8")


async def movements_csv(db: AsyncSession) -> bytes:
    result = await db.execute(
        select(
            InventoryMovement.id,
            InventoryMovement.product_id,
            InventoryMovement.movement_type,
            InventoryMovement.quantity,
            InventoryMovement.created_at,
            InventoryMovement.note,
        ).order_by(InventoryMovement.created_at, InventoryMovement.id)
    )
    rows = [
        (m[0], m[1], m[2].value if m[2] else "", m[3], m[4], m[5] or "")
        for m in result
    ]
    header = ["id", "product_id", "movement_type", "quantity", "created_at", "note"]
    return _to_csv([header, *rows]).encode("utf-8")


def _dec(value) -> str:
    """Format a Numeric/Decimal cell cleanly for CSV."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)
