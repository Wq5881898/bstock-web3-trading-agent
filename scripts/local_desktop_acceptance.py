"""Offline native desktop soak. Synthetic candles only; no wallet/network calls."""
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")
from PyQt5 import QtCore, QtWidgets
from bstock_web3.catalog import BStockAsset
from bstock_web3.desktop import create_monitor_class
from bstock_web3.engine import EngineEvent
from bstock_web3.market_data import MultiTimeframeSnapshot
from bstock_web3.models import Kline
from bstock_web3.strategy import SignalDecision


def main():
    root = Path("runtime") / "desktop-acceptance" / str(time.time_ns())
    root.mkdir(parents=True)
    os.environ["BINANCE_AGENT_RUNTIME_DIR"] = str(root.resolve())
    asset = BStockAsset("NVDA", "NVDAB", "SYNTHETIC", "56", "NVDABUSDT", "1")
    counters = {"attempts": 0, "failures": 0}

    class Engine:
        def __init__(self, config): pass
        def evaluate_once(self):
            counters["attempts"] += 1
            n = counters["attempts"]
            if n % 17 == 0:
                counters["failures"] += 1
                raise ValueError("SYNTHETIC injected feed outage")
            now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc) + timedelta(minutes=n)
            def bars(size, minutes):
                end = now.replace(minute=now.minute // minutes * minutes)
                result = []
                for i in range(size):
                    price = 100 + math.sin((i+n)/12)*2
                    result.append(Kline(end-timedelta(minutes=(size-i)*minutes), price,
                        price+.8, price-.8, price+.2*math.sin(i), 10))
                return tuple(result)
            snapshot = MultiTimeframeSnapshot(asset, bars(240, 1), bars(80, 5), now)
            return EngineEvent(asset, SignalDecision("hold", "SYNTHETIC_UI_FIXTURE", 100,
                snapshot.signal_bar_time.isoformat()), "paper", market_snapshot=snapshot)

    app = QtWidgets.QApplication([])
    window = create_monitor_class(Engine)()
    window.setWindowTitle("SYNTHETIC · Local acceptance · No real orders")
    window.show()
    window.toggle()
    window.timer.setInterval(10)
    window.result_timer.setInterval(10)
    started = time.monotonic()
    result = {"source": "SYNTHETIC", "real_orders": False, "passed": False}
    stopping = False
    timer = QtCore.QTimer()

    def check():
        nonlocal stopping
        try:
            if time.monotonic() - started > 120:
                raise AssertionError("Acceptance timeout")
            if counters["attempts"] >= 650 and not stopping:
                stopping = True
                window.toggle()
            if not stopping or window.runner is not None:
                return
            assert window.state_lock is None
            assert window.start.isEnabled() and window.symbol.isEnabled()
            assert window.table.rowCount() == 500
            assert window.log.document().blockCount() <= 1000
            assert window.candles.displayed_count == 240
            window.tabs.setCurrentIndex(1)
            window.candles.interval.setCurrentText("5m")
            assert window.candles.displayed_count == 80
            app.processEvents()
            assert window.grab().save(str(root / "candles.png"))
            window.tabs.setCurrentIndex(0)
            assert window.grab().save(str(root / "monitor.png"))
            window.tabs.setCurrentIndex(2)
            window.strategy_choice.setCurrentIndex(1)
            app.processEvents()
            assert window.grab().save(str(root / "strategies.png"))
            result.update(passed=True, **counters, rows=window.table.rowCount(),
                          elapsed_seconds=round(time.monotonic()-started, 2), artifacts=str(root.resolve()))
            finish()
        except Exception as exc:
            result.update(error=type(exc).__name__ + ": " + str(exc))
            finish()

    def finish():
        timer.stop()
        (root / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
        window.close()
        if window.runner is None:
            app.quit()

    timer.timeout.connect(check)
    timer.start(20)
    app.exec_()
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
