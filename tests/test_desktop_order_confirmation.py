import os
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

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
