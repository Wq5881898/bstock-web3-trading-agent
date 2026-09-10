"""Display exactly the closed candles delivered to the strategy; no fetching."""
from datetime import timezone
from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg


class Candles(pg.GraphicsObject):
    def __init__(self, bars, seconds):
        super().__init__()
        self.picture = QtGui.QPicture()
        painter = QtGui.QPainter(self.picture)
        for bar in bars:
            stamp = (bar.time.replace(tzinfo=timezone.utc) if bar.time.tzinfo is None else bar.time).timestamp()
            color = "#087f6a" if bar.close >= bar.open else "#c44343"
            painter.setPen(pg.mkPen(color))
            painter.setBrush(pg.mkBrush(color))
            painter.drawLine(QtCore.QPointF(stamp, bar.low), QtCore.QPointF(stamp, bar.high))
            painter.drawRect(QtCore.QRectF(stamp-seconds*.3, min(bar.open, bar.close), seconds*.6,
                                          max(abs(bar.close-bar.open), .000001)))
        painter.end()

    def paint(self, painter, *args):
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QtCore.QRectF(self.picture.boundingRect())


class CandlePanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.snapshot = None
        self.current = False
        layout = QtWidgets.QVBoxLayout(self)
        self.interval = QtWidgets.QComboBox()
        self.interval.addItems(["1m", "5m"])
        self.interval.currentTextChanged.connect(self.render)
        self.status = QtWidgets.QLabel("等待行情 / Waiting for market data")
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(utcOffset=0)})
        self.plot.setBackground("w")
        self.plot.setLabel("left", "Price", units="USDT")
        layout.addWidget(self.interval)
        layout.addWidget(self.status)
        layout.addWidget(self.plot)
        self.displayed_count = 0

    def update_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.current = True
        self.render()

    def mark_unavailable(self):
        self.current = False
        self.status.setText("无本轮行情；图表保留旧快照 / No current snapshot; chart is historical")

    def render(self):
        self.plot.clear()
        if self.snapshot is None:
            return
        bars = self.snapshot.one_minute if self.interval.currentText() == "1m" else self.snapshot.five_minute
        bars = bars[-240:]
        self.displayed_count = len(bars)
        self.plot.addItem(Candles(bars, 60 if self.interval.currentText() == "1m" else 300))
        observed = self.snapshot.observed_at.astimezone(timezone.utc).isoformat()
        self.status.setText(f"{self.snapshot.asset.spot_symbol} · {len(bars)} 已收盘 / closed · UTC {observed}")
        if not self.current:
            self.status.setText(self.status.text() + " · 旧快照 / historical")
        self.plot.enableAutoRange()
