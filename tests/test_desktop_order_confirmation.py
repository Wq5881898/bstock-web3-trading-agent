import os
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

from pathlib import Path
from types import SimpleNamespace
import time

import pytest

pytest.importorskip("PyQt5")
from PyQt5 import QtWidgets

from bstock_web3.desktop import create_monitor_class
from bstock_web3.desktop_order_confirmation import (
    create_order_confirmation_dialog, validate_confirmation_preview)

pytestmark = pytest.mark.usefixtures("qt_app")


NOW = 1_000_000


def preview(**changes):
    value = {"account":"agentic-test", "arguments":{
        "symbol":"BTCUSDT", "side":"BUY", "type":"MARKET",
        "newClientOrderId":"bstock-" + "a" * 28,
        "newOrderRespType":"FULL", "quoteOrderQty":"10.00"},
        "confirmation":"MCP CONFIRM " + "A" * 24,
        "expiresAtMs":NOW + 15_000}
    value.update(changes)
    return value


def test_preview_validation_is_exact_and_time_bounded():
    validate_confirmation_preview(preview(), now_ms=NOW)
    for value in (
        {**preview(), "extra":True},
        preview(account=""),
        preview(confirmation="CONFIRM"),
        preview(expiresAtMs=NOW),
        preview(expiresAtMs=NOW + 15_001),
    ):
        with pytest.raises(ValueError):
            validate_confirmation_preview(value, now_ms=NOW)


def test_exact_phrase_confirms_once_and_displays_exact_order():
    app = QtWidgets.QApplication.instance()
    confirmed, cancelled = [], []
    dialog = create_order_confirmation_dialog(preview(),
        on_confirmed=confirmed.append, on_cancelled=lambda:cancelled.append(True),
        clock_ms=lambda:NOW)
    dialog.show(); app.processEvents()
    details = dialog.findChild(QtWidgets.QLabel, "confirmedOrderDetails").text()
    assert "agentic-test" in details and "BTCUSDT" in details
    assert "BUY" in details and "10.00 quoteOrderQty" in details
    dialog.input.setText("MCP CONFIRM " + "B" * 24)
    assert not dialog.confirm_button.isEnabled()
    dialog.input.setText(preview()["confirmation"])
    assert dialog.confirm_button.isEnabled()
    dialog.confirm_button.click(); app.processEvents()
    assert confirmed == [preview()["confirmation"]]
    assert cancelled == []
    dialog.done(QtWidgets.QDialog.Accepted)
    assert len(confirmed) == 1


def test_cancel_and_expiry_never_confirm():
    app = QtWidgets.QApplication.instance()
    confirmed, cancelled = [], []
    dialog = create_order_confirmation_dialog(preview(),
        on_confirmed=confirmed.append, on_cancelled=lambda:cancelled.append(True),
        clock_ms=lambda:NOW)
    dialog.reject(); app.processEvents()
    assert confirmed == [] and cancelled == [True]
    now = [NOW]
    dialog = create_order_confirmation_dialog(preview(),
        on_confirmed=confirmed.append, on_cancelled=lambda:cancelled.append(True),
        clock_ms=lambda:now[0])
    dialog.show(); now[0] += 15_000; dialog._tick(); app.processEvents()
    assert confirmed == [] and cancelled == [True, True]
    assert not dialog.confirm_button.isEnabled()


def test_monitor_owns_and_cancels_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    app = QtWidgets.QApplication.instance()
    calls = []
    window = create_monitor_class(lambda config: None)()
    window.show()
    dialog = window.show_confirmed_order_prompt(preview(), calls.append,
        lambda:calls.append("cancel"), clock_ms=lambda:NOW)
    assert dialog in window.order_prompts
    assert "submission disabled" in window.mcp_live_status.text()
    window.close(); app.processEvents()
    assert calls == ["cancel"]
    assert not window.order_prompts


def test_account_tab_runs_only_injected_non_dispatchable_rehearsal(
        monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    app = QtWidgets.QApplication.instance()
    events = []
    receipt = object()
    summary = {"accountRef":"agentic-primary", "symbol":"BTCUSDT",
        "canTrade":True, "availableQuote":"100", "positionQuantity":"0",
        "positionCost":"0", "pendingOrderId":None,
        "observedAt":"2026-09-21T12:00:10Z"}

    live_preview = preview(expiresAtMs=int(time.time() * 1000) + 15_000)
    class Session:
        preview = live_preview
        def confirm(self, phrase):
            events.append(("confirm", phrase))
            return Path("rehearsal.json"), SimpleNamespace(
                symbol="BTCUSDT", side="BUY")
        def cancel(self):
            events.append(("cancel",))

    def importer(symbol):
        return tmp_path / "verified.json", summary, receipt
    def loader(symbol, verified, loss):
        events.append(("load", symbol, verified, str(loss)))
        return Session()

    window = create_monitor_class(lambda config: None, None, importer, loader)()
    window.show()
    try:
        window.mcp_import.click()
        assert window.mcp_rehearse.isEnabled()
        window.mcp_rehearse.click(); app.processEvents()
        assert events[0] == ("load", "BTCUSDT", receipt, "0.0")
        dialog = window.order_prompts[0]
        dialog.input.setText(Session.preview["confirmation"])
        dialog.confirm_button.click(); app.processEvents()
        assert events[1] == ("confirm", Session.preview["confirmation"])
        assert "dispatch_prohibited=true" in window.mcp_status.text()
        assert "no MCP call occurred" in window.mcp_status.text()
        assert window.mcp_rehearsal_session is None
    finally:
        window.close()


def test_live_mcp_switch_is_off_by_default_and_uses_file_handoff(
        monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))
    app = QtWidgets.QApplication.instance()
    events = []
    receipt = object()
    summary = {"accountRef":"agentic-primary", "symbol":"BTCUSDT",
        "canTrade":True, "availableQuote":"100", "positionQuantity":"0",
        "positionCost":"0", "pendingOrderId":None,
        "observedAt":"2026-09-21T12:00:10Z"}
    live_preview = preview(expiresAtMs=int(time.time() * 1000) + 15_000)

    class LiveSession:
        preview = live_preview
        ticket = None
        def confirm(self, phrase):
            events.append(("confirm-live", phrase))
            self.ticket = SimpleNamespace(symbol="BTCUSDT")
            return (tmp_path / "ticket.json", self.ticket,
                    tmp_path / "result.json")
        def import_result(self):
            events.append(("import-live",))
            return SimpleNamespace(phase=SimpleNamespace(value="FILLED"))
        def cancel(self):
            events.append(("cancel-live",))
        def close(self):
            events.append(("close-live",))

    def importer(symbol):
        return tmp_path / "verified.json", summary, receipt
    def live_loader(symbol, verified, loss):
        events.append(("load-live", symbol, verified, str(loss)))
        return LiveSession()

    window = create_monitor_class(
        lambda config: None, None, importer, None, live_loader)()
    window.show()
    try:
        assert not window.mcp_live_enabled.isChecked()
        assert not window.mcp_live_prepare.isEnabled()
        window.mcp_import.click()
        assert not window.mcp_live_prepare.isEnabled()
        window.mcp_live_enabled.setChecked(True)
        assert window.mcp_live_prepare.isEnabled()
        window.mcp_live_prepare.click(); app.processEvents()
        dialog = window.order_prompts[0]
        dialog.input.setText(LiveSession.preview["confirmation"])
        dialog.confirm_button.click(); app.processEvents()
        assert events[:2] == [
            ("load-live", "BTCUSDT", receipt, "0.0"),
            ("confirm-live", LiveSession.preview["confirmation"])]
        assert window.mcp_live_import.isEnabled()
        window.mcp_live_import.click(); app.processEvents()
        assert events[-1] == ("import-live",)
        assert window.mcp_live_session is None
    finally:
        window.close()
