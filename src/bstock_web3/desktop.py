from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
import os
import re
import sys
from pathlib import Path

from .engine import BStockEngine, BStockEngineConfig
from .poll_runner import PollRunner
from .desktop_preferences import DesktopPreferences, load_preferences, save_preferences
from .strategy import MtfEmaConfig


STYLE = """
QWidget { background:#f3f6f5; color:#172321; font-family:'Microsoft YaHei UI'; font-size:13px; }
QFrame#top { background:white; border-left:4px solid #087f6a; }
QLabel#title { color:#0b493f; font-size:19px; font-weight:700; }
QLabel#subtitle { color:#526963; font-size:12px; }
QPushButton { background:#e5eeeb; border:1px solid #b7c9c4; padding:7px 14px; }
QPushButton#primary { color:white; background:#087f6a; font-weight:700; }
QLineEdit,QComboBox,QDoubleSpinBox { background:white; border:1px solid #bbc9c5; padding:6px; }
QTableWidget { background:white; gridline-color:#e0e7e5; }
QHeaderView::section { background:#e6efec; padding:7px; font-weight:700; }
"""


def desktop_state_file(symbol: str, mode: str) -> Path:
    """Return a writable, launch-directory-independent desktop state path."""
    configured = os.environ.get("BINANCE_AGENT_RUNTIME_DIR")
    if configured:
        runtime_root = Path(configured).expanduser()
    else:
        source_root = Path(__file__).resolve().parents[2]
        if (source_root / "pyproject.toml").is_file():
            runtime_root = source_root / "runtime" / "desktop"
        else:
            app_data = os.environ.get("LOCALAPPDATA")
            runtime_root = Path(app_data) / "BinanceAgentOS" if app_data else Path.home() / ".binance-agent-os"
    safe_symbol = symbol.strip().lower()
    if not re.fullmatch(r"[a-z0-9]{1,32}", safe_symbol) or mode not in ("paper", "quote"):
        raise ValueError("Invalid desktop symbol or mode")
    return runtime_root / f"{safe_symbol}_{mode}.json"


def create_monitor_class(engine_factory=BStockEngine):
    """Keep Qt optional for CLI users and permit deterministic desktop tests."""
    from PyQt5 import QtCore, QtWidgets
    from .candle_widget import CandlePanel

    class Monitor(QtWidgets.QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.engine = None
            self.runner = None
            self.state_lock = None
            self.closing = False
            self._last_risk = ""
            self.alerts = []
            self.result_timer = QtCore.QTimer(self)
            self.result_timer.timeout.connect(self.collect)
            self.result_timer.start(100)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.poll)
            self.setWindowTitle("Binance Agent OS · 多市场量化交易终端")
            self.resize(1100, 720)
            root = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(root)
            top = QtWidgets.QFrame(objectName="top")
            top_layout = QtWidgets.QVBoxLayout(top)
            top_layout.addWidget(QtWidgets.QLabel("Binance Agent OS 多市场量化交易终端", objectName="title"))
            top_layout.addWidget(QtWidgets.QLabel(
                "当前适配器：Binance bStock（BSC）｜执行通道：Agent OS MCP / Agentic Wallet｜现货与合约适配器：规划中",
                objectName="subtitle",
            ))
            controls = QtWidgets.QHBoxLayout()
            self.symbol = QtWidgets.QLineEdit("NVDAB")
            self.symbol.setMaximumWidth(100)
            self.mode = QtWidgets.QComboBox()
            self.mode.addItems(["paper", "quote"])
            self.amount = QtWidgets.QDoubleSpinBox()
            self.amount.setRange(1, 100000)
            self.amount.setValue(100)
            self.loss_limit = QtWidgets.QDoubleSpinBox()
            self.loss_limit.setRange(.01, 100000)
            self.loss_limit.setValue(10)
            self.start = QtWidgets.QPushButton("启动监控", objectName="primary")
            self.start.clicked.connect(self.toggle)
            for label, widget in (("标的", self.symbol), ("模式", self.mode),
                                  ("单笔 USDC", self.amount), ("模拟日亏损上限", self.loss_limit)):
                controls.addWidget(QtWidgets.QLabel(label))
                controls.addWidget(widget)
            controls.addStretch(1)
            controls.addWidget(self.start)
            top_layout.addLayout(controls)
            layout.addWidget(top)
            self.status = QtWidgets.QLabel("安全状态：未运行。GUI V1 不提供实盘提交按钮。")
            layout.addWidget(self.status)
            limits = QtWidgets.QHBoxLayout()
            self.risk_inputs = {}
            for key, label, default in (
                ("paper_position_cap", "模拟持仓成本 / Cost cap", 100),
                ("paper_max_daily_entries", "每日开仓 / Entries", 20),
                ("paper_max_loss_streak", "连亏暂停 / Loss streak", 3),
                ("paper_entry_cooldown", "开仓冷却秒 / Cooldown", 60),
            ):
                edit = QtWidgets.QDoubleSpinBox() if key == "paper_position_cap" else QtWidgets.QSpinBox()
                edit.setRange(0 if key == "paper_entry_cooldown" else 1, 100000)
                edit.setValue(default)
                self.risk_inputs[key] = edit
                limits.addWidget(QtWidgets.QLabel(label))
                limits.addWidget(edit)
            layout.addLayout(limits)
            preferences_row = QtWidgets.QHBoxLayout()
            self.save_settings = QtWidgets.QPushButton("保存参数 / Save settings")
            self.load_settings = QtWidgets.QPushButton("读取已保存参数 / Load settings")
            self.save_settings.clicked.connect(self.save_inputs)
            self.load_settings.clicked.connect(self.load_inputs)
            preferences_row.addWidget(self.save_settings)
            preferences_row.addWidget(self.load_settings)
            preferences_row.addWidget(QtWidgets.QLabel("仅保存输入；不会自动启动 / Inputs only; no auto-start"))
            layout.addLayout(preferences_row)
            risk_controls = QtWidgets.QHBoxLayout()
            self.pause_buys = QtWidgets.QPushButton("暂停模拟买入 / Pause buys")
            self.resume_buys = QtWidgets.QPushButton("手动恢复买入 / Resume buys")
            self.pause_buys.clicked.connect(lambda: self.paper_command("pause"))
            self.resume_buys.clicked.connect(lambda: self.paper_command("resume"))
            for button in (self.pause_buys, self.resume_buys):
                button.setEnabled(False)
                risk_controls.addWidget(button)
            self.risk_label = QtWidgets.QLabel("模拟风控 / Paper risk: —")
            risk_controls.addWidget(self.risk_label)
            layout.addLayout(risk_controls)
            self.table = QtWidgets.QTableWidget(0, 7)
            self.table.setHorizontalHeaderLabels(
                ["时间", "动作", "原因", "价格", "趋势", "预期边际", "Quote/成交"])
            self.table.horizontalHeader().setStretchLastSection(True)
            self.tabs = QtWidgets.QTabWidget()
            self.tabs.addTab(self.table, "监控 / Monitor")
            self.candles = CandlePanel()
            self.tabs.addTab(self.candles, "K线 / Candles")
            strategy_page = QtWidgets.QWidget()
            strategy_layout = QtWidgets.QVBoxLayout(strategy_page)
            self.strategy_choice = QtWidgets.QComboBox()
            self.strategy_choice.addItems(["MTF EMA · 默认 / Default", "MTF EMA · 自定义 / Custom",
                "Median · 待接入逐笔行情 / Pending tick feed",
                "Range / Slope / Median Auto · 待迁移 / Pending migration"])
            for index in (2, 3):
                self.strategy_choice.model().item(index).setEnabled(False)
            strategy_layout.addWidget(self.strategy_choice)
            strategy_layout.addWidget(QtWidgets.QLabel(
                "自定义仅限模拟；持仓期间必须使用原参数。\nCustom settings: paper only; open positions retain original parameters.\n"
                "周期单位为已收盘K线；比例0.004 = 0.4%。\nPeriods use closed candles; fraction 0.004 = 0.4%."))
            self.strategy_inputs = {}
            strategy_grid = QtWidgets.QFormLayout()
            labels = {
                "trend_short": "5m 快 EMA / Fast", "trend_long": "5m 慢 EMA / Slow",
                "entry_short": "1m 快 EMA / Fast", "entry_long": "1m 慢 EMA / Slow",
                "atr_period": "5m ATR 周期 / Period", "min_trend_spread": "最小趋势价差比例 / Trend spread",
                "min_expected_edge": "最小 ATR/价格 / ATR-to-price", "stop_loss": "持仓止损比例 / Stop loss fraction",
            }
            for key, value in asdict(MtfEmaConfig()).items():
                edit = QtWidgets.QSpinBox() if type(value) is int else QtWidgets.QDoubleSpinBox()
                if type(value) is int:
                    edit.setRange(1, 200)
                else:
                    edit.setDecimals(6)
                    edit.setRange(.000001 if key == "stop_loss" else 0, .999999)
                    edit.setSingleStep(.0001)
                edit.setValue(value)
                self.strategy_inputs[key] = edit
                strategy_grid.addRow(labels[key], edit)
            strategy_layout.addLayout(strategy_grid)
            strategy_layout.addStretch(1)
            self.tabs.addTab(strategy_page, "策略 / Strategies")
            self.strategy_choice.currentIndexChanged.connect(self.strategy_selection_changed)
            self.strategy_selection_changed()
            layout.addWidget(self.tabs, 2)
            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumBlockCount(1000)
            layout.addWidget(self.log, 1)
            self.setCentralWidget(root)
            self.setStyleSheet(STYLE)
            self.preferences_path = desktop_state_file("NVDAB", "paper").parent / "preferences.json"
            self.load_inputs(initial=True)

        def strategy_selection_changed(self, index=None):
            custom = self.strategy_choice.currentIndex() == 1
            if not custom:
                for key, value in asdict(MtfEmaConfig()).items():
                    self.strategy_inputs[key].setValue(value)
            for edit in self.strategy_inputs.values():
                edit.setEnabled(custom and self.runner is None)

        def selected_strategy_config(self):
            if self.strategy_choice.currentIndex() not in (0, 1):
                raise ValueError("Strategy is not available")
            return MtfEmaConfig(**{key: edit.value() for key, edit in self.strategy_inputs.items()})

        def save_inputs(self):
            if self.runner is not None:
                return
            try:
                preferences = DesktopPreferences(
                    symbol=self.symbol.text().strip().upper(), mode=self.mode.currentText(),
                    order_size_usdc=str(self.amount.value()),
                    paper_daily_loss_limit=str(self.loss_limit.value()),
                    strategy_config=asdict(self.selected_strategy_config()),
                    **{k: str(e.value()) if k == "paper_position_cap" else e.value()
                       for k, e in self.risk_inputs.items()})
                save_preferences(self.preferences_path, preferences)
            except (ValueError, OSError):
                self.status.setText("保存失败：检查参数和目录权限；旧预设未替换 / Save failed; check inputs and permissions")
                return
            self.status.setText("参数已保存；未启动，未修改账本 / Settings saved; stopped; ledger unchanged")

        def load_inputs(self, checked=False, *, initial=False):
            if self.runner is not None:
                return
            try:
                preferences = load_preferences(self.preferences_path)
            except FileNotFoundError:
                if not initial:
                    self.status.setText("尚无已保存参数 / No saved settings")
                return
            except (ValueError, OSError):
                self.status.setText("预设无法读取：保留当前输入，请检查后手动启动 / Invalid settings; inputs unchanged; review before start")
                return
            self.symbol.setText(preferences.symbol)
            self.mode.setCurrentText(preferences.mode)
            self.amount.setValue(float(preferences.order_size_usdc))
            self.loss_limit.setValue(float(preferences.paper_daily_loss_limit))
            for key, edit in self.risk_inputs.items():
                value = getattr(preferences, key)
                edit.setValue(float(value) if key == "paper_position_cap" else value)
            self.strategy_choice.setCurrentIndex(0 if preferences.strategy_config == asdict(MtfEmaConfig()) else 1)
            for key, value in preferences.strategy_config.items():
                self.strategy_inputs[key].setValue(value)
            self.strategy_selection_changed()
            self.status.setText("已读取参数；未运行，请核对后启动 / Settings loaded; stopped; review before start")

        def toggle(self) -> None:
            if self.timer.isActive():
                self.timer.stop()
                self.start.setEnabled(False)
                self.status.setText("停止中：等待当前评估完成，不再启动新轮次 / Stopping after current evaluation")
                self.finish_stop()
                return
            try:
                config = BStockEngineConfig(symbol=self.symbol.text().strip().upper(),
                    mode=self.mode.currentText(), order_size_usdc=Decimal(str(self.amount.value())),
                    paper_daily_loss_limit=Decimal(str(self.loss_limit.value())),
                    strategy_config=self.selected_strategy_config(),
                    **{k: Decimal(str(e.value())) if k == "paper_position_cap" else e.value() for k, e in self.risk_inputs.items()},
                    state_file=desktop_state_file(self.symbol.text(), self.mode.currentText()))
            except ValueError as exc:
                self.status.setText(f"配置错误 / Invalid configuration: {exc}")
                return
            try:
                config.state_file.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.status.setText("无法创建状态目录 / Cannot create session directory")
                return
            lock = QtCore.QLockFile(str(config.state_file) + ".lock")
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                self.status.setText("该模拟状态已被另一窗口占用 / Session already owned by another window")
                return
            self.state_lock = lock
            self.runner = PollRunner(lambda: engine_factory(config))
            self.strategy_choice.setEnabled(False)
            for edit in self.strategy_inputs.values():
                edit.setEnabled(False)
            for widget in (self.symbol, self.mode, self.amount, self.loss_limit, self.save_settings, self.load_settings, *self.risk_inputs.values()):
                widget.setEnabled(False)
            for button in (self.pause_buys, self.resume_buys):
                button.setEnabled(config.mode == "paper")
            self.timer.start(15000)
            self.start.setText("停止监控")
            self.status.setText(f"运行中：{config.mode}；不会由 GUI 提交真实交易")
            self.poll()

        def poll(self) -> None:
            if self.runner is not None and self.timer.isActive():
                self.runner.submit()

        def paper_command(self, action):
            if self.runner is not None and self.timer.isActive() and self.runner.command(action):
                self.risk_label.setText("指令排队，下一轮评估处理 / Queued for next evaluation")
                self.poll()

        def finish_stop(self):
            if self.runner is not None and self.runner.future is not None:
                return
            if self.runner is not None:
                self.runner.close()
                self.runner = None
            if self.state_lock is not None:
                self.state_lock.unlock()
                self.state_lock = None
            self.start.setText("启动监控")
            self.start.setEnabled(True)
            self.strategy_choice.setEnabled(True)
            self.strategy_selection_changed()
            for widget in (self.symbol, self.mode, self.amount, self.loss_limit, self.save_settings, self.load_settings, *self.risk_inputs.values()):
                widget.setEnabled(True)
            for button in (self.pause_buys, self.resume_buys):
                button.setEnabled(False)
            self.status.setText("安全状态：已停止 / Stopped")
            if self.closing:
                self.close()

        def closeEvent(self, event):
            if self.runner is not None:
                self.closing = True
                self.timer.stop()
                self.start.setEnabled(False)
                self.status.setText("等待当前评估安全结束 / Waiting for evaluation to finish")
                event.ignore()
                self.finish_stop()
                return
            self.result_timer.stop()
            event.accept()

        def collect(self):
            if self.runner is None:
                return
            future = self.runner.take()
            if future is None:
                return
            try:
                event = future.result()
                risk = getattr(event, "paper_risk_status", "")
                self.risk_label.setText("模拟买入锁 / Paper buy latch: " + (risk or "—"))
                if risk and risk != "ACTIVE" and risk != self._last_risk:
                    box = QtWidgets.QMessageBox(self)
                    box.setWindowTitle("模拟风控 / Paper risk")
                    box.setText(f"{risk}\n停止买入；卖出仍按策略。需手动恢复。\nBuys paused; strategy exits remain active. Manual resume required.")
                    box.setModal(False)
                    box.setAttribute(QtCore.Qt.WA_DeleteOnClose)
                    self.alerts.append(box)
                    box.finished.connect(lambda _, item=box: self.alerts.remove(item) if item in self.alerts else None)
                    box.show()
                self._last_risk = risk
                snapshot = getattr(event, "market_snapshot", None)
                if snapshot is not None:
                    self.candles.update_snapshot(snapshot)
                    if event.signal.reason.startswith("stale_"):
                        self.candles.mark_unavailable()
                else:
                    self.candles.mark_unavailable()
                self.status.setText(f"运行中 / Running: {event.mode} · {event.signal.reason}")
                if self.table.rowCount() >= 500:
                    self.table.removeRow(0)
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
                self.candles.mark_unavailable()
                self.status.setText(f"运行错误（本轮已跳过）：{exc}")
                self.log.appendPlainText(json.dumps({"error": str(exc)}, ensure_ascii=False))
            finally:
                if not self.timer.isActive():
                    self.finish_stop()

    return Monitor


def main() -> int:
    try:
        from PyQt5 import QtWidgets
        monitor = create_monitor_class()
    except ImportError:
        print("桌面窗口需要安装: pip install -e .[desktop]", file=sys.stderr)
        return 2
    app = QtWidgets.QApplication(sys.argv)
    window = monitor()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
