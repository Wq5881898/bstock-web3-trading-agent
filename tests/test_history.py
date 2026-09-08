from datetime import datetime, timedelta, timezone

import pandas as pd

from bstock_web3.history import aggregate_seconds


def test_second_bars_aggregate_to_complete_minute():
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    rows = []
    for index in range(60):
        opened = start + timedelta(seconds=index)
        rows.append({"open_time": opened, "open_time_ms": int(opened.timestamp() * 1000),
                     "open": 100 + index, "high": 101 + index, "low": 99 + index,
                     "close": 100.5 + index, "volume": 1})
    result = aggregate_seconds(pd.DataFrame(rows), "1min", expected_count=60)
    assert len(result) == 1
    assert bool(result.iloc[0]["complete"])
    assert result.iloc[0]["source_count"] == 60
    assert result.iloc[0]["high"] == 160

