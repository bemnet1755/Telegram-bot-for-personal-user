"""Product CRUD, search, archive, and photo handling.

Handlers stay thin; all state changes live here and are committed.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    InventoryBatch,
    Product,
    Sale,
    SaleItem,
    SaleStatus,
)

MAX_PRODUCTS = 100000  # sanity cap, not a business limit


class ProductNotFoundError(Exception):
    def __init__(self, product_id: int):
        self.product_id = product_id
        super().__init__(f"Product {product_id} not found")


async def create_product(
    db: AsyncSession,
    name: str,
    *,
    sku: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    photo_file_id: Optional[str] = None,
    default_selling_price: Optional[float] = None,
    low_stock_threshold: int = 0,
) -> Product:
    name = (name or "").strip()
    if not name:
        raise ValueError("Product name is required")
    product = Product(
        name=name,
        sku=sku.strip() if sku and sku.strip() else None,
        description=(description or "").strip() or None,
        category=(category or "").strip() or None,
        brand=(brand or "").strip() or None,
        photo_file_id=photo_file_id,
        default_selling_price=default_selling_price,
        low_stock_threshold=max(0, low_stock_threshold),
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def get_product(db: AsyncSession, product_id: int) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise ProductNotFoundError(product_id)
    return product


async def list_active_products(db: AsyncSession, limit: int = 100, offset: int = 0):
    result = await db.execute(
        select(Product)
        .where(Product.is_active.is_(True))
        .order_by(Product.name)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def search_products(
    db: AsyncSession, query: str, limit: int = 25
) -> list[Product]:
    """Search active products by name, SKU, brand, or category (case-insensitive)."""
    query = (query or "").strip()
    if not query:
        return []
    like = f"%{query}%"
    result = await db.execute(
        select(Product)
        .where(
            Product.is_active.is_(True),
            or_(
                Product.name.ilike(like),
                Product.sku.ilike(like),
                Product.brand.ilike(like),
                Product.category.ilike(like),
            ),
        )
        .order_by(Product.name)
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_product(
    db: AsyncSession,
    product: Product,
    *,
    name: Optional[str] = None,
    sku: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    default_selling_price: Optional[float] = None,
    low_stock_threshold: Optional[int] = None,
) -> Product:
    """Update mutable fields. Pass None to leave a field unchanged (except price,
    which uses -1 sentinel semantics below is NOT supported; use explicit value)."""
    if name is not None:
        product.name = name.strip()
    if sku is not None:
        product.sku = sku.strip() or None
    if description is not None:
        product.description = description.strip() or None
    if category is not None:
        product.category = category.strip() or None
    if brand is not None:
        product.brand = brand.strip() or None
    if default_selling_price is not None:
        product.default_selling_price = default_selling_price
    if low_stock_threshold is not None:
        product.low_stock_threshold = max(0, low_stock_threshold)
    await db.commit()
    await db.refresh(product)
    return product


async def set_photo(db: AsyncSession, product: Product, file_id: str) -> Product:
    """Attach/replace the Telegram photo file_id for a product."""
    product.photo_file_id = file_id
    await db.commit()
    await db.refresh(product)
    return product


async def archive_product(db: AsyncSession, product: Product) -> Product:
    """Soft-delete: keep all history, hide from active lists."""
    product.is_active = False
    await db.commit()
    await db.refresh(product)
    return product


async def restore_product(db: AsyncSession, product: Product) -> Product:
    product.is_active = True
    await db.commit()
    await db.refresh(product)
    return product


async def batch_summary(
    db: AsyncSession, product_id: int
) -> tuple[int, Optional[float], float, float]:
    """Return (units, newest_batch_cost, cost_value, retail_value) for a product.

    * newest_batch_cost: the cost of the most recently received open batch, or
      the product's last known purchase cost if none remains.
    * cost_value: sum(remaining * unit_cost) over open batches.
    * retail_value: sum(remaining * selling_price) using the product's
      current default selling price.
    """
    result = await db.execute(
        select(
            InventoryBatch.unit_cost,
            InventoryBatch.received_at,
            InventoryBatch.qty_remaining,
        )
        .where(
            InventoryBatch.product_id == product_id,
            InventoryBatch.qty_remaining > 0,
        )
        .order_by(InventoryBatch.received_at.desc(), InventoryBatch.id.desc())
    )
    rows = list(result.all())

    units = sum(r[2] for r in rows)
    cost_value = sum(float(r[0]) * r[2] for r in rows)
    newest_cost = rows[0][0] if rows else None

    product = await db.get(Product, product_id)
    price = float(product.default_selling_price) if product and product.default_selling_price is not None else 0.0
    retail_value = units * price
    return units, (float(newest_cost) if newest_cost is not None else None), cost_value, retail_value
