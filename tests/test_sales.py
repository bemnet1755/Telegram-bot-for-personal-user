"""Tests for the sales service (record_sale, cancel_sale)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.database.models import InventoryBatch, Product, Sale, SaleItem, product_stock
from app.database.models.enums import SaleStatus
from app.services import inventory_service, product_service, sales_service
from app.services.exceptions import DomainError, InsufficientStockError, InvalidQuantityError
from app.services.sales_service import SaleLine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_product(
    db,
    name: str = "Widget",
    price: float | None = 200.0,
    threshold: int = 0,
) -> Product:
    return await product_service.create_product(
        db, name, default_selling_price=price, low_stock_threshold=threshold
    )


async def _stock_up(db, product: Product, qty: int, cost: float = 100.0) -> None:
    await inventory_service.add_purchase(db, product.id, qty, cost)


# ---------------------------------------------------------------------------
# next_sale_number
# ---------------------------------------------------------------------------


class TestNextSaleNumber:
    async def test_first_sale_number(self, db) -> None:
        number = await sales_service.next_sale_number(db)
        assert number == "#000001"

    async def test_increments_correctly(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 10)
        await sales_service.record_sale(db, [SaleLine(product.id, 1)])
        number = await sales_service.next_sale_number(db)
        assert number == "#000002"


# ---------------------------------------------------------------------------
# record_sale
# ---------------------------------------------------------------------------


class TestRecordSale:
    async def test_basic_sale(self, db) -> None:
        product = await _create_product(db, price=500.0)
        await _stock_up(db, product, 10, cost=200.0)

        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 3)])

        assert confirmed.sale.id is not None
        assert confirmed.sale.status == SaleStatus.ACTIVE
        assert len(confirmed.items) == 1
        item = confirmed.items[0]
        assert item.quantity == 3
        assert float(item.revenue) == pytest.approx(1500.0)  # 3 * 500
        assert float(item.cogs) == pytest.approx(600.0)  # 3 * 200
        assert float(item.gross_profit) == pytest.approx(900.0)

    async def test_sale_decreases_stock(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 10)
        initial = await product_stock(db, product.id)
        await sales_service.record_sale(db, [SaleLine(product.id, 4)])
        remaining = await product_stock(db, product.id)
        assert remaining == initial - 4

    async def test_sale_totals_on_sale_row(self, db) -> None:
        product = await _create_product(db, price=100.0)
        await _stock_up(db, product, 20, cost=50.0)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 5)])
        sale = confirmed.sale
        assert float(sale.total_revenue) == pytest.approx(500.0)
        assert float(sale.total_cogs) == pytest.approx(250.0)
        assert float(sale.total_gross_profit) == pytest.approx(250.0)

    async def test_custom_price_overrides_default(self, db) -> None:
        product = await _create_product(db, price=100.0)
        await _stock_up(db, product, 10)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 2, 300.0)])
        assert float(confirmed.items[0].revenue) == pytest.approx(600.0)

    async def test_insufficient_stock_raises(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 3)
        with pytest.raises(InsufficientStockError) as exc_info:
            await sales_service.record_sale(db, [SaleLine(product.id, 10)])
        assert exc_info.value.requested == 10
        assert exc_info.value.available == 3

    async def test_zero_quantity_raises(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 10)
        with pytest.raises(InvalidQuantityError):
            await sales_service.record_sale(db, [SaleLine(product.id, 0)])

    async def test_empty_lines_raises(self, db) -> None:
        with pytest.raises(DomainError):
            await sales_service.record_sale(db, [])

    async def test_low_stock_trigger(self, db) -> None:
        product = await _create_product(db, price=100.0, threshold=3)
        await _stock_up(db, product, 5)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 3)])
        # remaining=2 which is below threshold=3, so should appear in low_stock
        assert len(confirmed.low_stock) == 1
        assert confirmed.low_stock[0][0].id == product.id

    async def test_multi_batch_fifo_cogs(self, db) -> None:
        """FIFO: sell from oldest batch first."""
        product = await _create_product(db, price=None)
        await _stock_up(db, product, 5, cost=10.0)   # batch 1 (older)
        await _stock_up(db, product, 5, cost=20.0)   # batch 2 (newer)
        # Sell 7: should consume 5 @ 10 + 2 @ 20 = 90
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 7, 0.0)])
        assert float(confirmed.items[0].cogs) == pytest.approx(90.0)

    async def test_sale_number_sequential(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 20)
        r1 = await sales_service.record_sale(db, [SaleLine(product.id, 1)])
        r2 = await sales_service.record_sale(db, [SaleLine(product.id, 1)])
        assert r1.sale.sale_number == "#000001"
        assert r2.sale.sale_number == "#000002"

    async def test_remaining_by_product(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 10)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 4)])
        assert confirmed.remaining_by_product[product.id] == 6


# ---------------------------------------------------------------------------
# cancel_sale
# ---------------------------------------------------------------------------


class TestCancelSale:
    async def test_cancel_marks_sale_cancelled(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 10)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 3)])
        sale_id = confirmed.sale.id

        cancelled = await sales_service.cancel_sale(db, sale_id)
        assert cancelled.status == SaleStatus.CANCELLED
        assert cancelled.cancelled_at is not None

    async def test_cancel_returns_stock(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 10)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 4)])
        remaining_after_sale = await product_stock(db, product.id)
        assert remaining_after_sale == 6

        await sales_service.cancel_sale(db, confirmed.sale.id)
        remaining_after_cancel = await product_stock(db, product.id)
        assert remaining_after_cancel == 10

    async def test_cancel_already_cancelled_raises(self, db) -> None:
        product = await _create_product(db)
        await _stock_up(db, product, 10)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 2)])
        await sales_service.cancel_sale(db, confirmed.sale.id)
        with pytest.raises(DomainError):
            await sales_service.cancel_sale(db, confirmed.sale.id)

    async def test_cancel_nonexistent_raises(self, db) -> None:
        with pytest.raises(DomainError):
            await sales_service.cancel_sale(db, 99999)
