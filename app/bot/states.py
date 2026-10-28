"""Conversation states (FSM) for the structured flows.

Every multi-step flow keeps its partial data in aiogram's user-data dict
rather than many separate states, which keeps handlers simpler. A single
``Flow`` object is stored under ``flow``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from aiogram.fsm.state import State, StatesGroup


class AddProductStates(StatesGroup):
    awaiting_name = State()
    awaiting_sku = State()
    awaiting_category = State()
    awaiting_price = State()
    awaiting_threshold = State()
    awaiting_photo = State()


class AddStockStates(StatesGroup):
    awaiting_product = State()
    awaiting_quantity = State()
    awaiting_cost = State()
    awaiting_supplier = State()
    awaiting_note = State()
    awaiting_confirm = State()


class SellStates(StatesGroup):
    awaiting_product = State()
    awaiting_quantity = State()
    awaiting_price = State()
    awaiting_confirm = State()


class AdjustStates(StatesGroup):
    awaiting_delta = State()
    awaiting_reason = State()
    awaiting_confirm = State()


class SearchStates(StatesGroup):
    awaiting_query = State()


class CancelStates(StatesGroup):
    awaiting_sale = State()


@dataclass
class Flow:
    """Scratch space for the active conversation."""

    kind: str
    data: dict = field(default_factory=dict)
