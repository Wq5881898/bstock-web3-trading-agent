from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import time

from .engine import BStockEngine, BStockEngineConfig


def _payload(event) -> dict:
    result = {"symbol": event.asset.symbol, "contractAddress": event.asset.contract_address,
              "mode": event.mode, "signal": event.signal.__dict__}
    if event.paper_fill:
        result["paperFill"] = event.paper_fill
    if event.plan:
        result["quote"] = event.plan.quote.__dict__
        result["roundTripCostBps"] = (None if event.plan.round_trip_cost_bps is None
                                       else str(event.plan.round_trip_cost_bps))
        result["costGatePassed"] = event.plan.cost_gate_passed
        result["confirmationRequired"] = event.mode == "live-confirmed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone bStock Web3 engine")
    parser.add_argument("--symbol", default="NVDAB")
    parser.add_argument("--mode", choices=("paper", "quote", "live-confirmed"), default="paper")
    parser.add_argument("--amount", default="20")
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--eligibility-file", type=Path)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine = BStockEngine(BStockEngineConfig(
        symbol=args.symbol, mode=args.mode, order_size_usdc=Decimal(args.amount),
        eligibility_file=args.eligibility_file, state_file=args.state_file,
    ))
    while True:
        try:
            event = engine.evaluate_once()
            print(json.dumps(_payload(event), ensure_ascii=False, indent=2))
            if event.plan and event.plan.cost_gate_passed and args.mode == "live-confirmed":
                print("真实链上交易待确认；请核对 Quote、合约、数量和风险。")
                print(f"输入逐笔确认码：{event.plan.confirmation}")
                result = engine.execute_confirmed(event.plan, input("> ").strip())
                print(json.dumps(result.detail, ensure_ascii=False, indent=2))
        except KeyboardInterrupt:
            return 130
        except Exception as exc:
            print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
