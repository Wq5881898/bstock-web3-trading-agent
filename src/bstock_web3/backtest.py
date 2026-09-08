from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import timezone
import json
from pathlib import Path

import pandas as pd

from .catalog import BStockAsset
from .market_data import MultiTimeframeSnapshot
from .models import Kline
from .strategy import MtfEmaStrategy, PositionView


@dataclass(frozen=True)
class BacktestResult:
    initial_cash: float
    final_value: float
    net_pnl: float
    return_pct: float
    completed_trades: int
    fees: float
    max_drawdown_pct: float


def run_backtest(path: Path, *, initial_cash: float = 1000.0,
                 order_size: float = 20.0, fee_bps: float = 10.0) -> BacktestResult:
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.sort_values("open_time").drop_duplicates("open_time")
    if "complete" in frame:
        frame = frame[frame["complete"].astype(bool)]
    five = (frame.set_index("open_time").resample("5min", label="left", closed="left")
            .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                 close=("close", "last"), volume=("volume", "sum")).dropna().reset_index())
    asset = BStockAsset("TEST", "TESTB", "0x0", "56", "TESTBUSDT", "1")
    strategy = MtfEmaStrategy()
    cash, quantity, entry, fees, trades = initial_cash, 0.0, 0.0, 0.0, 0
    equity, fee_rate = [], fee_bps / 10000.0
    for index in range(22, len(frame)):
        now = frame.iloc[index]["open_time"]
        one_rows = frame.iloc[max(0, index - 239):index]
        five_rows = five[five["open_time"] + pd.Timedelta(minutes=5) <= now].tail(240)
        snapshot = MultiTimeframeSnapshot(asset, _klines(one_rows), _klines(five_rows),
                                          now.to_pydatetime().astimezone(timezone.utc))
        decision = strategy.evaluate(snapshot, PositionView(quantity, entry))
        price = float(frame.iloc[index]["open"])
        if decision.action == "buy" and quantity == 0 and cash > 0:
            spend = min(order_size, cash)
            fee = spend * fee_rate
            quantity, entry, cash = (spend - fee) / price, price, cash - spend
            fees += fee
        elif decision.action == "sell" and quantity > 0:
            gross, fee = quantity * price, quantity * price * fee_rate
            cash, quantity, entry = cash + gross - fee, 0.0, 0.0
            fees, trades = fees + fee, trades + 1
        equity.append(cash + quantity * price)
    last = float(frame.iloc[-1]["close"])
    final = cash + quantity * last
    if quantity:
        fee = quantity * last * fee_rate
        final -= fee
        fees, trades = fees + fee, trades + 1
    peak, max_dd = equity[0] if equity else initial_cash, 0.0
    for value in equity:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak if peak else 0.0)
    return BacktestResult(initial_cash, final, final - initial_cash,
                          (final / initial_cash - 1) * 100, trades, fees, max_dd * 100)


def _klines(frame: pd.DataFrame) -> tuple[Kline, ...]:
    return tuple(Kline(row.open_time.to_pydatetime(), float(row.open), float(row.high),
                       float(row.low), float(row.close), float(row.volume))
                 for row in frame.itertuples(index=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the standalone MTF EMA strategy")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--order-size", type=float, default=20.0)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    args = parser.parse_args()
    print(json.dumps(asdict(run_backtest(args.data, initial_cash=args.initial_cash,
        order_size=args.order_size, fee_bps=args.fee_bps)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
