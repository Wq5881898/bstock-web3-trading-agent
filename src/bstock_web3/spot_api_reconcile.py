"""Fail-closed Binance Spot account snapshot for an API-backed session."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path

from .mcp_confirmed import SpotMarketRules
from .mcp_spot_snapshot import (build_bound_mcp_spot_evidence,
    build_local_risk_metrics)
from .spot_accounting import SpotFillLedger, normalize_fills
from .spot_equity_risk import EquityObservation, SpotEquityRiskLedger


@dataclass(frozen=True)
class SpotApiSnapshot:
    evidence: object
    rules: SpotMarketRules
    commission: dict
    book: dict
    filled_order_ids: frozenset[int] = frozenset()


class SpotApiReconciler:
    """Full-history checks plus durable no-external-cashflow guard.

    The dedicated session account must not be manually funded/withdrawn while
    running. Quote/base balance changes unexplained by fills block execution.
    """

    def __init__(self, api, directory: Path, *, account_ref: str,
                 symbol: str, base_asset: str, quote_asset: str):
        self.api = api
        self.directory = Path(directory)
        self.account_ref, self.symbol = account_ref, symbol
        self.base_asset, self.quote_asset = base_asset, quote_asset
        self.fills = SpotFillLedger(self.directory / "fills.json",
            account_ref=account_ref, symbol=symbol, base_asset=base_asset,
            quote_asset=quote_asset)
        self.equity = SpotEquityRiskLedger(self.directory / "equity.json",
            account_ref=account_ref, symbol=symbol)
        self.balance_path = self.directory / "balance-checkpoint.json"

    def initialize(self, *, now_ms: int):
        if self.balance_path.exists() or self.equity.path.exists():
            raise RuntimeError("Spot session baseline already exists")
        return self._read(now_ms=now_ms, initial=True)

    def read(self, *, now_ms: int):
        if not self.balance_path.exists() or not self.equity.path.exists():
            raise RuntimeError("Spot session baseline is not initialized")
        return self._read(now_ms=now_ms, initial=False)

    def _all_pages(self, name, cursor_key, item_id):
        rows, cursor = [], 0
        for _ in range(100):
            page = getattr(self.api, name)(self.symbol, **{cursor_key: cursor}, limit=1000)
            if not isinstance(page, list) or len(page) > 1000:
                raise ValueError("Invalid Spot history page")
            if any(not isinstance(row, dict) or type(row.get(item_id)) is not int
                   or row[item_id] < cursor for row in page):
                raise ValueError("Invalid Spot history cursor")
            if page and any(page[i][item_id] >= page[i + 1][item_id]
                            for i in range(len(page) - 1)):
                raise ValueError("Unordered Spot history page")
            rows.extend(page)
            if len(page) < 1000:
                return rows
            cursor = page[-1][item_id] + 1
        raise RuntimeError("Spot history exceeds bounded pagination")

    def _read(self, *, now_ms: int, initial: bool):
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("Invalid snapshot time")
        info = self.api.exchange_info(self.symbol)
        rules = SpotMarketRules.from_exchange_info(info, self.symbol)
        if (rules.base_asset != self.base_asset or rules.quote_asset != self.quote_asset):
            raise ValueError("Spot instrument identity changed")
        open_orders = self.api.open_orders_all()
        if (not isinstance(open_orders, list)
                or any(not isinstance(row, dict) or row.get("symbol") != self.symbol
                       for row in open_orders)):
            raise ValueError("Another Spot symbol has an open order")
        trades = self._all_pages("my_trades", "from_id", "id")
        all_orders = self._all_pages("all_orders", "order_id", "orderId")
        commission = self.api.commission(self.symbol)
        if not isinstance(commission, dict) or commission.get("symbol") != self.symbol:
            raise ValueError("Unverified Spot commission")
        try:
            for kind in ("standardCommission", "specialCommission", "taxCommission"):
                section = commission[kind]
                for side in ("taker", "buyer", "seller"):
                    rate = Decimal(str(section[side]))
                    if not rate.is_finite() or rate < 0:
                        raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError("Unverified Spot commission") from None
        book = self.api.book_ticker(self.symbol)
        account = self.api.account()
        if not isinstance(account, dict):
            raise ValueError("Invalid Spot account")
        account = {key: value for key, value in account.items() if key != "uid"}
        normalized = normalize_fills(trades, self.symbol, self.base_asset,
                                     self.quote_asset)
        quote_total, base_total = self._balances(account)
        self._check_quote_continuity(quote_total, normalized, initial=initial)
        observation = EquityObservation(
            datetime.fromtimestamp(now_ms / 1000, timezone.utc).date().isoformat(),
            now_ms, quote_total, base_total, Decimal(str(book["bidPrice"])))
        with self.fills as ledger:
            ledger.sync(trades, history_complete=True)
        with self.equity as ledger:
            if initial:
                equity_result = ledger.initialize(observation, [],
                    history_complete=True, operator_confirmed=True)
            else:
                equity_result = ledger.observe(observation, [], history_complete=True)
        risk = build_local_risk_metrics(trades=trades, symbol=self.symbol,
            base_asset=self.base_asset, quote_asset=self.quote_asset,
            risk_day=observation.risk_day, equity_result=equity_result)
        evidence = build_bound_mcp_spot_evidence(account=account,
            open_orders=open_orders, trades=trades, all_orders=all_orders,
            book=book, account_ref=self.account_ref,
            account_binding_verified=True, symbol=self.symbol,
            base_asset=self.base_asset, quote_asset=self.quote_asset,
            risk_day=observation.risk_day, observed_at_ms=now_ms,
            evidence_id=f"api-{now_ms}", risk=risk,
            trade_history_complete=True)
        self._save_balance(quote_total, normalized)
        return SpotApiSnapshot(evidence, rules, commission, book,
            frozenset(row["orderId"] for row in normalized))

    def _balances(self, account):
        if account.get("accountType") != "SPOT" or account.get("canTrade") is not True:
            raise ValueError("Spot account cannot trade")
        rows = account.get("balances")
        if not isinstance(rows, list):
            raise ValueError("Invalid Spot balances")
        by_asset = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("asset") in by_asset:
                raise ValueError("Invalid Spot balance row")
            free, locked = Decimal(str(row["free"])), Decimal(str(row["locked"]))
            if not free.is_finite() or not locked.is_finite() or min(free, locked) < 0:
                raise ValueError("Invalid Spot balance value")
            by_asset[row["asset"]] = free + locked
        if any(asset not in (self.base_asset, self.quote_asset) and amount > 0
               for asset, amount in by_asset.items()):
            raise ValueError("Dedicated Spot account contains another asset")
        return (by_asset.get(self.quote_asset, Decimal("0")),
                by_asset.get(self.base_asset, Decimal("0")))

    def _check_quote_continuity(self, quote_total, fills, *, initial):
        if initial:
            return
        try:
            saved = json.loads(self.balance_path.read_text(encoding="utf-8"))
            if (saved.get("account_ref") != self.account_ref
                    or saved.get("symbol") != self.symbol
                    or not isinstance(saved.get("fill_ids"), list)):
                raise ValueError
            previous_ids = set(saved["fill_ids"])
            if len(previous_ids) != len(saved["fill_ids"]):
                raise ValueError
            current_ids = {row["id"] for row in fills}
            if not previous_ids <= current_ids:
                raise ValueError
            expected_delta = sum((
                (Decimal(row["quoteQty"]) if not row["isBuyer"] else -Decimal(row["quoteQty"]))
                - (Decimal(row["commission"]) if row["commissionAsset"] == self.quote_asset else Decimal("0"))
                for row in fills if row["id"] not in previous_ids), Decimal("0"))
            if quote_total - Decimal(saved["quote_total"]) != expected_delta:
                raise ValueError("Unexplained Spot quote balance movement")
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            raise ValueError("Invalid Spot balance checkpoint") from None

    def _save_balance(self, quote_total, fills):
        payload = {"account_ref": self.account_ref, "symbol": self.symbol,
            "quote_total": str(quote_total),
            "fill_ids": [row["id"] for row in fills]}
        self.balance_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.balance_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.balance_path)
