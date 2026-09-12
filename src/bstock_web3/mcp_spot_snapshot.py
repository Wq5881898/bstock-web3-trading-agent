"""Strict parser for sanitized Binance Agent OS Spot read results.

The caller owns MCP tool invocation.  This module accepts the returned JSON and
produces the venue-neutral risk evidence; it cannot perform a tool call.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from .execution_contract import ProductType
from .execution_safety import McpReconciliationEvidence


MCP_SPOT_READ_TOOLS = (
    "spot.getAccount", "spot.getOpenOrders", "spot.myTrades",
    "spot.allOrders", "spot.accountCommission", "spot.exchangeInfo",
    "spot.tickerBookTicker",
)


def _decimal(value, name, *, allow_zero=True):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Invalid {name}") from None
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise ValueError(f"Invalid {name}")
    return result


@dataclass(frozen=True)
class LocalRiskMetrics:
    daily_equity_loss: Decimal
    daily_entries: int = 0
    consecutive_losses: int = 0
    last_entry_ms: int | None = None


def _position_cost(trades, symbol, base_asset, quote_asset):
    quantity = Decimal("0")
    cost = Decimal("0")
    for row in sorted(trades, key=lambda item: item.get("time", -1)):
        if not isinstance(row, dict) or row.get("symbol") != symbol:
            raise ValueError("Invalid Spot trade history")
        qty = _decimal(row.get("qty"), "trade quantity", allow_zero=False)
        quote = _decimal(row.get("quoteQty"), "trade quote", allow_zero=False)
        commission = _decimal(row.get("commission", 0), "trade commission")
        commission_asset = row.get("commissionAsset")
        if commission and commission_asset not in {base_asset, quote_asset}:
            raise ValueError("Third-asset commission requires explicit risk accounting")
        if type(row.get("isBuyer")) is not bool:
            raise ValueError("Invalid Spot trade side")
        if row["isBuyer"]:
            acquired = qty - (commission if commission_asset == base_asset else 0)
            spent = quote + (commission if commission_asset == quote_asset else 0)
            if acquired <= 0:
                raise ValueError("Invalid net bought quantity")
            quantity += acquired
            cost += spent
        else:
            disposed = qty + (commission if commission_asset == base_asset else 0)
            if disposed > quantity:
                raise ValueError("Trade history cannot explain sold quantity")
            if quantity:
                cost -= cost * disposed / quantity
            quantity -= disposed
    return quantity, max(cost, Decimal("0"))


def build_mcp_spot_evidence(
    *, account: dict, open_orders: list, trades: list, all_orders: list,
    book: dict, account_ref: str, expected_uid: int, symbol: str,
    base_asset: str, quote_asset: str, risk_day: str, observed_at_ms: int,
    evidence_id: str, risk: LocalRiskMetrics, trade_history_complete: bool,
) -> McpReconciliationEvidence:
    """Fail closed unless the MCP reads describe one explainable Spot position."""
    if (not isinstance(account, dict) or type(expected_uid) is not int
            or account.get("uid") != expected_uid):
        raise ValueError("Agentic account identity mismatch")
    if account.get("accountType") != "SPOT" or type(account.get("canTrade")) is not bool:
        raise ValueError("Invalid Spot account response")
    if not isinstance(open_orders, list) or not isinstance(trades, list) \
            or not isinstance(all_orders, list):
        raise ValueError("Invalid Spot account collections")
    if trade_history_complete is not True:
        raise ValueError("Complete paginated trade history is required")
    if not isinstance(risk, LocalRiskMetrics):
        raise ValueError("Invalid local risk metrics")
    if not re.fullmatch(r"[A-Z0-9]{1,32}", symbol):
        raise ValueError("Invalid Spot symbol")
    if not isinstance(book, dict) or book.get("symbol") != symbol:
        raise ValueError("Invalid Spot book response")
    bid = _decimal(book.get("bidPrice"), "bid price", allow_zero=False)
    ask = _decimal(book.get("askPrice"), "ask price", allow_zero=False)
    if bid > ask:
        raise ValueError("Crossed Spot book")
    balances = account.get("balances")
    if not isinstance(balances, list):
        raise ValueError("Invalid Spot balances")
    by_asset = {}
    for row in balances:
        if not isinstance(row, dict) or not isinstance(row.get("asset"), str):
            raise ValueError("Invalid Spot balance row")
        if row["asset"] in by_asset:
            raise ValueError("Duplicate Spot balance asset")
        by_asset[row["asset"]] = (
            _decimal(row.get("free"), "free balance"),
            _decimal(row.get("locked"), "locked balance"))
    if any(asset not in {base_asset, quote_asset} and free + locked > 0
           for asset, (free, locked) in by_asset.items()):
        raise ValueError("Unsupported nonzero asset in single-symbol account")
    available_quote = by_asset.get(quote_asset, (Decimal("0"), Decimal("0")))[0]
    base_free, base_locked = by_asset.get(
        base_asset, (Decimal("0"), Decimal("0")))
    actual_quantity = base_free + base_locked
    explained_quantity, position_cost = _position_cost(
        trades, symbol, base_asset, quote_asset)
    tolerance = Decimal("0.00000001")
    if abs(actual_quantity - explained_quantity) > tolerance:
        raise ValueError("Trade history does not reconcile Spot base balance")
    if any(not isinstance(row, dict) or row.get("symbol") != symbol
           for row in all_orders):
        raise ValueError("Invalid Spot order history")
    order_ids = {row.get("orderId") for row in all_orders}
    if any(row.get("orderId") not in order_ids for row in trades):
        raise ValueError("Spot fills do not reconcile order history")
    matching_open = [row for row in open_orders if isinstance(row, dict)
                     and row.get("symbol") == symbol]
    if len(matching_open) != len(open_orders):
        raise ValueError("Open-order response contains another symbol")
    pending = None
    if matching_open:
        pending = str(matching_open[0].get("orderId") or
                      matching_open[0].get("clientOrderId") or "unknown")
    return McpReconciliationEvidence(
        evidence_id=evidence_id, account_ref=account_ref, symbol=symbol,
        product=ProductType.SPOT, risk_day=risk_day,
        observed_at_ms=observed_at_ms, account_checked=True,
        balances_checked=True, open_orders_checked=True, fills_checked=True,
        can_trade=account["canTrade"], available_quote=available_quote,
        position_quantity=actual_quantity, position_cost=position_cost,
        daily_equity_loss=risk.daily_equity_loss,
        daily_entries=risk.daily_entries,
        consecutive_losses=risk.consecutive_losses,
        last_entry_ms=risk.last_entry_ms, pending_order_id=pending)
