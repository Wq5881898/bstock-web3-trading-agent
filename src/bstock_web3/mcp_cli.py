from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

from .catalog import BStockCatalogClient
from .market_data import BStockMultiTimeframeFeed
from .mcp_bridge import build_mcp_spot_plan, write_mcp_plan
from .strategy import MtfEmaStrategy, PositionView, SignalDecision


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a credential-free Binance Agent OS MCP Spot order plan"
    )
    parser.add_argument("--symbol", default="NVDAB")
    parser.add_argument("--amount", default="20", help="BUY quote amount in USDT")
    parser.add_argument("--position-quantity", default="0")
    parser.add_argument("--entry-price", default="0")
    parser.add_argument("--max-age-seconds", type=int, default=45)
    parser.add_argument(
        "--output", type=Path,
        default=Path("runtime") / "mcp" / "latest-order-plan.json",
    )
    args = parser.parse_args()

    catalog = BStockCatalogClient()
    asset = catalog.resolve(args.symbol)
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
    position = PositionView(
        float(Decimal(args.position_quantity)), float(Decimal(args.entry_price))
    )
    signal = MtfEmaStrategy().evaluate(snapshot, position)
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
            position_quantity=Decimal(args.position_quantity),
            max_age_seconds=args.max_age_seconds,
        )
    except RuntimeError as exc:
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
        "plan": plan.to_dict(),
        "message": (
            "计划不会自行下单。请交给已登录 Binance Agent OS MCP 的宿主，"
            "完成账户、规则、手续费和最终订单核验后再逐笔确认。"
        ),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

