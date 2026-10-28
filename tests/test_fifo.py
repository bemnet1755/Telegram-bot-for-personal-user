"""Tests for the FIFO engine (fifo_service.py).

Verifies:
- Correct FIFO allocation order (oldest batch first).
- COGS calculation precision.
- InsufficientStockError when stock is low.
- Batch qty_remaining decremented correctly after consume().
- FifoConsumption rows written correctly.
- revert() restores qty_remaining to the original batches.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import pytest_asyncio

from app.database.models import FifoConsumption, InventoryBatch, Product, SaleItem, Sale
from app.database.models.enums import MovementType, PaymentMethod, SaleStatus
from app.services.exceptions import InsufficientStockError
from app.services.fifo_service import BatchAllocation, FifoEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(offset_days: int = 0) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=offset_days)


async def _make_product(db, name: str = "Widget") -> Product:
    p = Product(name=name, low_stock_threshold=0)
    db.add(p)
    await db.flush()
    return p


async def _make_batch(
    db,
    product: Product,
    qty: int,
    unit_cost: float,
    received_at: dt.datetime | None = None,
) -> InventoryBatch:
    b = InventoryBatch(
        product_id=product.id,
        qty_received=qty,
        qty_remaining=qty,
        unit_cost=Decimal(str(unit_cost)),
        received_at=received_at or _utc(),
    )
    db.add(b)
    await db.flush()
    return b


async def _make_sale_item(db, product: Product, sale: Sale, qty: int) -> SaleItem:
    si = SaleItem(
        sale_id=sale.id,
        product_id=product.id,
        quantity=qty,
        unit_selling_price=Decimal("100.00"),
        revenue=Decimal(str(qty * 100)),
        cogs=Decimal("0"),
        gross_profit=Decimal(str(qty * 100)),
    )
    db.add(si)
    await db.flush()
    return si


async def _make_sale(db) -> Sale:
    sale = Sale(
        sale_number="#000001",
        payment_method=PaymentMethod.CASH,
        status=SaleStatus.ACTIVE,
    )
    db.add(sale)
    await db.flush()
    return sale


# ---------------------------------------------------------------------------
# allocate() — pure function, no DB
# ---------------------------------------------------------------------------


class TestAllocate:
    """Tests for FifoEngine.allocate (pure, synchronous)."""

    def _batch(self, id_: int, qty: int, cost: float, days_ago: int = 0) -> "InventoryBatch":
        """Create a minimal mock batch using SimpleNamespace (no DB session needed)."""
        from types import SimpleNamespace
        b = SimpleNamespace(
            id=id_,
            qty_remaining=qty,
            unit_cost=Decimal(str(cost)),
            received_at=_utc(-days_ago),
        )
        return b  # type: ignore[return-value]

    def test_single_batch_full(self) -> None:
        b = self._batch(1, 10, 5.00)
        allocs = FifoEngine.allocate([b], 10)
        assert len(allocs) == 1
        assert allocs[0].quantity == 10
        assert allocs[0].cogs == Decimal("50.00")

    def test_single_batch_partial(self) -> None:
        b = self._batch(1, 10, 5.00)
        allocs = FifoEngine.allocate([b], 3)
        assert allocs[0].quantity == 3
        assert allocs[0].cogs == Decimal("15.00")

    def test_multi_batch_fifo_order(self) -> None:
        # Two batches: oldest first (b1), then b2.
        b1 = self._batch(1, 5, 10.00, days_ago=5)
        b2 = self._batch(2, 10, 20.00, days_ago=0)
        allocs = FifoEngine.allocate([b1, b2], 7)
        assert allocs[0].batch_id == 1
        assert allocs[0].quantity == 5
        assert allocs[1].batch_id == 2
        assert allocs[1].quantity == 2
        # cogs = 5*10 + 2*20 = 90
        total_cogs = sum(a.cogs for a in allocs)
        assert total_cogs == Decimal("90.00")

    def test_insufficient_stock_raises(self) -> None:
        b = self._batch(1, 5, 5.00)
        with pytest.raises(InsufficientStockError) as exc_info:
            FifoEngine.allocate([b], 10)
        assert exc_info.value.requested == 10
        assert exc_info.value.available == 5

    def test_empty_batches_raises(self) -> None:
        with pytest.raises(InsufficientStockError):
            FifoEngine.allocate([], 1)

    def test_cogs_precision(self) -> None:
        """COGS must be rounded to 2 dp."""
        b = self._batch(1, 3, 1 / 3)  # 0.333... per unit
        allocs = FifoEngine.allocate([b], 3)
        # Each allocation COGS rounded to 2dp
        for a in allocs:
            assert a.cogs == a.cogs.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# consume() — touches DB
# ---------------------------------------------------------------------------


class TestConsume:
    async def test_consume_decrements_batch(self, db) -> None:
        product = await _make_product(db)
        batch = await _make_batch(db, product, 10, 5.00)
        sale = await _make_sale(db)
        item = await _make_sale_item(db, product, sale, 6)

        allocs = await FifoEngine.consume(db, item, 6)

        assert len(allocs) == 1
        assert allocs[0].quantity == 6
        await db.refresh(batch)
        assert batch.qty_remaining == 4

    async def test_consume_writes_fifo_consumption_rows(self, db) -> None:
        product = await _make_product(db)
        b1 = await _make_batch(db, product, 5, 10.00, received_at=_utc(-2))
        b2 = await _make_batch(db, product, 5, 20.00, received_at=_utc(-1))
        sale = await _make_sale(db)
        item = await _make_sale_item(db, product, sale, 7)

        allocs = await FifoEngine.consume(db, item, 7)
        await db.flush()

        from sqlalchemy import select
        rows = (
            await db.execute(
                select(FifoConsumption).where(FifoConsumption.sale_item_id == item.id)
            )
        ).scalars().all()
        assert len(rows) == 2
        quantities = {r.batch_id: r.quantity for r in rows}
        assert quantities[b1.id] == 5
        assert quantities[b2.id] == 2

    async def test_consume_insufficient_raises(self, db) -> None:
        product = await _make_product(db)
        await _make_batch(db, product, 3, 5.00)
        sale = await _make_sale(db)
        item = await _make_sale_item(db, product, sale, 10)

        with pytest.raises(InsufficientStockError):
            await FifoEngine.consume(db, item, 10)


# ---------------------------------------------------------------------------
# revert() — restore stock
# ---------------------------------------------------------------------------


class TestRevert:
    async def test_revert_restores_qty_remaining(self, db) -> None:
        product = await _make_product(db)
        batch = await _make_batch(db, product, 10, 5.00)
        sale = await _make_sale(db)
        item = await _make_sale_item(db, product, sale, 4)

        await FifoEngine.consume(db, item, 4)
        await db.flush()
        await db.refresh(batch)
        assert batch.qty_remaining == 6

        # Now revert.
        from sqlalchemy import select
        consumptions = (
            await db.execute(
                select(FifoConsumption).where(FifoConsumption.sale_item_id == item.id)
            )
        ).scalars().all()
        total_returned = await FifoEngine.revert(db, consumptions)

        await db.refresh(batch)
        assert batch.qty_remaining == 10
        assert total_returned == 4
