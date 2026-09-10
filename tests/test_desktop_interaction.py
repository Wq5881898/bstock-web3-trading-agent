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
        assert window.runner is None
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
        assert not window.strategy_choice.model().item(2).isEnabled()
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
        assert window.strategy_inputs["entry_short"].isEnabled()
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
