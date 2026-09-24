"""Operator-approved MCP Spot equity baseline and local risk check."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from .mcp_bridge import load_mcp_account_binding
from .mcp_equity_guard import McpSpotEquityGuard
from .mcp_host_receipt import load_verified_receipt
from .mcp_spot_snapshot import LocalRiskMetrics


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review or confirm the existing Agentic Spot equity baseline")
    parser.add_argument("mode", choices=("preview", "initialize", "check"))
    parser.add_argument("--verified-snapshot", type=Path, required=True)
    parser.add_argument("--binding-file", type=Path,
        default=Path("runtime/desktop/mcp/account-binding.json"))
    parser.add_argument("--ledger-file", type=Path,
        default=Path("runtime/desktop/mcp/live/btcusdt-equity-risk.json"))
    parser.add_argument("--confirm-baseline", default="")
    args = parser.parse_args()
    binding = load_mcp_account_binding(args.binding_file)
    receipt = load_verified_receipt(args.verified_snapshot, binding)
    if receipt.symbol != "BTCUSDT":
        parser.error("Current MCP equity baseline supports BTCUSDT only")
    age = (datetime.now(timezone.utc).timestamp() * 1000
           - receipt.observed_at_ms) / 1000
    if not 0 <= age <= 60:
        parser.error("Verified account snapshot must be no older than 60 seconds")
    risk_day = datetime.fromtimestamp(
        receipt.observed_at_ms / 1000, timezone.utc).date().isoformat()
    evidence = receipt.to_evidence(
        risk_day=risk_day, risk=LocalRiskMetrics(Decimal("0")))
    snapshot = evidence.to_snapshot()
    if not snapshot.reconciled or not snapshot.can_trade \
            or snapshot.pending_order_id:
        parser.error("A settled and reconciled Agentic Spot account is required")
    if args.mode == "preview":
        bid = Decimal(receipt.tool_results["spot.tickerBookTicker"]["bidPrice"])
        quote_rows = [row for row in receipt.tool_results["spot.getAccount"]["balances"]
                      if row["asset"] == receipt.quote_asset]
        quote_total = (Decimal(str(quote_rows[0]["free"]))
                       + Decimal(str(quote_rows[0]["locked"]))
                       if quote_rows else Decimal("0"))
        equity = quote_total + snapshot.position_quantity * bid
        print(json.dumps({"mode": "PREVIEW_ONLY", "symbol": receipt.symbol,
            "accountRef": receipt.account_ref, "equity": format(equity, "f"),
            "observedAt": receipt.observed_at,
            "confirmationRequired": "CONFIRM BTCUSDT EQUITY BASELINE"},
            ensure_ascii=False, indent=2))
        return 0
    if args.mode == "initialize" and args.confirm_baseline != \
            "CONFIRM BTCUSDT EQUITY BASELINE":
        parser.error("Exact --confirm-baseline phrase is required")
    with McpSpotEquityGuard(
            args.ledger_file, account_ref=receipt.account_ref,
            account_fingerprint=receipt.account_fingerprint,
            symbol=receipt.symbol) as guard:
        result = (guard.initialize(receipt, operator_confirmed=True)
                  if args.mode == "initialize" else guard.observe(receipt))
    print(json.dumps({"mode": args.mode.upper(), "symbol": receipt.symbol,
        "accountRef": receipt.account_ref,
        "cumulativeLoss": format(result.cumulative_loss, "f"),
        "equity": format(result.equity, "f"),
        "baselineEquity": format(result.baseline_equity, "f"),
        "observedAt": receipt.observed_at,
        "ledgerFile": str(args.ledger_file.resolve())},
        ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
