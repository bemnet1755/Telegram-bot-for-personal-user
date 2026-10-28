"""Initial schema: all tables.

Revision ID: 001
Revises:
Create Date: 2026-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- products ---
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("brand", sa.String(100), nullable=True),
        sa.Column("photo_file_id", sa.String(512), nullable=True),
        sa.Column("default_selling_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_brand", "products", ["brand"])

    # --- sales (created before inventory_movements which references it) ---
    op.create_table(
        "sales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sale_number", sa.String(20), nullable=False),
        sa.Column("total_revenue", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_cogs", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_gross_profit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column(
            "payment_method",
            sa.String(16),
            nullable=False,
            server_default="CASH",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sale_number", name="uq_sales_sale_number"),
    )
    op.create_index("ix_sales_sale_number", "sales", ["sale_number"])
    op.create_index("ix_sales_created_at", "sales", ["created_at"])

    # --- sale_items ---
    op.create_table(
        "sale_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_selling_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("revenue", sa.Numeric(18, 2), nullable=False),
        sa.Column("cogs", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_profit", sa.Numeric(18, 2), nullable=False),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sale_items_sale_id", "sale_items", ["sale_id"])
    op.create_index("ix_sale_items_product_id", "sale_items", ["product_id"])

    # --- inventory_movements (references sale_items + sales; batches added later) ---
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(32), nullable=False),
        sa.Column("sale_item_id", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.Integer(), nullable=True),  # FK added after batches table
        sa.Column("sale_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sale_item_id"], ["sale_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_movements_product_id", "inventory_movements", ["product_id"])
    op.create_index("ix_inventory_movements_movement_type", "inventory_movements", ["movement_type"])
    op.create_index("ix_inventory_movements_created_at", "inventory_movements", ["created_at"])

    # --- inventory_batches (references inventory_movements) ---
    op.create_table(
        "inventory_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty_received", sa.Integer(), nullable=False),
        sa.Column("qty_remaining", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supplier", sa.String(200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("movement_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["movement_id"], ["inventory_movements.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint("qty_received > 0", name="ck_batch_qty_received_positive"),
        sa.CheckConstraint("qty_remaining >= 0", name="ck_batch_qty_remaining_nonneg"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_batches_product_id", "inventory_batches", ["product_id"])
    op.create_index("ix_inventory_batches_received_at", "inventory_batches", ["received_at"])

    # Add batch_id FK to inventory_movements now that the table exists (PostgreSQL/standard).
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_movements_batch_id",
            "inventory_movements",
            "inventory_batches",
            ["batch_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # --- fifo_consumptions ---
    op.create_table(
        "fifo_consumptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sale_item_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("cogs", sa.Numeric(18, 2), nullable=False),
        sa.ForeignKeyConstraint(["sale_item_id"], ["sale_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["inventory_batches.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("sale_item_id", "batch_id", name="uq_fifo_item_batch"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fifo_consumptions_sale_item_id", "fifo_consumptions", ["sale_item_id"])
    op.create_index("ix_fifo_consumptions_batch_id", "fifo_consumptions", ["batch_id"])

    # --- app_settings ---
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_settings_key"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_settings_key", "app_settings", ["key"])


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("fifo_consumptions")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("fk_movements_batch_id", "inventory_movements", type_="foreignkey")
    op.drop_table("inventory_batches")
    op.drop_table("inventory_movements")
    op.drop_table("sale_items")
    op.drop_table("sales")
    op.drop_table("products")
