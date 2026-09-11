"""Worker-owned public-feed adapter for the transactional Median paper session."""
from dataclasses import dataclass
from datetime import datetime, timezone
import time

from .aggregate_provider import AggregateTradeProvider
from .catalog import BStockCatalogClient
from .market_data import BStockMultiTimeframeFeed
from .median_paper import StrategyPaperSession
from .strategy import SignalDecision
from .range_guard import GuardedRangeMedianConfig, minute_guard_context
from .strategy_registry import strategy_config


@dataclass(frozen=True)
class MedianMonitorEvent:
    signal: SignalDecision
    paper_risk_status: str
    fills: tuple
    market_snapshot: object = None
    mode: str = "paper"
    plan: object = None
    paper_fill: object = None
    account_snapshot: object = None
    recent_fills: tuple = ()


class MedianMonitor:
    def __init__(self, config, *, catalog=None, trades=None, candles=None, clock=time.time):
        if config.mode != "paper" or config.state_file is None:
            raise ValueError("Median monitor requires paper mode and an explicit SQLite path")
        self.config, self.clock = config, clock
        self.catalog = catalog or BStockCatalogClient()
        self.trades = trades or AggregateTradeProvider()
        self.candles = candles or BStockMultiTimeframeFeed()
        self.asset = None
        self.session = None
        self._resume = False
        self._pause = False
        self._last_chart = 0
        self._snapshot = None
        self._recovery_cursor = None

    def close(self):
        try:
            if self.session is not None:
                self.session.close()
        finally:
            self.trades.close()

    def paper_control(self, action):
        if action == "pause":
            self._resume = False
            if self.session is not None:
                self.session.pause_buys()
            else:
                self._pause = True
        elif action == "resume":
            self._resume = True
        else:
            raise ValueError("Unknown paper command")

    def evaluate_once(self):
        if self.asset is None:
            self.asset = self.catalog.resolve(self.config.symbol)
        if self.session is None:
            self.session = StrategyPaperSession(self.config.state_file,
                symbol=self.asset.spot_symbol, strategy=strategy_config(self.config), risk=self.config)
            if self.session.stream.recovery_required:
                self._recovery_cursor = self.session.stream.next_id
            if self.session.stream.next_id is not None or self._pause:
                self.session.pause_buys()  # restart never resumes BUYs implicitly
            self._pause = False
        try:
            status = self.catalog.market_status(self.asset)
        except Exception:
            self._resume = False
            self.session.data_error()
            self._recovery_cursor = self.session.stream.next_id
            raise
        if not status.open_state or status.reason_code != "TRADING":
            self.session.data_error()
            self._recovery_cursor = self.session.stream.next_id
            return self._event(SignalDecision("hold", "market_unavailable", None, None), ())
        fills = []
        caught_up = False
        context = None
        if self.config.strategy_kind in ("range-median-guarded", "range-ema-guarded", "range-guarded-auto"):
            try:
                self._snapshot = self.candles.fetch(self.asset)
                self._last_chart = self.clock()
                context = minute_guard_context(self._snapshot)
                context["_snapshot"] = self._snapshot
            except Exception:
                context = {}
        try:
            # Bound work per cycle; full pages are catch-up/warmup only.
            for _ in range(3):
                cursor = self.session.stream.next_id
                # Median needs only a small rolling window; fixed Range strategies
                # need more trades to reconstruct enough completed price bars.
                limit = 200 if cursor is None and self.config.strategy_kind == "median" else 1000
                rows = self.trades.fetch(self.asset.spot_symbol, from_id=cursor, limit=limit)
                now_ms = int(self.clock() * 1000)
                fills.extend(self.session.accept_page(rows, now_ms=now_ms,
                             warmup=cursor is None or len(rows) == limit, context=context))
                if cursor is None:
                    break
                if len(rows) < limit:
                    caught_up = True
                    break
        except ValueError:
            # Feed/schema errors latch recovery. DB/conflicting-writer failures propagate
            # without a second state write that could mask their original exception.
            self._resume = False
            self.session.data_error()
            self._recovery_cursor = self.session.stream.next_id
            raise
        last = self.session.stream.latest_tick()
        fresh = last is not None and 0 <= int(self.clock()*1000) - last["time_ms"] <= 5000
        if self._resume:
            self._resume = False
            current_cursor = self.session.stream.next_id
            repaired = not self.session.stream.recovery_required or (
                current_cursor is not None and (self._recovery_cursor is None or current_cursor > self._recovery_cursor))
            if caught_up and fresh and repaired:
                self.session.resume_buys(now_ms=int(self.clock()*1000), reconciled=True)
        if self.clock() - self._last_chart >= 15:
            self._last_chart = self.clock()
            try:
                self._snapshot = self.candles.fetch(self.asset)
            except Exception:
                self._snapshot = None  # chart failure does not suppress valid tick exits
        prefix = "median" if self.config.strategy_kind == "median" else self.config.strategy_kind
        reason = prefix + ("_ticks_ready" if caught_up and fresh else "_catching_up_or_stale")
        signal = SignalDecision("hold", reason, last["price"] if last else None,
            datetime.fromtimestamp(last["time_ms"]/1000, timezone.utc).isoformat() if last else None)
        return self._event(signal, tuple(fills))

    def _event(self, signal, fills):
        account = {name: getattr(self.session.ledger, name) for name in (
            "cash", "quantity", "entry_cost", "realized_pnl", "fees", "entries", "losses")}
        return MedianMonitorEvent(signal, self.session.ledger.pause or "ACTIVE", fills,
                                  self._snapshot, account_snapshot=account,
                                  recent_fills=tuple(self.session.fills(limit=100)))
