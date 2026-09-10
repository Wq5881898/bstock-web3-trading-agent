"""Two public-feed evaluations with isolated simulated funds; never real orders."""
from dataclasses import asdict
import json
from pathlib import Path
import time

from bstock_web3.engine import BStockEngineConfig
from bstock_web3.median_monitor import MedianMonitor


def main():
    root = Path("runtime") / "median-public-smoke" / str(time.time_ns())
    worker = MedianMonitor(BStockEngineConfig(symbol="NVDAB", strategy_kind="median",
        state_file=root / "paper.sqlite"))
    report = {"source": "PUBLIC_MARKET", "real_orders": False, "symbol": "NVDAB", "evaluations": []}
    try:
        for i in range(2):
            if i:
                time.sleep(3)
            event = worker.evaluate_once()
            report["evaluations"].append({"reason": event.signal.reason,
                "risk": event.paper_risk_status, "paper_fills": len(event.fills),
                "next_trade_id": worker.session.stream.next_id,
                "chart_bars": len(event.market_snapshot.one_minute) if event.market_snapshot else 0})
        report["ledger"] = asdict(worker.session.ledger)
    finally:
        worker.close()
    root.mkdir(parents=True, exist_ok=True)
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**report, "artifacts": str(root.resolve())}))


if __name__ == "__main__":
    main()
