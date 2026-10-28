"""Natural-language input, rule-based.

Turns short, structured phrases like "Bought 20 black shirts for 400 each,
selling for 700" into parsed fields. This is deliberately simple and has NO
LLM dependency — structured buttons remain the source of truth. If the user
later configures an LLM provider (see Settings), this module can hand off,
but the rule parser is always available.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedIntent:
    """Result of parsing a free-text command."""

    kind: str  # "buy" | "sell" | "unknown"
    product_query: str = ""
    quantity: Optional[int] = None
    unit_cost: Optional[float] = None
    selling_price: Optional[float] = None
    confidence: str = "low"  # "low" | "medium" | "high"
    ambiguities: list[str] = field(default_factory=list)

    @property
    def needs_confirmation(self) -> bool:
        """Anything less than 'high' confidence must be confirmed by the user."""
        return self.confidence != "high" or bool(self.ambiguities)


_NUM = r"-?\d[\d,]*(?:\.\d+)?"


def parse(text: str) -> ParsedIntent:
    """Parse a user message into a structured intent.

    Recognizes two families:
      * purchases: "bought / bought / got / received / restocked N <product>
        for <cost> each"
      * sales: "sold N <product>"
    """
    lowered = (text or "").lower().strip()
    if not lowered:
        return ParsedIntent(kind="unknown")

    intent = ParsedIntent(kind="unknown")

    # ---- purchases ----
    if any(k in lowered for k in ("bought", "got", "received", "restock", "add stock", "purchase")):
        intent.kind = "buy"
        intent.quantity, rest = _take_quantity(lowered)
        if "for" in lowered:
            intent.unit_cost = _cost_after_for(lowered)
        price_match = re.search(r"sell(?:ing)?(?:\s+them)?\s+for\s+" + _NUM, lowered)
        if price_match:
            intent.selling_price = _to_float(price_match.group(1))
        intent.product_query = _strip_numbers_and_keywords(lowered)
        _set_confidence(intent)
        return intent

    # ---- sales ----
    if "sold" in lowered or "sell" in lowered:
        intent.kind = "sell"
        intent.quantity, rest = _take_quantity(lowered)
        intent.product_query = _strip_numbers_and_keywords(lowered)
        _set_confidence(intent)
        return intent

    return ParsedIntent(kind="unknown", product_query=_strip_numbers_and_keywords(lowered))


def _take_quantity(text: str):
    """Return (quantity, remainder); quantity is None when not found."""
    m = re.search(r"\b(\d[\d,]*)\b", text)
    if not m:
        return None, text
    return int(m.group(1).replace(",", "")), text


def _cost_after_for(text: str) -> Optional[float]:
    m = re.search(r"\bfor\s+(" + _NUM + r")", text)
    return _to_float(m.group(1)) if m else None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _strip_numbers_and_keywords(text: str) -> str:
    """Remove quantities/keywords so we can match the product name."""
    stop = {
        "bought", "got", "received", "restock", "add", "stock", "purchase",
        "sold", "sell", "selling", "them", "for", "each", "unit", "units",
        "price", "cost", "and", "i", "am", "is", "the", "a", "an",
    }
    cleaned = re.sub(r"\d[\d,]*(?:\.\d+)?", " ", text)
    tokens = [t for t in cleaned.split() if t not in stop]
    return " ".join(tokens).strip()


# ---- post-processing ----
def _set_confidence(intent: ParsedIntent) -> None:
    """Set a conservative confidence: even fully-parsed intents need a confirm."""
    if intent.kind in ("buy", "sell") and intent.quantity and intent.product_query:
        intent.confidence = "medium"
    else:
        intent.confidence = "low"
