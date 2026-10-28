"""First-In-First-Out (FIFO) inventory engine.

Consumes stock from the oldest open batch first so that COGS reflects the
actual historical purchase cost of the units sold. Batch locks are taken with
``FOR UPDATE`` so two concurrent sales cannot double-spend the same units.

Nothing here commits on its own; the caller (``sales_service``) owns the
transaction so the whole sale (record + consumption) is atomic.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    FifoConsumption,
    InventoryBatch,
    SaleItem,
    product_stock,
)
from app.services.exceptions import InsufficientStockError


@dataclass
class BatchAllocation:
    """How many units a sale takes out of a specific batch."""

    batch_id: int
    quantity: int
    unit_cost: Decimal
    cogs: Decimal

    @property
    def total(self) -> Decimal:
        return self.cogs


class FifoEngine:
    """Reads/writes FIFO batch consumption within the caller's transaction."""

    @staticmethod
    async def available(db: AsyncSession, product_id: int) -> int:
        """Units currently on hand for a product."""
        return await product_stock(db, product_id)

    @staticmethod
    async def _open_batches(db: AsyncSession, product_id: int) -> list[InventoryBatch]:
        """Open batches oldest-first, row-locked to serialize FIFO consumption."""
        result = await db.execute(
            select(InventoryBatch)
            .where(
                InventoryBatch.product_id == product_id,
                InventoryBatch.qty_remaining > 0,
            )
            .order_by(InventoryBatch.received_at, InventoryBatch.id)
            .with_for_update()
        )
        return list(result.scalars().all())

    @classmethod
    def allocate(cls, batches: list[InventoryBatch], quantity: int) -> list[BatchAllocation]:
        """Pure function: split ``quantity`` across ``batches`` in FIFO order."""
        total = sum(b.qty_remaining for b in batches)
        if total < quantity:
            raise InsufficientStockError(quantity, total)

        allocations: list[BatchAllocation] = []
        remaining = quantity
        for batch in batches:
            if remaining <= 0:
                break
            take = min(batch.qty_remaining, remaining)
            unit_cost = Decimal(str(batch.unit_cost))
            cogs = (unit_cost * take).quantize(Decimal("0.01"))
            allocations.append(
                BatchAllocation(
                    batch_id=batch.id,
                    quantity=take,
                    unit_cost=unit_cost,
                    cogs=cogs,
                )
            )
            remaining -= take
        return allocations

    @classmethod
    async def consume(
        cls,
        db: AsyncSession,
        sale_item: SaleItem,
        quantity: int,
    ) -> list[BatchAllocation]:
        """Consume ``quantity`` units for ``sale_item`` from FIFO batches.

        Locks the batches, allocates, decrements ``qty_remaining``, and writes
        one :class:`FifoConsumption` audit row per batch. Caller commits.
        """
        batches = await cls._open_batches(db, sale_item.product_id)
        allocations = cls.allocate(batches, quantity)

        batch_map = {b.id: b for b in batches}
        for alloc in allocations:
            batch = batch_map[alloc.batch_id]
            batch.qty_remaining -= alloc.quantity
            db.add(
                FifoConsumption(
                    sale_item_id=sale_item.id,
                    batch_id=alloc.batch_id,
                    quantity=alloc.quantity,
                    unit_cost=alloc.unit_cost,
                    cogs=alloc.cogs,
                )
            )
        await db.flush()
        return allocations

    @staticmethod
    async def revert(
        db: AsyncSession,
        consumption_rows: list[FifoConsumption],
    ) -> int:
        """Put stock back for a reversed sale.

        Re-adds units to the exact batches that were consumed (restored into
        those batches, not re-priced). Returns the total units returned.
        """
        units = 0
        # Restore into the newest-consumed batches first so the FIFO order is
        # preserved as closely as possible.
        ordered = sorted(consumption_rows, key=lambda r: r.id, reverse=True)
        rows_by_batch: dict[int, list[FifoConsumption]] = {}
        for row in ordered:
            rows_by_batch.setdefault(row.batch_id, []).append(row)

        for batch_id, rows in rows_by_batch.items():
            batch = await db.get(InventoryBatch, batch_id)
            if batch is None:
                continue
            qty = sum(r.quantity for r in rows)
            batch.qty_remaining += qty
            units += qty
        await db.flush()
        return units
