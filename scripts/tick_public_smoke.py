"""Bounded public-feed paper observation for Median and fixed Range strategies."""
from argparse import ArgumentParser
from dataclasses import asdict
import json
from pathlib import Path
import time

from bstock_web3.engine import BStockEngineConfig
from bstock_web3.median_monitor import MedianMonitor
from bstock_web3.range_ticks import RangeStrategyConfig
from bstock_web3.range_guard import GuardedRangeMedianConfig
from bstock_web3.range_auto import RangeAutoConfig, RangeMedianAdaptiveConfig


def parse_args():
    parser = ArgumentParser(description="Public aggregate-trade paper smoke; never places real orders")
    parser.add_argument("--strategy", choices=("median", "range-ema", "range-median", "range-median-guarded",
        "range-ema-guarded", "range-auto", "range-guarded-auto", "range-median-adaptive"), default="median")
    parser.add_argument("--symbol", default="NVDAB")
    parser.add_argument("--evaluations", type=int, default=2)
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()
    symbol = args.symbol.strip().upper()
    if not 1 <= args.evaluations <= 20 or not 0 <= args.interval <= 60:
        parser.error("evaluations must be 1–20 and interval must be 0–60 seconds")
    return args, symbol


def main():
    args, symbol = parse_args()
    root = Path("runtime") / "tick-public-smoke" / f"{args.strategy}-{time.time_ns()}"
    family = "median" if args.strategy == "range-median" else "ema"
    config = BStockEngineConfig(symbol=symbol, strategy_kind=args.strategy,
        range_config=RangeStrategyConfig(family=family),
        guarded_range_config=GuardedRangeMedianConfig(), range_auto_config=RangeAutoConfig(),
        range_adaptive_config=RangeMedianAdaptiveConfig(), state_file=root / "paper.sqlite")
    worker = MedianMonitor(config)
    report = {"source": "PUBLIC_MARKET", "account_access": False, "real_orders": False,
        "symbol": symbol, "strategy": args.strategy, "evaluations": []}
    try:
        for index in range(args.evaluations):
            if index:
                time.sleep(args.interval)
            event = worker.evaluate_once()
            checkpoint = worker.session.stream.checkpoint()
            range_state = checkpoint
            while isinstance(range_state, dict) and "base" in range_state:
                range_state = range_state["base"]
            if isinstance(range_state, dict) and "children" in range_state:
                children = list(range_state["children"].values())
                generations = [child.get("sequence", 0) for child in children]
                retained = sum(len(child.get("bars", ())) for child in children)
            else:
                generations = [range_state.get("sequence")] if isinstance(range_state, dict) else [None]
                retained = len(range_state.get("bars", ())) if isinstance(range_state, dict) else 0
            report["evaluations"].append({"reason": event.signal.reason,
                "risk": event.paper_risk_status, "paper_fills": len(event.fills),
                "next_trade_id": worker.session.stream.next_id,
                "range_generation": max((v for v in generations if v is not None), default=None),
                "completed_range_bars_retained": retained,
                "last_trade_ms": (worker.session.stream.latest_tick() or {}).get("time_ms"),
                "chart_bars": len(event.market_snapshot.one_minute) if event.market_snapshot else 0})
        report["ledger"] = asdict(worker.session.ledger)
    finally:
        worker.close()
    root.mkdir(parents=True, exist_ok=True)
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**report, "artifacts": str(root.resolve())}))


if __name__ == "__main__":
    main()
