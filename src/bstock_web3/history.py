from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

import pandas as pd

from .catalog import BStockCatalogClient
from .market_data import instrument_for
from .provider import BinanceSpotKlineProvider


UTC = timezone.utc


@dataclass(frozen=True)
class HistoryReport:
    symbol: str
    spot_symbol: str
    start_utc: str
    end_utc: str
    downloaded_seconds: int
    missing_seconds: int
    one_minute_bars: int
    five_minute_bars: int
    files: dict[str, str]
    sha256: dict[str, str]


def aggregate_seconds(frame: pd.DataFrame, rule: str, *, expected_count: int) -> pd.DataFrame:
    columns = ["open_time", "open_time_ms", "open", "high", "low", "close",
               "volume", "source_count", "complete"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    work = frame.copy()
    work["open_time"] = pd.to_datetime(work["open_time"], utc=True)
    work = work.sort_values("open_time").drop_duplicates("open_time", keep="last")
    grouped = work.set_index("open_time").resample(rule, label="left", closed="left")
    result = grouped.agg(open=("open", "first"), high=("high", "max"),
                         low=("low", "min"), close=("close", "last"),
                         volume=("volume", "sum"), source_count=("open_time_ms", "count"))
    result = result.dropna(subset=["open", "close"]).reset_index()
    result.insert(1, "open_time_ms",
                  (result["open_time"].astype("int64") // 1_000_000).astype("int64"))
    result["complete"] = result["source_count"] == expected_count
    return result[columns]


class BStockHistoryBuilder:
    def __init__(self, provider: BinanceSpotKlineProvider | None = None, *,
                 page_limit: int = 1000, max_retries: int = 4) -> None:
        self.provider = provider or BinanceSpotKlineProvider()
        self.page_limit = page_limit
        self.max_retries = max_retries

    def build(self, symbol: str, *, days: int = 3,
              output_root: Path = Path("kline_history/bstock"),
              end: datetime | None = None, resume: bool = True) -> HistoryReport:
        if days <= 0:
            raise ValueError("days 必须大于 0")
        asset = BStockCatalogClient().resolve(symbol)
        finish = _utc(end or datetime.now(UTC)).replace(microsecond=0) - timedelta(seconds=1)
        start = finish - timedelta(days=days) + timedelta(seconds=1)
        directory = output_root / asset.symbol / f"{start:%Y%m%dT%H%M%SZ}_{finish:%Y%m%dT%H%M%SZ}"
        directory.mkdir(parents=True, exist_ok=True)
        checkpoint = directory / "klines_1s.checkpoint.parquet"
        by_ms: dict[int, dict] = {}
        if resume and checkpoint.exists():
            for row in pd.read_parquet(checkpoint).to_dict("records"):
                by_ms[int(row["open_time_ms"])] = row
        cursor, end_ms = int(start.timestamp() * 1000), int(finish.timestamp() * 1000)
        if by_ms:
            cursor = max(cursor, max(by_ms) + 1000)
        instrument = instrument_for(asset)
        pages = 0
        while cursor <= end_ms:
            page_end = min(end_ms, cursor + (self.page_limit - 1) * 1000)
            rows = self._fetch(instrument, start_time_ms=cursor, end_time_ms=page_end)
            for row in rows:
                opened_ms = int(_utc(row.time).timestamp() * 1000)
                by_ms[opened_ms] = {"open_time": _utc(row.time), "open_time_ms": opened_ms,
                                    "open": row.open, "high": row.high, "low": row.low,
                                    "close": row.close, "volume": row.volume}
            cursor = max((int(_utc(row.time).timestamp() * 1000) for row in rows),
                         default=page_end) + 1000
            pages += 1
            if pages % 25 == 0 or cursor > end_ms:
                pd.DataFrame([by_ms[key] for key in sorted(by_ms)]).to_parquet(checkpoint, index=False)
        raw = pd.DataFrame([by_ms[key] for key in sorted(by_ms)])
        one, five = aggregate_seconds(raw, "1min", expected_count=60), aggregate_seconds(raw, "5min", expected_count=300)
        paths = {"1s": directory / "klines_1s.parquet",
                 "1m": directory / "klines_1m.parquet",
                 "5m": directory / "klines_5m.parquet"}
        for key, frame in (("1s", raw), ("1m", one), ("5m", five)):
            frame.to_parquet(paths[key], index=False)
        checkpoint.unlink(missing_ok=True)
        report = HistoryReport(asset.symbol, asset.spot_symbol, start.isoformat(), finish.isoformat(),
            len(raw), max(int((finish - start).total_seconds()) + 1 - len(raw), 0),
            len(one), len(five), {k: str(v) for k, v in paths.items()},
            {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in paths.items()})
        (directory / "manifest.json").write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    def _fetch(self, instrument, **kwargs):
        for attempt in range(self.max_retries):
            try:
                return self.provider.fetch_klines(instrument, interval="1s",
                                                  limit=self.page_limit, **kwargs)
            except Exception:
                if attempt + 1 == self.max_retries:
                    raise
                time.sleep(min(2 ** attempt, 8))


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download bStock 1s history and aggregate 1m/5m")
    parser.add_argument("--symbol", default="NVDAB")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--output-root", type=Path, default=Path("kline_history/bstock"))
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    report = BStockHistoryBuilder().build(args.symbol, days=args.days,
        output_root=args.output_root, resume=not args.no_resume)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

