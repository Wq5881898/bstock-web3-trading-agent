from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from .catalog import BinanceExchangeSpotCatalogClient
from .market_data import BStockMultiTimeframeFeed
from .mcp_bridge import (build_mcp_spot_plan, load_mcp_account_binding,
    write_mcp_plan)
from .mcp_host_receipt import load_verified_receipt
from .strategy import MtfEmaStrategy, PositionView, SignalDecision


def _verified_position(snapshot_path: Path, binding, *, symbol: str,
                       now: datetime) -> tuple[PositionView, Decimal]:
    receipt = load_verified_receipt(snapshot_path, binding)
    if receipt.symbol != symbol:
        raise ValueError("Verified account snapshot symbol mismatch")
    observed = datetime.fromisoformat(receipt.observed_at.replace("Z", "+00:00"))
    if observed.tzinfo is None or not 0 <= (now - observed).total_seconds() <= 15:
        raise ValueError("Verified account snapshot is not fresh")
    quantity, cost = receipt.tradable_position()
    entry = cost / quantity if quantity > 0 and cost > 0 else Decimal("0")
    return PositionView(float(quantity), float(entry)), quantity


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a credential-free Binance Agent OS MCP Spot order plan"
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--amount", default="100", help="BUY quote amount in USDT")
    parser.add_argument("--verified-snapshot", type=Path, required=True,
        help="Strictly verified receipt for the existing Agentic account")
    parser.add_argument("--max-age-seconds", type=int, default=45)
    parser.add_argument(
        "--binding-file", type=Path,
        default=Path("runtime") / "desktop" / "mcp" / "account-binding.json",
        help="Enrolled Agentic account binding created by bstock-mcp-import",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("runtime") / "mcp" / "latest-order-plan.json",
    )
    args = parser.parse_args()
    if args.symbol.strip().upper() != "BTCUSDT":
        parser.error("The current Agent OS MCP prototype supports BTCUSDT only")
    symbol = "BTCUSDT"
    binding = load_mcp_account_binding(args.binding_file)
    if binding.fingerprint is None:
        parser.error("Agentic account binding is not enrolled")
    try:
        position, position_quantity = _verified_position(
            args.verified_snapshot, binding, symbol=symbol,
            now=datetime.now(timezone.utc))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    catalog = BinanceExchangeSpotCatalogClient()
    asset = catalog.resolve(symbol)
    status = catalog.market_status(asset)
    if not status.open_state or status.reason_code != "TRADING":
        result = {
            "success": True,
            "action": "hold",
            "reason": f"market_unavailable:{status.reason_code or 'UNKNOWN'}",
            "mcpPlanCreated": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    snapshot = BStockMultiTimeframeFeed().fetch(asset)
    signal = MtfEmaStrategy().evaluate(snapshot, position)
    # Public market-data fetches can outlive the short account-evidence window.
    try:
        checked_position, checked_quantity = _verified_position(
            args.verified_snapshot, binding, symbol=symbol,
            now=datetime.now(timezone.utc))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if checked_position != position or checked_quantity != position_quantity:
        parser.error("Verified account position changed during strategy evaluation")
    if not signal.strategy_id:
        signal = replace(signal, strategy_id="mtf")
    if signal.action == "hold":
        print(json.dumps({
            "success": True,
            "asset": asdict(asset),
            "signal": asdict(signal),
            "mcpPlanCreated": False,
            "message": "当前没有可执行信号；未创建订单计划，也未调用 MCP。",
        }, ensure_ascii=False, indent=2))
        return 0

    try:
        plan = build_mcp_spot_plan(
            asset,
            signal,
            amount_usdt=Decimal(args.amount),
            position_quantity=position_quantity,
            max_age_seconds=args.max_age_seconds,
            account_binding=binding,
        )
    except (RuntimeError, ValueError) as exc:
        blocked = SignalDecision(
            "hold", f"mcp_plan_blocked:{exc}", signal.price,
            signal.signal_bar_time, signal.trend_spread, signal.expected_edge,
        )
        print(json.dumps({
            "success": True,
            "asset": asdict(asset),
            "signal": asdict(blocked),
            "mcpPlanCreated": False,
        }, ensure_ascii=False, indent=2))
        return 0

    write_mcp_plan(plan, args.output)
    print(json.dumps({
        "success": True,
        "asset": asdict(asset),
        "signal": asdict(signal),
        "mcpPlanCreated": True,
        "planFile": str(args.output.resolve()),
        "planSummary": {
            "planId": plan.plan_id,
            "accountRef": plan.account_binding["account_ref"],
            "symbol": plan.symbol,
            "side": plan.side,
            "orderArguments": plan.order_arguments,
            "expiresAt": plan.expires_at,
        },
        "message": (
            "计划不会自行下单。请交给当前已授权的Codex Binance Agent OS MCP宿主，"
            "完成账户、规则、手续费和最终订单核验后再逐笔确认。"
        ),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
