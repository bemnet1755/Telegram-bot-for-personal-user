"""SQLAlchemy 2.x ORM models.

Design notes
------------
* All money is stored as ``Numeric(18,2)`` so we never do float arithmetic
  on financial quantities.
* Inventory is NOT a denormalized counter on the product. It is the sum of
  open batches plus a delta for unbatched corrections. See
  :func:`product_stock` and :class:`InventoryBatch`.
* Historical COGS is frozen at sale time in :class:`SaleItem` and
  :class:`FifoConsumption` so later cost changes never rewrite the past.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from .enums import MovementType, PaymentMethod, SaleStatus


class Base(DeclarativeBase):
    """Declarative base shared by all models and by Alembic's metadata."""


def utcnow() -> dt.datetime:
    """Timezone-aware UTC timestamp (always stored in UTC)."""
    return dt.datetime.now(dt.timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    sku: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Telegram photo file_id (no external hosting required).
    photo_file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Money
    default_selling_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)

    # Inventory guardrail
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    batches: Mapped[list["InventoryBatch"]] = relationship(
        "InventoryBatch", back_populates="product", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Product id={self.id} name={self.name!r}>"


class InventoryBatch(Base):
    """A lot of units bought at a single purchase cost.

    ``qty_received`` is fixed at creation time; ``qty_remaining`` changes
    over time. Batches are the only place where physical units live, so
    stock counts never drift from batch records.
    """

    __tablename__ = "inventory_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    qty_received: Mapped[int] = mapped_column(Integer)
    qty_remaining: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 2))
    received_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    supplier: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    movement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("inventory_movements.id", ondelete="SET NULL"), nullable=True
    )

    product: Mapped["Product"] = relationship("Product", back_populates="batches")

    __table_args__ = (
        CheckConstraint("qty_received > 0", name="ck_batch_qty_received_positive"),
        CheckConstraint("qty_remaining >= 0", name="ck_batch_qty_remaining_nonneg"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InventoryBatch id={self.id} product={self.product_id} rem={self.qty_remaining}>"


class InventoryMovement(Base):
    """Every stock change, auditable and reversible.

    * ``quantity`` is signed: positive for inbound, negative for outbound.
    * ``batch_id`` links a batch-creating movement (PURCHASE / RETURN) to the
      batch it produced.
    * ``sale_item_id`` links an outbound SALE movement to the sale item it
      served.
    """

    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    movement_type: Mapped[MovementType] = mapped_column(
        SAEnum(
            *MovementType,
            name="movement_type",
            native_enum=False,
            length=32,
            create_constraint=True,
        ),
        index=True,
    )
    sale_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sale_items.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("inventory_batches.id", ondelete="SET NULL"), nullable=True
    )
    sale_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InventoryMovement id={self.id} {self.movement_type} qty={self.quantity}>"


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human-friendly sequential number, e.g. #000123
    sale_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    total_revenue: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_cogs: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_gross_profit: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(*PaymentMethod, name="payment_method", native_enum=False, length=16),
        default=PaymentMethod.CASH,
        server_default="CASH",
    )
    status: Mapped[SaleStatus] = mapped_column(
        SAEnum(*SaleStatus, name="sale_status", native_enum=False, length=16),
        default=SaleStatus.ACTIVE,
        server_default="ACTIVE",
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    cancelled_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["SaleItem"]] = relationship(
        "SaleItem", back_populates="sale", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Sale id={self.id} number={self.sale_number}>"


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    unit_selling_price: Mapped[float] = mapped_column(Numeric(18, 2))
    revenue: Mapped[float] = mapped_column(Numeric(18, 2))
    cogs: Mapped[float] = mapped_column(Numeric(18, 2))
    gross_profit: Mapped[float] = mapped_column(Numeric(18, 2))

    sale: Mapped["Sale"] = relationship("Sale", back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SaleItem id={self.id} product={self.product_id} qty={self.quantity}>"


class FifoConsumption(Base):
    """Per-batch record of how a sale item consumed inventory (FIFO audit).

    Multiple rows share the same ``sale_item_id``; together they must equal
    the item's ``quantity`` and the costs that produced its ``cogs``.
    """

    __tablename__ = "fifo_consumptions"
    __table_args__ = (
        UniqueConstraint("sale_item_id", "batch_id", name="uq_fifo_item_batch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_item_id: Mapped[int] = mapped_column(
        ForeignKey("sale_items.id", ondelete="CASCADE"), index=True
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_batches.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 2))
    cogs: Mapped[float] = mapped_column(Numeric(18, 2))


class AppSetting(Base):
    """Key/value store for user-configurable settings (currency, timezone, ...)."""

    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_settings_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------


async def product_stock(db, product_id: int) -> int:
    """On-hand units for a product.

    Batches are the single source of truth for physical units, so on-hand
    stock is simply the sum of open batches' ``qty_remaining``. Every
    inventory operation (purchase, sale, return, adjustment) mutates a
    batch, which keeps this figure consistent with the FIFO ledger.
    """
    result = await db.execute(
        select(func.sum(InventoryBatch.qty_remaining)).where(
            InventoryBatch.product_id == product_id,
            InventoryBatch.qty_remaining > 0,
        )
    )
    return int(result.scalar_one_or_none() or 0)
