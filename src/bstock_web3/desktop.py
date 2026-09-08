from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
import sys
from pathlib import Path

from .engine import BStockEngine, BStockEngineConfig


STYLE = """
QWidget { background:#f3f6f5; color:#172321; font-family:'Microsoft YaHei UI'; font-size:13px; }
QFrame#top { background:white; border-left:4px solid #087f6a; }
QLabel#title { color:#0b493f; font-size:19px; font-weight:700; }
QPushButton { background:#e5eeeb; border:1px solid #b7c9c4; padding:7px 14px; }
QPushButton#primary { color:white; background:#087f6a; font-weight:700; }
QLineEdit,QComboBox,QDoubleSpinBox { background:white; border:1px solid #bbc9c5; padding:6px; }
QTableWidget { background:white; gridline-color:#e0e7e5; }
QHeaderView::section { background:#e6efec; padding:7px; font-weight:700; }
"""


def main() -> int:
    try:
        from PyQt5 import QtCore, QtWidgets
    except ImportError:
        print("桌面窗口需要安装: pip install -e .[desktop]", file=sys.stderr)
        return 2

    class Monitor(QtWidgets.QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.engine = None
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.poll)
            self.setWindowTitle("bStock Web3 Engine V1 · 独立监控")
            self.resize(1100, 720)
            root = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(root)
            top = QtWidgets.QFrame(objectName="top")
            top_layout = QtWidgets.QHBoxLayout(top)
            top_layout.addWidget(QtWidgets.QLabel("bStock Web3 模拟盘 / 报价监控", objectName="title"))
            self.symbol = QtWidgets.QLineEdit("NVDAB")
            self.symbol.setMaximumWidth(100)
            self.mode = QtWidgets.QComboBox()
            self.mode.addItems(["paper", "quote"])
            self.amount = QtWidgets.QDoubleSpinBox()
            self.amount.setRange(1, 100000)
            self.amount.setValue(20)
            self.start = QtWidgets.QPushButton("启动监控", objectName="primary")
            self.start.clicked.connect(self.toggle)
            for label, widget in (("标的", self.symbol), ("模式", self.mode),
                                  ("单笔 USDC", self.amount)):
                top_layout.addWidget(QtWidgets.QLabel(label))
                top_layout.addWidget(widget)
            top_layout.addWidget(self.start)
            layout.addWidget(top)
            self.status = QtWidgets.QLabel("安全状态：未运行。GUI V1 不提供实盘提交按钮。")
            layout.addWidget(self.status)
            self.table = QtWidgets.QTableWidget(0, 7)
            self.table.setHorizontalHeaderLabels(
                ["时间", "动作", "原因", "价格", "趋势", "预期边际", "Quote/成交"])
            self.table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.table)
            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            layout.addWidget(self.log, 1)
            self.setCentralWidget(root)
            self.setStyleSheet(STYLE)

        def toggle(self) -> None:
            if self.timer.isActive():
                self.timer.stop()
                self.start.setText("启动监控")
                self.status.setText("安全状态：已停止")
                return
            config = BStockEngineConfig(symbol=self.symbol.text().strip().upper(),
                mode=self.mode.currentText(), order_size_usdc=Decimal(str(self.amount.value())),
                state_file=Path("runtime") / f"{self.symbol.text().strip().lower()}_{self.mode.currentText()}.json")
            self.engine = BStockEngine(config)
            self.timer.start(15000)
            self.start.setText("停止监控")
            self.status.setText(f"运行中：{config.mode}；不会由 GUI 提交真实交易")
            self.poll()

        def poll(self) -> None:
            try:
                event = self.engine.evaluate_once()
                row = self.table.rowCount()
                self.table.insertRow(row)
                quote = event.plan.quote.to_amount if event.plan else (
                    json.dumps(event.paper_fill, ensure_ascii=False) if event.paper_fill else "--")
                values = [event.signal.signal_bar_time or "--", event.signal.action,
                          event.signal.reason, str(event.signal.price or "--"),
                          str(event.signal.trend_spread or "--"),
                          str(event.signal.expected_edge or "--"), quote]
                for column, value in enumerate(values):
                    self.table.setItem(row, column, QtWidgets.QTableWidgetItem(value))
                self.table.scrollToBottom()
                self.log.appendPlainText(json.dumps({"signal": asdict(event.signal),
                    "mode": event.mode}, ensure_ascii=False))
            except Exception as exc:
                self.status.setText(f"运行错误（本轮已跳过）：{exc}")
                self.log.appendPlainText(json.dumps({"error": str(exc)}, ensure_ascii=False))

    app = QtWidgets.QApplication(sys.argv)
    window = Monitor()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
