"""Execution boundary shared by Spot, Web3 and future derivatives adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .strategy import SignalDecision
from .strategy_registry import ensure_strategy_supports


class ProductType(StrEnum):
    SPOT = "SPOT"
    WEB3_SPOT = "WEB3_SPOT"
    FUTURES = "FUTURES"


class PositionAction(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    CLOSE_LONG = "CLOSE_LONG"


@dataclass(frozen=True)
class ExecutionInstrument:
    symbol: str
    product: ProductType
    venue: str
    base_asset: str
    quote_asset: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OrderIntent:
    strategy_id: str
    instrument: ExecutionInstrument
    action: PositionAction
    reference_price: Decimal
    reason: str
    strategy_params: dict = field(default_factory=dict)
    reduce_only: bool = False


@dataclass(frozen=True)
class ExecutionReceipt:
    external_id: str
    state: str
    filled_base: Decimal | None = None
    filled_quote: Decimal | None = None


@runtime_checkable
class ExecutionAdapter(Protocol):
    """A venue plugin; it must not calculate indicators or strategy signals."""
    product: ProductType

    def preview(self, intent: OrderIntent): ...
    def submit(self, preview, *, authorization=None) -> ExecutionReceipt: ...
    def status(self, external_id: str) -> ExecutionReceipt: ...


def order_intent(decision: SignalDecision, instrument: ExecutionInstrument) -> OrderIntent | None:
    if decision.action == "hold":
        return None
    if decision.price is None:
        raise ValueError("Executable strategy decision requires a price")
    if not decision.strategy_id:
        raise ValueError("Executable strategy decision requires a registered strategy_id")
    ensure_strategy_supports(decision.strategy_id, instrument.product)
    price = Decimal(str(decision.price))
    if not price.is_finite() or price <= 0:
        raise ValueError("Invalid strategy reference price")
    action = PositionAction.OPEN_LONG if decision.action == "buy" else PositionAction.CLOSE_LONG
    return OrderIntent(decision.strategy_id, instrument, action, price,
        decision.reason, dict(decision.strategy_params), decision.action == "sell")
