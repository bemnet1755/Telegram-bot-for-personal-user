"""Tests for the reporting service."""
from __future__ import annotations

import datetime as dt

import pytest

from app.database.models import Product, product_stock
from app.database.models.enums import SaleStatus
from app.services import inventory_service, product_service, reporting_service, sales_service
from app.services.sales_service import SaleLine


UTC = dt.timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_product(
    db,
    name: str = "Widget",
    price: float = 200.0,
    threshold: int = 0,
) -> Product:
    return await product_service.create_product(
        db, name, default_selling_price=price, low_stock_threshold=threshold
    )


async def _stock_up(db, product: Product, qty: int, cost: float = 100.0) -> None:
    await inventory_service.add_purchase(db, product.id, qty, cost)


async def _sell(db, product: Product, qty: int, price: float | None = None) -> None:
    await sales_service.record_sale(
        db, [SaleLine(product.id, qty, price)]
    )


# ---------------------------------------------------------------------------
# period_summary / today_summary
# ---------------------------------------------------------------------------


class TestPeriodSummary:
    async def test_empty_period(self, db) -> None:
        tzinfo = dt.timezone.utc
        result = await reporting_service.today_summary(db, tzinfo)
        assert result.sales_count == 0
        assert result.revenue == 0.0
        assert result.gross_profit == 0.0

    async def test_single_sale_today(self, db) -> None:
        product = await _create_product(db, price=500.0)
        await _stock_up(db, product, 10, cost=200.0)
        await _sell(db, product, 2)

        tzinfo = dt.timezone.utc
        result = await reporting_service.today_summary(db, tzinfo)
        assert result.sales_count == 1
        assert result.revenue == pytest.approx(1000.0)
        assert result.cogs == pytest.approx(400.0)
        assert result.gross_profit == pytest.approx(600.0)
        assert result.units_sold == 2

    async def test_margin_calculation(self, db) -> None:
        product = await _create_product(db, price=200.0)
        await _stock_up(db, product, 10, cost=100.0)
        await _sell(db, product, 1)

        tzinfo = dt.timezone.utc
        result = await reporting_service.today_summary(db, tzinfo)
        # gross profit = 100, revenue = 200, margin = 50%
        assert result.margin_pct == pytest.approx(50.0)

    async def test_cancelled_sale_excluded(self, db) -> None:
        product = await _create_product(db, price=500.0)
        await _stock_up(db, product, 10, cost=200.0)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 2)])
        await sales_service.cancel_sale(db, confirmed.sale.id)

        tzinfo = dt.timezone.utc
        result = await reporting_service.today_summary(db, tzinfo)
        assert result.sales_count == 0
        assert result.revenue == 0.0

    async def test_week_summary(self, db) -> None:
        product = await _create_product(db, price=100.0)
        await _stock_up(db, product, 20, cost=50.0)
        await _sell(db, product, 5)

        tzinfo = dt.timezone.utc
        result = await reporting_service.week_summary(db, tzinfo)
        assert result.sales_count >= 1
        assert result.revenue == pytest.approx(500.0)

    async def test_month_summary(self, db) -> None:
        product = await _create_product(db, price=100.0)
        await _stock_up(db, product, 20, cost=50.0)
        await _sell(db, product, 3)

        tzinfo = dt.timezone.utc
        result = await reporting_service.this_month_summary(db, tzinfo)
        assert result.sales_count >= 1
        assert result.revenue == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# inventory_summary
# ---------------------------------------------------------------------------


class TestInventorySummary:
    async def test_empty_inventory(self, db) -> None:
        result = await reporting_service.inventory_summary(db)
        assert result.product_count == 0
        assert result.units == 0
        assert result.cost_value == 0.0
        assert result.retail_value == 0.0

    async def test_single_product_values(self, db) -> None:
        product = await _create_product(db, price=500.0)
        await _stock_up(db, product, 10, cost=200.0)

        result = await reporting_service.inventory_summary(db)
        assert result.product_count == 1
        assert result.units == 10
        assert result.cost_value == pytest.approx(2000.0)
        assert result.retail_value == pytest.approx(5000.0)

    async def test_out_of_stock_counted(self, db) -> None:
        product = await _create_product(db, price=100.0, threshold=5)
        # No stock added
        result = await reporting_service.inventory_summary(db)
        assert result.out_of_stock_count == 1

    async def test_low_stock_counted(self, db) -> None:
        product = await _create_product(db, price=100.0, threshold=5)
        await _stock_up(db, product, 3, cost=50.0)

        result = await reporting_service.inventory_summary(db)
        assert result.low_stock_count == 1
        assert result.out_of_stock_count == 0


# ---------------------------------------------------------------------------
# top_products
# ---------------------------------------------------------------------------


class TestTopProducts:
    async def test_empty_returns_empty(self, db) -> None:
        result = await reporting_service.top_products(db)
        assert result == []

    async def test_rankings_by_revenue(self, db) -> None:
        p1 = await _create_product(db, "Cheap", price=10.0)
        p2 = await _create_product(db, "Expensive", price=1000.0)
        await _stock_up(db, p1, 20, cost=5.0)
        await _stock_up(db, p2, 10, cost=500.0)

        await _sell(db, p1, 10)  # revenue = 100
        await _sell(db, p2, 3)   # revenue = 3000

        tops = await reporting_service.top_products(db, sort="revenue", limit=2)
        assert tops[0].product_id == p2.id
        assert tops[1].product_id == p1.id

    async def test_cancelled_sales_excluded(self, db) -> None:
        product = await _create_product(db, price=100.0)
        await _stock_up(db, product, 10, cost=50.0)
        confirmed = await sales_service.record_sale(db, [SaleLine(product.id, 5)])
        await sales_service.cancel_sale(db, confirmed.sale.id)

        tops = await reporting_service.top_products(db, sort="revenue")
        assert tops == []


# ---------------------------------------------------------------------------
# sales_history
# ---------------------------------------------------------------------------


class TestSalesHistory:
    async def test_history_empty(self, db) -> None:
        history = await reporting_service.sales_history(db)
        assert history == []

    async def test_history_ordered_newest_first(self, db) -> None:
        product = await _create_product(db, price=100.0)
        await _stock_up(db, product, 20, cost=50.0)
        r1 = await sales_service.record_sale(db, [SaleLine(product.id, 1)])
        r2 = await sales_service.record_sale(db, [SaleLine(product.id, 1)])

        history = await reporting_service.sales_history(db)
        # Sale 2 should be first (newest)
        assert history[0].id == r2.sale.id
        assert history[1].id == r1.sale.id

    async def test_history_limit(self, db) -> None:
        product = await _create_product(db, price=100.0)
        await _stock_up(db, product, 20, cost=50.0)
        for _ in range(5):
            await sales_service.record_sale(db, [SaleLine(product.id, 1)])

        history = await reporting_service.sales_history(db, limit=3)
        assert len(history) == 3
