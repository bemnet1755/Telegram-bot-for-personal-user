"""Domain exceptions.

Handlers translate these into friendly user-facing messages; the raw
exception (and traceback) is logged server-side but never shown to the user.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all expected business-rule failures."""


class InsufficientStockError(DomainError):
    def __init__(self, requested: int, available: int):
        self.requested = requested
        self.available = available
        super().__init__(f"Requested {requested}, only {available} available")


class ProductNotFoundError(DomainError):
    def __init__(self, product_id: int):
        self.product_id = product_id
        super().__init__(f"Product {product_id} not found")


class InvalidQuantityError(DomainError):
    def __init__(self, value):
        self.value = value
        super().__init__(f"Invalid quantity: {value!r}")


class InvalidPriceError(DomainError):
    def __init__(self, value):
        self.value = value
        super().__init__(f"Invalid price: {value!r}")
