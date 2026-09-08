from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import subprocess
import time
from typing import Any, Callable


USDC_BSC = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"


@dataclass(frozen=True)
class WalletQuote:
    from_symbol: str
    from_amount: str
    to_symbol: str
    to_amount: str
    slippage: float


@dataclass(frozen=True)
class WalletOrderResult:
    status: str
    order_id: str
    tx_hash: str | None
    from_amount: str
    to_amount: str | None
    detail: dict[str, Any]


class AgenticWalletCli:
    """JSON-only wrapper; secrets remain under the official baw client."""

    def __init__(self, *, executable: str = "baw", timeout_seconds: float = 30.0,
                 poll_seconds: float = 1.0, runner: Any | None = None) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.runner = runner or subprocess.run

    def require_connected(self) -> None:
        payload = self._run("wallet", "status")
        status = str((payload.get("data") or {}).get("status", ""))
        if status != "CONNECTED":
            raise RuntimeError(f"Agentic Wallet 未连接：{status or payload}")

    def token_balance(self, token_address: str, *, chain_id: str = "56") -> Decimal:
        payload = self._run("wallet", "balance", "--binanceChainId", chain_id,
                            "--tokenAddress", token_address)
        for row in payload.get("data") or []:
            if str(row.get("address", "")).lower() == token_address.lower():
                return Decimal(str(row.get("balance") or "0"))
        return Decimal("0")

    def quote(self, *, amount: str, from_token: str, to_token: str,
              chain_id: str = "56", slippage: str = "auto") -> WalletQuote:
        payload = self._run("market-order", "quote", "--fromTokenQty", amount,
                            "--fromToken", from_token, "--toToken", to_token,
                            "--binanceChainId", chain_id, "--slippage", slippage)
        data = payload.get("data") or {}
        return WalletQuote(str(data["fromCoinSymbol"]), str(data["fromCoinAmount"]),
                           str(data["toCoinSymbol"]), str(data["toCoinAmount"]),
                           float(data["slippage"]))

    def swap(self, *, amount: str, from_token: str, to_token: str,
             chain_id: str = "56", slippage: str = "auto", mev: bool = True,
             gas_level: str = "HIGH",
             on_submitted: Callable[[str, datetime], None] | None = None) -> WalletOrderResult:
        self.require_connected()
        submitted_at = datetime.now(timezone.utc)
        payload = self._run("market-order", "swap", "--fromTokenQty", amount,
                            "--fromToken", from_token, "--toToken", to_token,
                            "--binanceChainId", chain_id, "--slippage", slippage,
                            "--mev", str(mev).lower(), "--gasLevel", gas_level)
        order_id = str((payload.get("data") or {})["orderId"])
        if on_submitted is not None:
            on_submitted(order_id, submitted_at)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                order = self._find_order(order_id, from_token, to_token, amount,
                                         submitted_at, chain_id)
            except RuntimeError:
                # The submission is already durable. A transient status-query
                # failure must not erase its identity or trigger another order.
                order = None
            if order is not None and str(order.get("status")) in {"FINISHED", "FAILED"}:
                return self._order_result(order, fallback_id=order_id,
                                          fallback_amount=amount)
            time.sleep(self.poll_seconds)
        return WalletOrderResult("PENDING", order_id, None, amount, None,
                                 {"submittedOrderId": order_id})

    def order_status(self, order_id: str) -> WalletOrderResult | None:
        """Read a submitted order by id without creating a new transaction."""
        payload = self._run("market-order", "list", "--orderId", order_id)
        rows = (payload.get("data") or {}).get("list") or []
        if not rows:
            return None
        row = rows[0]
        return self._order_result(row, fallback_id=order_id, fallback_amount="0")

    @staticmethod
    def _order_result(order: dict[str, Any], *, fallback_id: str,
                      fallback_amount: str) -> WalletOrderResult:
        return WalletOrderResult(
            str(order.get("status") or "PENDING"),
            str(order.get("orderId") or fallback_id),
            order.get("txHash"),
            str(order.get("fromTokenQty") or fallback_amount),
            None if order.get("toTokenActualQty") is None
            else str(order["toTokenActualQty"]),
            order,
        )

    def _find_order(self, order_id: str, from_token: str, to_token: str,
                    amount: str, submitted_at: datetime, chain_id: str) -> dict[str, Any] | None:
        exact = self._run("market-order", "list", "--orderId", order_id)
        rows = (exact.get("data") or {}).get("list") or []
        if rows:
            return rows[0]
        recent = self._run("market-order", "list", "--binanceChainId", chain_id,
                           "--page", "1", "--pageSize", "20")
        for row in (recent.get("data") or {}).get("list") or []:
            if str(row.get("fromToken", "")).lower() != from_token.lower():
                continue
            if str(row.get("toToken", "")).lower() != to_token.lower():
                continue
            try:
                if abs(float(row["fromTokenQty"]) - float(amount)) > 1e-12:
                    continue
                if datetime.fromisoformat(str(row["bookTime"])).astimezone(timezone.utc) < submitted_at.replace(microsecond=0):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            return row
        return None

    def _run(self, *args: str) -> dict[str, Any]:
        completed = self.runner([self.executable, *args, "--json"], capture_output=True,
            text=True, timeout=max(10.0, self.timeout_seconds), check=False)
        raw = (completed.stdout or completed.stderr or "").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"baw 未返回有效 JSON：{raw}") from exc
        if completed.returncode != 0 or not payload.get("success"):
            raise RuntimeError(f"baw command failed: {payload.get('error') or payload}")
        return payload
