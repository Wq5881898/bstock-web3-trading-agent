import os
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
from datetime import datetime, timedelta, timezone
import pytest
pytest.importorskip("PyQt5")
pytest.importorskip("pyqtgraph")
from PyQt5.QtWidgets import QApplication
from bstock_web3.candle_widget import CandlePanel
from bstock_web3.catalog import BStockAsset
from bstock_web3.market_data import MultiTimeframeSnapshot
from bstock_web3.models import Kline
pytestmark = pytest.mark.usefixtures("qt_app")


def sample():
    end = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    def bars(n, minutes):
        return tuple(Kline(end-timedelta(minutes=(n-i)*minutes), 100+i*.2,
            101+i*.2, 99+i*.2, 100.5+i*.2, 10) for i in range(n))
    return MultiTimeframeSnapshot(BStockAsset("NVDA", "NVDAB", "fixture", "56", "NVDABUSDT", "1"),
                                  bars(250, 1), bars(80, 5), end)


def test_switch_closed_snapshots_and_stale_label():
    app = QApplication.instance() or QApplication([])
    panel = CandlePanel()
    snapshot = sample()
    panel.update_snapshot(snapshot)
    assert panel.displayed_count == 240
    assert "closed" in panel.status.text()
    panel.interval.setCurrentText("5m")
    assert panel.displayed_count == 80
    panel.mark_unavailable()
    assert "historical" in panel.status.text()
    panel.interval.setCurrentText("1m")
    assert "historical" in panel.status.text()
    assert panel.snapshot is snapshot
    panel.close()
