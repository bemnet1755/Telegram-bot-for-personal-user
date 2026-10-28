"""Inventory operations: receive stock, apply adjustments, list history.

Every stock change creates an :class:`InventoryMovement` (and, for inbound,
an :class:`InventoryBatch`), so inventory is fully auditable.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    InventoryBatch,
    InventoryMovement,
    Product,
)
from app.services import product_service
from app.services.exceptions import DomainError, InvalidQuantityError


async def add_purchase(
    db: AsyncSession,
    product_id: int,
    quantity: int,
    unit_cost: float,
    *,
    supplier: Optional[str] = None,
    note: Optional[str] = None,
) -> InventoryBatch:
    """Receive a stock purchase.

    Creates one FIFO batch and one PURCHASE movement. The on-hand stock
    increases by ``quantity``.
    """
    from app.database.models import MovementType
    from decimal import Decimal

    if quantity <= 0:
        raise InvalidQuantityError(quantity)
    if unit_cost < 0:
        raise DomainError("Purchase cost cannot be negative")

    await product_service.get_product(db, product_id)

    movement = InventoryMovement(
        product_id=product_id,
        quantity=quantity,
        movement_type=MovementType.PURCHASE,
        note=note,
    )
    db.add(movement)
    await db.flush()

    batch = InventoryBatch(
        product_id=product_id,
        qty_received=quantity,
        qty_remaining=quantity,
        unit_cost=Decimal(str(unit_cost)),
        supplier=supplier,
        note=note,
        movement_id=movement.id,
    )
    movement.batch_id = batch.id
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def apply_adjustment(
    db: AsyncSession,
    product_id: int,
    delta: int,
    *,
    reason: Optional[str] = None,
    damage: bool = False,
) -> InventoryMovement:
    """Correct stock with an audited ADJUSTMENT_IN/OUT or DAMAGE movement.

    Inbound adjustments create a zero-cost batch so the units are sellable;
    outbound adjustments remove units from the newest batches first (they
    carry no cost, so COGS history is untouched).
    """
    from app.database.models import MovementType
    from decimal import Decimal

    if delta == 0:
        raise InvalidQuantityError(delta)

    await product_service.get_product(db, product_id)

    if delta > 0:
        movement_type = MovementType.ADJUSTMENT_IN
    else:
        movement_type = MovementType.DAMAGE if damage else MovementType.ADJUSTMENT_OUT

    movement = InventoryMovement(
        product_id=product_id,
        quantity=delta,
        movement_type=movement_type,
        note=reason,
    )
    db.add(movement)
    await db.flush()

    if delta > 0:
        batch = InventoryBatch(
            product_id=product_id,
            qty_received=delta,
            qty_remaining=delta,
            unit_cost=Decimal("0.00"),
            note=reason,
            movement_id=movement.id,
        )
        movement.batch_id = batch.id
        db.add(batch)
    else:
        await _remove_units(db, product_id, -delta)

    await db.commit()
    await db.refresh(movement)
    return movement


async def _remove_units(db: AsyncSession, product_id: int, count: int) -> None:
    """Remove ``count`` units from the newest batches (FIFO-safe for outbound)."""
    from app.services.fifo_service import FifoEngine
    from app.services.exceptions import InsufficientStockError

    batches = await FifoEngine._open_batches(db, product_id)
    total = sum(b.qty_remaining for b in batches)
    if count > total:
        raise InsufficientStockError(count, total)

    # Remove from newest first so the oldest (lowest-cost) stock survives.
    newest = list(reversed(batches))
    remaining = count
    for batch in newest:
        if remaining <= 0:
            break
        take = min(batch.qty_remaining, remaining)
        batch.qty_remaining -= take
        remaining -= take


async def history(
    db: AsyncSession,
    product_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[InventoryMovement]:
    """Recent movements for a product, newest first, with batch/sale context."""
    result = await db.execute(
        select(InventoryMovement)
        .where(InventoryMovement.product_id == product_id)
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def movements_count(db: AsyncSession, product_id: int) -> int:
    result = await db.execute(
        select(func.count(InventoryMovement.id)).where(
            InventoryMovement.product_id == product_id
        )
    )
    return int(result.scalar_one() or 0)


def stock_status(product: Product, units: int) -> str:
    """Return 'out' | 'low' | 'ok' based on the low-stock threshold."""
    if units <= 0:
        return "out"
    threshold = product.low_stock_threshold or 0
    if units <= threshold:
        return "low"
    return "ok"
