"""Sales: record, reverse, and read.

A sale always happens inside a single database transaction: create the
Sale + SaleItems, consume FIFO batches, compute COGS / gross profit, and
write a SALE movement. If anything fails, the whole thing rolls back.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    FifoConsumption,
    InventoryMovement,
    Product,
    Sale,
    SaleItem,
    SaleStatus,
    utcnow,
)
from app.database.models.enums import MovementType, PaymentMethod
from app.services import product_service
from app.services.exceptions import DomainError, InvalidPriceError, InvalidQuantityError
from app.services.fifo_service import FifoEngine


@dataclass
class SaleLine:
    """One line on the sales screen: what to record for a given product."""

    product_id: int
    quantity: int
    unit_price: Optional[float] = None  # None -> use product's default selling price

    @property
    def line_revenue(self) -> float:
        return 0.0  # computed with default price when None


@dataclass
class ConfirmedSale:
    """Everything the UI needs after a sale is recorded."""

    sale: Sale
    items: list[SaleItem]
    remaining_by_product: dict[int, int]
    low_stock: list[tuple[Product, int]]  # products that just hit the threshold


async def next_sale_number(db: AsyncSession) -> str:
    """Return the next zero-padded sale number, e.g. '#000104'."""
    result = await db.execute(select(func.max(Sale.sale_number)))
    last = result.scalar_one_or_none()
    if last is None:
        return "#000001"
    try:
        n = int(last.lstrip("#"))
    except ValueError:
        n = 0
    return f"#{n + 1:06d}"


async def record_sale(
    db: AsyncSession,
    lines: list[SaleLine],
    *,
    payment_method: PaymentMethod = PaymentMethod.CASH,
    note: Optional[str] = None,
    allow_negative_stock: bool = False,
) -> ConfirmedSale:
    """Record a (possibly multi-line) sale with FIFO consumption.

    Steps, all in one transaction:
      1. Resolve products and prices (default selling price if not given).
      2. Create the Sale + SaleItems with revenue/cogs/gross_profit.
      3. Consume FIFO batches, writing one SALE movement per item.
      4. Compute totals and commit.
    """
    if not lines:
        raise DomainError("No sale lines provided")

    sale_number = await next_sale_number(db)
    sale = Sale(
        sale_number=sale_number,
        payment_method=payment_method,
        note=note,
    )
    db.add(sale)
    await db.flush()

    total_revenue = Decimal("0")
    total_cogs = Decimal("0")
    created_items: list[SaleItem] = []
    remaining_by_product: dict[int, int] = {}
    low_stock: list[tuple[Product, int]] = []

    for line in lines:
        if line.quantity <= 0:
            raise InvalidQuantityError(line.quantity)

        product = await product_service.get_product(db, line.product_id)
        price = line.unit_price if line.unit_price is not None else (
            float(product.default_selling_price) if product.default_selling_price is not None else 0.0
        )
        if price < 0:
            raise InvalidPriceError(price)

        revenue = (Decimal(str(price)) * line.quantity).quantize(Decimal("0.01"))

        item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=line.quantity,
            unit_selling_price=Decimal(str(price)),
            revenue=revenue,
            cogs=Decimal("0"),
            gross_profit=revenue,  # corrected after FIFO consumption
        )
        db.add(item)
        await db.flush()

        # Consume FIFO batches; this may raise InsufficientStockError.
        allocations = await FifoEngine.consume(db, item, line.quantity)
        item_cogs = sum(a.cogs for a in allocations)
        item.cogs = item_cogs
        item.gross_profit = revenue - item_cogs

        total_revenue += revenue
        total_cogs += item_cogs

        # Record the SALE movement (outbound, signed negative).
        movement = InventoryMovement(
            product_id=product.id,
            quantity=-line.quantity,
            movement_type=MovementType.SALE,
            sale_item_id=item.id,
            sale_id=sale.id,
        )
        db.add(movement)

        created_items.append(item)

        # Remaining stock after this sale.
        remaining = await FifoEngine.available(db, product.id)
        remaining_by_product[product.id] = remaining
        if remaining <= (product.low_stock_threshold or 0):
            low_stock.append((product, remaining))

    sale.total_revenue = total_revenue
    sale.total_cogs = total_cogs
    sale.total_gross_profit = total_revenue - total_cogs

    await db.commit()
    await db.refresh(sale)
    return ConfirmedSale(
        sale=sale,
        items=created_items,
        remaining_by_product=remaining_by_product,
        low_stock=low_stock,
    )


async def get_sale(db: AsyncSession, sale_id: int) -> Sale:
    sale = await db.get(Sale, sale_id)
    if sale is None:
        raise DomainError(f"Sale {sale_id} not found")
    await db.refresh(sale, ["items"])
    return sale


async def get_sale_item(db: AsyncSession, item_id: int) -> SaleItem:
    item = await db.get(SaleItem, item_id)
    if item is None:
        raise DomainError(f"Sale item {item_id} not found")
    return item


async def cancel_sale(
    db: AsyncSession,
    sale_id: int,
    *,
    note: Optional[str] = None,
) -> Sale:
    """Reverse a sale: mark CANCELLED, return stock, and write reversing
    RETURN movements. The original rows stay for the audit trail."""
    sale = await get_sale(db, sale_id)
    if sale.status == SaleStatus.CANCELLED:
        raise DomainError("Sale is already cancelled")

    total_units_returned = 0
    for item in sale.items:
        await db.refresh(item)
        consumptions = list(
            (
                await db.execute(
                    select(FifoConsumption).where(
                        FifoConsumption.sale_item_id == item.id
                    )
                )
            ).scalars()
        )
        if consumptions:
            returned = await FifoEngine.revert(db, consumptions)
        else:
            returned = item.quantity
            # No consumption records; restore as a zero-cost batch.
            from app.database.models import InventoryBatch
            from decimal import Decimal as _Decimal

            batch = InventoryBatch(
                product_id=item.product_id,
                qty_received=returned,
                qty_remaining=returned,
                unit_cost=_Decimal("0.00"),
                note="sale-cancel-restore",
            )
            db.add(batch)
            await db.flush()

        total_units_returned += returned

        movement = InventoryMovement(
            product_id=item.product_id,
            quantity=returned,
            movement_type=MovementType.RETURN,
            sale_item_id=item.id,
            sale_id=sale.id,
            note=note,
        )
        db.add(movement)

    sale.status = SaleStatus.CANCELLED
    sale.cancelled_at = utcnow()
    await db.commit()
    await db.refresh(sale)
    return sale
