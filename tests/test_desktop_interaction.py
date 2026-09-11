import os
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
from threading import Event
import time
from types import SimpleNamespace
import pytest

pytest.importorskip("PyQt5")
from PyQt5 import QtWidgets
from bstock_web3.desktop import create_monitor_class
from bstock_web3.strategy import SignalDecision
pytestmark = pytest.mark.usefixtures("qt_app")


def pump(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def test_gui_stop_remains_responsive_and_releases_state_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    entered, release = Event(), Event()
    class Engine:
        def __init__(self, config): pass
        def evaluate_once(self):
            entered.set()
            assert release.wait(3)
            return SimpleNamespace(signal=SignalDecision("hold", "fixture", 100, "fixture"), plan=None, paper_fill=None, mode="paper")
    monitor = create_monitor_class(Engine)
    first, second = monitor(), monitor()
    first.show()
    try:
        first.toggle()
        assert entered.wait(1)
        assert not first.symbol.isEnabled()
        assert not first.save_settings.isEnabled()
        assert not first.load_settings.isEnabled()
        assert not first.strategy_choice.isEnabled()
        assert all(not edit.isEnabled() for edit in first.strategy_inputs.values())
        second.toggle()
        assert second.runner is None
        assert "already owned" in second.status.text()
        first.toggle()
        app.processEvents()
        assert not first.start.isEnabled()
        assert first.isVisible()
        assert first.state_lock is not None
        release.set()
        pump(app, lambda: first.runner is None)
        assert first.table.rowCount() == 1
        assert first.symbol.isEnabled()
        assert first.save_settings.isEnabled()
        assert first.load_settings.isEnabled()
        assert first.strategy_choice.isEnabled()
        assert first.state_lock is None
        second.toggle()
        assert second.runner is not None
        second.close()
        pump(app, lambda: second.runner is None)
    finally:
        release.set()
        first.close()
        second.close()
        pump(app, lambda: first.runner is None and second.runner is None)


def test_gui_worker_error_is_reported_and_can_stop(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class Engine:
        def __init__(self, config): raise ValueError("fixture failure")
    window = create_monitor_class(Engine)()
    try:
        window.toggle()
        pump(app, lambda: "fixture failure" in window.status.text())
        window.toggle()
        pump(app, lambda: window.runner is None)
        assert window.state_lock is None
    finally:
        window.close()


def test_saved_inputs_restore_without_start_or_ledger_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    ledger = tmp_path / "nvdab_paper.json"
    ledger.write_text('{"paper_buy_pause":"MANUAL"}')
    def forbidden(config):
        pytest.fail("Loading preferences must not construct an engine")
    monitor = create_monitor_class(forbidden)
    first = monitor()
    first.amount.setValue(55)
    first.risk_inputs["paper_max_loss_streak"].setValue(4)
    first.strategy_choice.setCurrentIndex(1)
    first.strategy_inputs["entry_short"].setValue(5)
    first.strategy_inputs["stop_loss"].setValue(.006)
    first.save_settings.click()
    first.close()
    second = monitor()
    try:
        assert second.amount.value() == 55
        assert second.risk_inputs["paper_max_loss_streak"].value() == 4
        assert second.strategy_choice.currentIndex() == 1
        assert second.strategy_inputs["entry_short"].value() == 5
        assert second.strategy_inputs["stop_loss"].value() == .006
        assert second.runner is None
        assert not second.timer.isActive()
        assert not second.resume_buys.isEnabled()
        assert ledger.read_text() == '{"paper_buy_pause":"MANUAL"}'
        saved = second.preferences_path.read_bytes()
        second.amount.setValue(101)
        second.save_settings.click()
        assert "Save failed" in second.status.text()
        assert second.preferences_path.read_bytes() == saved
        second.preferences_path.write_text('{"mode":"live-confirmed"}')
        second.load_settings.click()
        assert "Invalid settings" in second.status.text()
        assert second.amount.value() == 101
    finally:
        second.close()


def test_strategy_editor_validates_before_engine_construction(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    calls = []
    class Engine:
        def __init__(self, config): calls.append(config)
        def evaluate_once(self): raise ValueError("fixture complete")
    window = create_monitor_class(Engine)()
    try:
        assert window.strategy_choice.model().item(2).isEnabled()
        assert window.strategy_choice.model().item(3).isEnabled()
        assert window.strategy_choice.model().item(4).isEnabled()
        assert window.strategy_choice.model().item(5).isEnabled()
        for index in range(6, 10):
            assert window.strategy_choice.model().item(index).isEnabled()
        assert all(not edit.isEnabled() for edit in window.strategy_inputs.values())
        window.strategy_choice.setCurrentIndex(1)
        window.strategy_inputs["entry_short"].setValue(30)
        window.toggle()
        assert "Invalid configuration" in window.status.text()
        assert not calls
        assert window.runner is None
        window.strategy_inputs["entry_short"].setValue(5)
        window.mode.setCurrentText("quote")
        window.toggle()
        assert "paper-only" in window.status.text()
        assert not calls
        window.mode.setCurrentText("paper")
        window.toggle()
        pump(QtWidgets.QApplication.instance(), lambda: "fixture complete" in window.status.text())
        assert calls[0].strategy_config.entry_short == 5
        assert not window.strategy_inputs["entry_short"].isEnabled()
        window.toggle()
        pump(QtWidgets.QApplication.instance(), lambda: window.strategy_inputs["entry_short"].isEnabled())
    finally:
        window.close()


def test_median_gui_persists_selection_displays_fill_and_closes_on_worker(monkeypatch, tmp_path):
    from threading import get_ident
    from bstock_web3.median_monitor import MedianMonitor
    from bstock_web3.catalog import BStockAsset
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    ids, configs = [], []
    now = 1788955200
    class Catalog:
        def resolve(self, symbol): return BStockAsset("NVDA", "NVDAB", "fixture", "56", "NVDABUSDT", "1")
        def market_status(self, asset): return SimpleNamespace(open_state=True, reason_code="TRADING")
    class Trades:
        def fetch(self, symbol, *, from_id, limit):
            return [{"a":i, "T":now*1000, "p":"100" if from_id is None else "95", "q":"1"}
                    for i in (range(3) if from_id is None else [from_id])]
        def close(self): ids.append(get_ident())
    class Candles:
        def fetch(self, asset): raise ValueError("no chart fixture")
    def factory(config):
        configs.append(config)
        ids.append(get_ident())
        return MedianMonitor(config, catalog=Catalog(), trades=Trades(), candles=Candles(), clock=lambda:now)
    monitor = create_monitor_class(factory)
    window = monitor()
    app = QtWidgets.QApplication.instance()
    try:
        window.strategy_choice.setCurrentIndex(2)
        window.median_inputs["window"].setValue(3)
        window.save_inputs()
        window.toggle()
        pump(app, lambda: window.table.rowCount() == 1)
        assert configs[0].strategy_kind == "median"
        assert configs[0].state_file.name == "nvdab_paper_median.sqlite"
        assert not window.median_inputs["window"].isEnabled()
        window.poll()
        pump(app, lambda: window.table.rowCount() == 3)
        assert window.table.item(1,1).text() == "buy"
        assert "qty=" in window.account_summary.text()
        assert window.fill_history.rowCount() == 1
        assert window.fill_history.item(0, 2).text() == "buy"
        assert "数量/qty=" in window.account_summary.text()
        window.toggle()
        pump(app, lambda: window.runner is None)
        assert ids[0] == ids[-1] != get_ident()
        assert window.state_lock is None
    finally:
        window.close()
    restored = monitor()
    try:
        assert restored.strategy_choice.currentIndex() == 2
        assert restored.median_inputs["window"].value() == 3
        assert restored.runner is None
    finally:
        restored.close()


def test_range_gui_builds_separate_ema_and_median_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    configs = []
    class Engine:
        def __init__(self, config): configs.append(config)
        def evaluate_once(self): raise ValueError("fixture complete")
    window = create_monitor_class(Engine)()
    app = QtWidgets.QApplication.instance()
    try:
        window.strategy_choice.setCurrentIndex(3)
        window.range_inputs["range_bps"].setCurrentText("50")
        window.range_inputs["short"].setValue(5)
        window.range_inputs["long"].setValue(13)
        window.toggle()
        pump(app, lambda: "fixture complete" in window.status.text())
        assert configs[-1].strategy_kind == "range-ema"
        assert configs[-1].range_config.range_bps == 50
        assert configs[-1].range_config.short == 5
        assert configs[-1].state_file.name == "nvdab_paper_range_ema.sqlite"
        window.toggle()
        pump(app, lambda: window.runner is None)
        window.strategy_choice.setCurrentIndex(4)
        window.range_inputs["window"].setCurrentText("30")
        window.range_inputs["deviation"].setValue(.004)
        window.save_inputs()
        window.toggle()
        pump(app, lambda: "fixture complete" in window.status.text())
        assert configs[-1].strategy_kind == "range-median"
        assert configs[-1].range_config.window == 30
        assert configs[-1].range_config.deviation == .004
        assert configs[-1].state_file.name == "nvdab_paper_range_median.sqlite"
        window.toggle()
        pump(app, lambda: window.runner is None)
    finally:
        window.close()
    restored = create_monitor_class(Engine)()
    try:
        assert restored.strategy_choice.currentIndex() == 4
        assert restored.range_inputs["window"].currentText() == "30"
    finally:
        restored.close()


def test_new_session_clears_prior_account_view(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    class Engine:
        def __init__(self, config): pass
        def evaluate_once(self):
            return SimpleNamespace(signal=SignalDecision("hold", "fixture", 100, "fixture"),
                plan=None, paper_fill=None, mode="quote", account_snapshot=None, recent_fills=())
    window = create_monitor_class(Engine)()
    app = QtWidgets.QApplication.instance()
    try:
        window.account_summary.setText("OLD LEDGER")
        window.fill_history.setRowCount(1)
        window.toggle()
        assert "Waiting" in window.account_summary.text()
        assert window.fill_history.rowCount() == 0
        pump(app, lambda: window.table.rowCount() == 1)
        assert "OLD LEDGER" not in window.account_summary.text()
        window.toggle()
        pump(app, lambda: window.runner is None)
    finally:
        window.close()


def test_risk_alert_is_nonmodal_and_deduplicated(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class Engine:
        def __init__(self, config): pass
        def evaluate_once(self):
            return SimpleNamespace(signal=SignalDecision("hold", "fixture", 100, "fixture"),
                plan=None, paper_fill=None, mode="paper", paper_risk_status="DAILY_LOSS")
    window = create_monitor_class(Engine)()
    try:
        window.toggle()
        pump(app, lambda: len(window.alerts) == 1)
        assert not window.alerts[0].isModal()
        window.alerts[0].accept()
        app.processEvents()
        assert not window.alerts
        window.poll()
        pump(app, lambda: window.table.rowCount() == 2)
        assert not window.alerts
        window.toggle()
    finally:
        window.close()
