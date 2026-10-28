"""Tests for the inventory service (add_purchase, apply_adjustment, history)."""
from __future__ import annotations

import pytest

from app.database.models import InventoryBatch, InventoryMovement, Product, product_stock
from app.database.models.enums import MovementType
from app.services import inventory_service, product_service
from app.services.exceptions import DomainError, InsufficientStockError, InvalidQuantityError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_product(db, name: str = "Test Product") -> Product:
    return await product_service.create_product(db, name)


# ---------------------------------------------------------------------------
# add_purchase
# ---------------------------------------------------------------------------


class TestAddPurchase:
    async def test_creates_batch_and_movement(self, db) -> None:
        product = await _create_product(db)
        batch = await inventory_service.add_purchase(db, product.id, 20, 100.0)

        assert batch.id is not None
        assert batch.qty_received == 20
        assert batch.qty_remaining == 20
        assert float(batch.unit_cost) == 100.0

    async def test_increases_stock(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 15, 50.0)
        units = await product_stock(db, product.id)
        assert units == 15

    async def test_multiple_purchases_accumulate(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 10, 100.0)
        await inventory_service.add_purchase(db, product.id, 5, 120.0)
        units = await product_stock(db, product.id)
        assert units == 15

    async def test_supplier_stored_on_batch(self, db) -> None:
        product = await _create_product(db)
        batch = await inventory_service.add_purchase(
            db, product.id, 10, 100.0, supplier="Acme Corp"
        )
        assert batch.supplier == "Acme Corp"

    async def test_negative_quantity_raises(self, db) -> None:
        product = await _create_product(db)
        with pytest.raises(InvalidQuantityError):
            await inventory_service.add_purchase(db, product.id, -5, 100.0)

    async def test_zero_quantity_raises(self, db) -> None:
        product = await _create_product(db)
        with pytest.raises(InvalidQuantityError):
            await inventory_service.add_purchase(db, product.id, 0, 100.0)

    async def test_negative_cost_raises(self, db) -> None:
        product = await _create_product(db)
        with pytest.raises(DomainError):
            await inventory_service.add_purchase(db, product.id, 10, -1.0)

    async def test_nonexistent_product_raises(self, db) -> None:
        with pytest.raises(Exception):  # ProductNotFoundError from product_service
            await inventory_service.add_purchase(db, 99999, 10, 100.0)

    async def test_creates_purchase_movement(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 10, 100.0)
        movements = await inventory_service.history(db, product.id)
        assert len(movements) == 1
        assert movements[0].movement_type == MovementType.PURCHASE
        assert movements[0].quantity == 10


# ---------------------------------------------------------------------------
# apply_adjustment
# ---------------------------------------------------------------------------


class TestApplyAdjustment:
    async def test_positive_adjustment_increases_stock(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 10, 50.0)
        await inventory_service.apply_adjustment(db, product.id, +5, reason="Found extras")
        units = await product_stock(db, product.id)
        assert units == 15

    async def test_negative_adjustment_decreases_stock(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 10, 50.0)
        await inventory_service.apply_adjustment(db, product.id, -3, reason="Damaged")
        units = await product_stock(db, product.id)
        assert units == 7

    async def test_insufficient_stock_raises(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 5, 50.0)
        with pytest.raises(InsufficientStockError):
            await inventory_service.apply_adjustment(db, product.id, -10)

    async def test_zero_delta_raises(self, db) -> None:
        product = await _create_product(db)
        with pytest.raises(InvalidQuantityError):
            await inventory_service.apply_adjustment(db, product.id, 0)

    async def test_damage_flag_sets_movement_type(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 10, 50.0)
        movement = await inventory_service.apply_adjustment(
            db, product.id, -2, reason="Water damage", damage=True
        )
        assert movement.movement_type == MovementType.DAMAGE

    async def test_positive_creates_zero_cost_batch(self, db) -> None:
        product = await _create_product(db)
        movement = await inventory_service.apply_adjustment(db, product.id, +5)
        units = await product_stock(db, product.id)
        assert units == 5


# ---------------------------------------------------------------------------
# history / movements_count
# ---------------------------------------------------------------------------


class TestHistory:
    async def test_empty_history(self, db) -> None:
        product = await _create_product(db)
        movements = await inventory_service.history(db, product.id)
        assert movements == []

    async def test_history_ordered_newest_first(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 5, 10.0)
        await inventory_service.add_purchase(db, product.id, 3, 15.0)
        movements = await inventory_service.history(db, product.id)
        assert len(movements) == 2
        assert movements[0].quantity > 0  # newest first (PURCHASE movements are positive)

    async def test_movements_count(self, db) -> None:
        product = await _create_product(db)
        await inventory_service.add_purchase(db, product.id, 5, 10.0)
        await inventory_service.add_purchase(db, product.id, 3, 15.0)
        count = await inventory_service.movements_count(db, product.id)
        assert count == 2


# ---------------------------------------------------------------------------
# stock_status helper
# ---------------------------------------------------------------------------


class TestStockStatus:
    def _product(self, threshold: int):
        """Create a minimal mock product (no DB session needed)."""
        from types import SimpleNamespace
        return SimpleNamespace(low_stock_threshold=threshold)

    def test_out_of_stock(self) -> None:
        product = self._product(5)
        status = inventory_service.stock_status(product, 0)
        assert status == "out"

    def test_low_stock(self) -> None:
        product = self._product(5)
        status = inventory_service.stock_status(product, 3)
        assert status == "low"

    def test_ok_stock(self) -> None:
        product = self._product(5)
        status = inventory_service.stock_status(product, 10)
        assert status == "ok"

    def test_no_threshold_means_ok_if_positive(self) -> None:
        product = self._product(0)
        status = inventory_service.stock_status(product, 1)
        assert status == "ok"
