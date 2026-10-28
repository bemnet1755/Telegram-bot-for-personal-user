"""Shared enumeration types used by the models."""
from __future__ import annotations

import enum


class MovementType(str, enum.Enum):
    """Kinds of inventory movement, ordered by intent.

    POSITIVE moves add stock; NEGATIVE moves remove it. Every change is
    recorded as a movement, never a silent column edit.
    """

    PURCHASE = "PURCHASE"
    SALE = "SALE"
    RETURN = "RETURN"
    ADJUSTMENT_IN = "ADJUSTMENT_IN"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT"
    DAMAGE = "DAMAGE"

    @property
    def is_inbound(self) -> bool:
        return self in (
            MovementType.PURCHASE,
            MovementType.RETURN,
            MovementType.ADJUSTMENT_IN,
        )


class SaleStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    CARD = "CARD"
    TRANSFER = "TRANSFER"
    OTHER = "OTHER"
