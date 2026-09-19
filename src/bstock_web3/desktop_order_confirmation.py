"""Nonmodal, exact-text desktop confirmation for one prepared MCP order."""
from __future__ import annotations

import re
import time

from .mcp_confirmed_host import validate_confirmed_arguments


def validate_confirmation_preview(preview, *, now_ms):
    if (not isinstance(preview, dict) or set(preview) != {
            "account", "arguments", "confirmation", "expiresAtMs"}):
        raise ValueError("Invalid confirmed-order preview")
    account = preview["account"]
    if (not isinstance(account, str) or not account.strip()
            or len(account) > 128 or any(ord(char) < 32 for char in account)):
        raise ValueError("Invalid confirmed account reference")
    validate_confirmed_arguments("spot.newOrder", preview["arguments"])
    confirmation = preview["confirmation"]
    if (not isinstance(confirmation, str)
            or re.fullmatch(r"MCP CONFIRM [A-F0-9]{24}", confirmation) is None):
        raise ValueError("Invalid order confirmation phrase")
    expiry = preview["expiresAtMs"]
    if (type(now_ms) is not int or now_ms < 0 or type(expiry) is not int
            or not now_ms < expiry <= now_ms + 15_000):
        raise ValueError("Invalid or expired order confirmation")
    return dict(preview)


def create_order_confirmation_dialog(preview, *, on_confirmed, on_cancelled,
                                     clock_ms=None, parent=None):
    """Return a nonmodal one-shot dialog; callbacks must only enqueue work."""
    from PyQt5 import QtCore, QtWidgets

    clock = clock_ms or (lambda: time.time_ns() // 1_000_000)
    if not callable(on_confirmed) or not callable(on_cancelled) or not callable(clock):
        raise ValueError("Invalid order confirmation callback")
    validated = validate_confirmation_preview(preview, now_ms=clock())
    args = validated["arguments"]
    amount_key = "quoteOrderQty" if args["side"] == "BUY" else "quantity"

    class OrderConfirmationDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(parent)
            self.consumed = False
            self.setWindowTitle("确认真实Spot订单 / Confirm live Spot order")
            self.setModal(False)
            self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
            layout = QtWidgets.QVBoxLayout(self)
            warning = QtWidgets.QLabel(
                "这是真实订单预览。确认后仅允许提交一次。\n"
                "This is a live-order preview. Confirmation permits one submission only.")
            warning.setTextFormat(QtCore.Qt.PlainText)
            warning.setWordWrap(True)
            layout.addWidget(warning)
            details = QtWidgets.QLabel(
                f'账户 / Account: {validated["account"]}\n'
                f'币对 / Symbol: {args["symbol"]}\n'
                f'方向 / Side: {args["side"]}\n'
                f'类型 / Type: MARKET\n'
                f'金额 / Amount: {args[amount_key]} {amount_key}\n'
                f'客户端订单ID / Client ID: {args["newClientOrderId"]}')
            details.setObjectName("confirmedOrderDetails")
            details.setTextFormat(QtCore.Qt.PlainText)
            details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            layout.addWidget(details)
            layout.addWidget(QtWidgets.QLabel(
                "输入下方一次性短语 / Type the one-time phrase:"))
            phrase = QtWidgets.QLabel(validated["confirmation"])
            phrase.setObjectName("confirmationPhrase")
            phrase.setTextFormat(QtCore.Qt.PlainText)
            phrase.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            layout.addWidget(phrase)
            self.input = QtWidgets.QLineEdit()
            self.input.setObjectName("confirmationInput")
            self.input.setPlaceholderText("MCP CONFIRM …")
            self.input.setMaxLength(len(validated["confirmation"]))
            layout.addWidget(self.input)
            self.countdown = QtWidgets.QLabel()
            self.countdown.setObjectName("confirmationCountdown")
            layout.addWidget(self.countdown)
            buttons = QtWidgets.QHBoxLayout()
            self.cancel_button = QtWidgets.QPushButton("取消 / Cancel")
            self.confirm_button = QtWidgets.QPushButton("确认一次 / Confirm once")
            self.confirm_button.setObjectName("confirmLiveOrder")
            self.confirm_button.setEnabled(False)
            buttons.addWidget(self.cancel_button)
            buttons.addStretch(1)
            buttons.addWidget(self.confirm_button)
            layout.addLayout(buttons)
            self.input.textChanged.connect(self._changed)
            self.cancel_button.clicked.connect(self.reject)
            self.confirm_button.clicked.connect(self._confirm)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self._tick)
            self.timer.start(100)
            self._tick()

        def _changed(self, text):
            self.confirm_button.setEnabled(not self.consumed
                and clock() < validated["expiresAtMs"]
                and text == validated["confirmation"])

        def _tick(self):
            remaining = validated["expiresAtMs"] - clock()
            if remaining <= 0:
                self.countdown.setText("确认已过期 / Confirmation expired")
                self.input.setEnabled(False)
                self.confirm_button.setEnabled(False)
                if not self.consumed:
                    self.reject()
                return
            self.countdown.setText(
                f"剩余 / Remaining: {(remaining + 999) // 1000} s")

        def _confirm(self):
            if (self.consumed or clock() >= validated["expiresAtMs"]
                    or self.input.text() != validated["confirmation"]):
                return
            self.consumed = True
            self.timer.stop()
            self.confirm_button.setEnabled(False)
            on_confirmed(validated["confirmation"])
            self.accept()

        def done(self, result):
            self.timer.stop()
            if not self.consumed:
                self.consumed = True
                on_cancelled()
            super().done(result)

    return OrderConfirmationDialog()
