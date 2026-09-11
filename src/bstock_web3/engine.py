from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import secrets
from typing import Literal

from .catalog import BStockAsset, BStockCatalogClient
from .eligibility import EligibilitySnapshot
from .market_data import BStockMultiTimeframeFeed, MultiTimeframeSnapshot
from .strategy import MtfEmaConfig, MtfEmaStrategy, PositionView, SignalDecision
from .median_ticks import TickMedianConfig
from .range_ticks import RangeStrategyConfig
from .range_guard import GuardedRangeMedianConfig
from .range_auto import RangeAutoConfig, RangeMedianAdaptiveConfig
from .strategy_contract import CandleMarketInput, CandleStrategyRuntime
from .strategy_registry import strategy_ids, strategy_spec
from .wallet import AgenticWalletCli, USDC_BSC, WalletOrderResult, WalletQuote


EngineMode = Literal["paper", "quote", "live-confirmed"]


@dataclass
class EngineState:
    state_symbol: str | None = None
    state_mode: str | None = None
    cash_usdc: str = "1000"
    position_quantity: str = "0"
    entry_price: str = "0"
    realized_pnl: str = "0"
    fees_usdc: str = "0"
    paper_entry_cost: str | None = None
    paper_risk_day: str = ""
    paper_risk_baseline: str | None = None
    paper_last_equity: str | None = None
    paper_buy_pause: str = ""
    paper_daily_entries: int = 0
    paper_loss_streak: int = 0
    paper_last_entry_at: str | None = None
    paper_strategy_config: dict | None = None
    last_signal_bar: str | None = None
    pending_order_id: str | None = None
    pending_action: str | None = None
    pending_from_amount: str | None = None
    pending_submitted_at: str | None = None
    last_submitted_confirmation: str | None = None

    @property
    def position(self) -> PositionView:
        return PositionView(float(self.position_quantity), float(self.entry_price))


@dataclass(frozen=True)
class BStockEngineConfig:
    symbol: str = "NVDAB"
    mode: EngineMode = "paper"
    order_size_usdc: Decimal = Decimal("20")
    paper_fee_rate: Decimal = Decimal("0.001")
    slippage: str = "auto"
    min_net_edge_bps: Decimal = Decimal("10")
    max_quote_age_seconds: float = 45.0
    eligibility_file: Path | None = None
    state_file: Path | None = None
    paper_daily_loss_limit: Decimal = Decimal("10")
    paper_position_cap: Decimal = Decimal("100")
    paper_max_daily_entries: int = 20
    paper_max_loss_streak: int = 3
    paper_entry_cooldown: int = 60
    strategy_config: MtfEmaConfig = field(default_factory=MtfEmaConfig)
    strategy_kind: str = "mtf"
    median_config: TickMedianConfig = field(default_factory=TickMedianConfig)
    range_config: RangeStrategyConfig = field(default_factory=RangeStrategyConfig)
    guarded_range_config: GuardedRangeMedianConfig = field(default_factory=GuardedRangeMedianConfig)
    range_auto_config: RangeAutoConfig = field(default_factory=RangeAutoConfig)
    range_adaptive_config: RangeMedianAdaptiveConfig = field(default_factory=RangeMedianAdaptiveConfig)

    def __post_init__(self) -> None:
        if self.strategy_kind not in strategy_ids() or not isinstance(self.median_config, TickMedianConfig) or not isinstance(self.range_config, RangeStrategyConfig) or not isinstance(self.guarded_range_config, GuardedRangeMedianConfig) or not isinstance(self.range_auto_config, RangeAutoConfig) or not isinstance(self.range_adaptive_config, RangeMedianAdaptiveConfig):
            raise ValueError("Invalid strategy selection")
        if strategy_spec(self.strategy_kind).input_kind != "candles" and self.mode != "paper":
            raise ValueError("Tick/Range strategies are paper-only")
        if ((self.strategy_kind in ("range-ema", "range-ema-guarded") and self.range_config.family != "ema") or
                (self.strategy_kind == "range-median" and self.range_config.family != "median")):
            raise ValueError("Range selection/configuration mismatch")
        if not isinstance(self.strategy_config, MtfEmaConfig):
            raise ValueError("Expected MTF EMA configuration")
        if self.mode != "paper" and self.strategy_config != MtfEmaConfig():
            raise ValueError("Custom strategy settings are paper-only")
        if self.mode not in ("paper", "quote", "live-confirmed"):
            raise ValueError("Unknown engine mode")
        for name in ("order_size_usdc", "paper_fee_rate", "min_net_edge_bps", "paper_daily_loss_limit", "paper_position_cap"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be a finite Decimal")
        if isinstance(self.max_quote_age_seconds, bool) or not math.isfinite(self.max_quote_age_seconds):
            raise ValueError("Quote age must be finite")
        if self.order_size_usdc <= 0:
            raise ValueError("order_size_usdc 必须大于 0")
        if self.paper_daily_loss_limit <= 0:
            raise ValueError("Paper daily loss limit must be positive")
        if self.paper_position_cap <= 0 or (self.mode == "paper" and self.order_size_usdc > self.paper_position_cap):
            raise ValueError("Paper order budget exceeds position cost cap")
        for name in ("paper_max_daily_entries", "paper_max_loss_streak", "paper_entry_cooldown"):
            if type(getattr(self, name)) is not int or getattr(self, name) < (0 if name == "paper_entry_cooldown" else 1):
                raise ValueError("Invalid paper risk integer")
        if not Decimal("0") <= self.paper_fee_rate < Decimal("1"):
            raise ValueError("paper_fee_rate 必须在 [0, 1) 范围内")
        if self.min_net_edge_bps < 0:
            raise ValueError("min_net_edge_bps 不能为负数")
        if self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds 必须大于 0")


@dataclass(frozen=True)
class TradePlan:
    action: Literal["buy", "sell"]
    asset: BStockAsset
    amount: str
    from_token: str
    to_token: str
    quote: WalletQuote
    round_trip_quote: WalletQuote | None
    round_trip_cost_bps: Decimal | None
    cost_gate_passed: bool
    confirmation: str
    signal: SignalDecision
    created_at: datetime


@dataclass(frozen=True)
class EngineEvent:
    asset: BStockAsset
    signal: SignalDecision
    mode: EngineMode
    plan: TradePlan | None = None
    paper_fill: dict[str, str] | None = None
    market_snapshot: MultiTimeframeSnapshot | None = None
    paper_risk_status: str = ""
    account_snapshot: dict[str, str | int] | None = None
    recent_fills: tuple[dict, ...] = ()


class BStockEngine:
    def __init__(self, config: BStockEngineConfig, *,
                 catalog: BStockCatalogClient | None = None,
                 feed: BStockMultiTimeframeFeed | None = None,
                 strategy: MtfEmaStrategy | None = None,
                 wallet: AgenticWalletCli | None = None) -> None:
        if config.strategy_kind != "mtf":
            raise ValueError("Use MedianMonitor for the tick-based paper strategy")
        self.config = config
        self.catalog = catalog or BStockCatalogClient()
        self.feed = feed or BStockMultiTimeframeFeed()
        self.strategy = strategy or MtfEmaStrategy(config.strategy_config)
        self.strategy_runtime = CandleStrategyRuntime("mtf", self.strategy)
        self.wallet = wallet or AgenticWalletCli()
        self.asset: BStockAsset | None = None
        self.state = self._load_state()
        if self.config.mode == "paper" and isinstance(self.strategy, MtfEmaStrategy) and Decimal(self.state.position_quantity) > 0:
            previous_config = self.state.paper_strategy_config or asdict(MtfEmaConfig())
            if previous_config != asdict(self.strategy.config):
                raise RuntimeError("持仓策略参数不匹配，请恢复原参数 / Open position requires its original strategy settings")
        self._resume_requested = False

    def paper_control(self, action):
        if self.config.mode != "paper" or action not in ("pause", "resume"):
            raise ValueError("Paper control only")
        if action == "pause":
            self._resume_requested = False
            self.state.paper_buy_pause = self.state.paper_buy_pause or "MANUAL"
            self._save_state()
        else:
            self._resume_requested = True  # evaluated only after fresh valuation

    def _paper_risk(self, price, observed):
        equity = Decimal(self.state.cash_usdc) + Decimal(self.state.position_quantity) * price
        day = observed.astimezone(timezone.utc).date().isoformat()
        if self.state.paper_risk_day and day < self.state.paper_risk_day:
            self.state.paper_buy_pause = self.state.paper_buy_pause or "CLOCK_REWIND"
            self._save_state()
            return
        if self.state.paper_risk_day != day:
            self.state.paper_risk_day = day
            self.state.paper_risk_baseline = self.state.paper_last_equity or str(equity)
            self.state.paper_daily_entries = 0
        loss = Decimal(self.state.paper_risk_baseline) - equity
        if loss >= self.config.paper_daily_loss_limit:
            self.state.paper_buy_pause = self.state.paper_buy_pause or "DAILY_LOSS"
        elif self.state.paper_daily_entries >= self.config.paper_max_daily_entries:
            self.state.paper_buy_pause = self.state.paper_buy_pause or "DAILY_ENTRY_LIMIT"
        elif self.state.paper_loss_streak >= self.config.paper_max_loss_streak:
            self.state.paper_buy_pause = self.state.paper_buy_pause or "CONSECUTIVE_LOSSES"
        if self._resume_requested:
            self._resume_requested = False
            if loss < self.config.paper_daily_loss_limit and self.state.paper_daily_entries < self.config.paper_max_daily_entries:
                self.state.paper_buy_pause = ""
                self.state.paper_loss_streak = 0
        self.state.paper_last_equity = str(equity)
        self._save_state()

    def adopt_position(self, *, quantity: Decimal, entry_price: Decimal) -> None:
        if quantity <= 0 or entry_price <= 0:
            raise ValueError("接管仓位时 quantity 和 entry_price 必须大于 0")
        current = Decimal(self.state.position_quantity)
        if current > 0 and (current != quantity or Decimal(self.state.entry_price) != entry_price):
            raise RuntimeError("引擎已有不同仓位；拒绝覆盖，请先人工核对状态文件")
        self.state.position_quantity, self.state.entry_price = str(quantity), str(entry_price)
        self._save_state()

    def evaluate_once(self, *, now: datetime | None = None) -> EngineEvent:
        event = self._evaluate_once(now=now)
        if self.config.mode == "paper":
            account = {name: getattr(self.state, name) for name in ("cash_usdc", "position_quantity",
                "entry_price", "realized_pnl", "fees_usdc", "paper_daily_entries", "paper_loss_streak")}
            return replace(event, paper_risk_status=self.state.paper_buy_pause or "ACTIVE",
                           account_snapshot=account)
        return event

    def _evaluate_once(self, *, now: datetime | None = None) -> EngineEvent:
        asset = self.asset or self.catalog.resolve(self.config.symbol)
        self.asset = asset
        if self.config.mode == "live-confirmed" and self.state.pending_order_id:
            pending = self._reconcile_pending()
            if pending is not None:
                return EngineEvent(asset, pending, self.config.mode)
        status = self.catalog.market_status(asset)
        if not status.open_state or status.reason_code != "TRADING":
            return EngineEvent(asset, SignalDecision(
                "hold", f"market_unavailable:{status.reason_code or 'UNKNOWN'}", None, None
            ), self.config.mode)
        snapshot = self.feed.fetch(asset, now=now)
        if snapshot.signal_bar_time is None or not 60 <= (snapshot.observed_at - snapshot.signal_bar_time).total_seconds() < 120:
            return EngineEvent(asset, SignalDecision("hold", "stale_or_missing_candles", None, None),
                               self.config.mode, market_snapshot=snapshot)
        signal_bar = snapshot.signal_bar_time.isoformat() if snapshot.signal_bar_time else None
        if self.config.mode == "paper":
            self._paper_risk(Decimal(str(snapshot.one_minute[-1].close)), snapshot.observed_at)
        if signal_bar is not None and self.state.last_signal_bar is not None and datetime.fromisoformat(signal_bar) <= datetime.fromisoformat(self.state.last_signal_bar):
            return EngineEvent(asset, SignalDecision(
                "hold", "signal_bar_already_processed", None, signal_bar
            ), self.config.mode, market_snapshot=snapshot)
        decision = self.strategy_runtime.evaluate(CandleMarketInput(snapshot), self.state.position)[0].decision(self.state.position)
        if self.config.mode == "paper" and decision.action == "buy" and self.state.paper_buy_pause:
            decision = replace(decision, action="hold", reason="paper_buys_paused:" + self.state.paper_buy_pause)
        if self.config.mode == "paper" and decision.action == "buy" and self.state.paper_last_entry_at:
            age = (snapshot.observed_at - datetime.fromisoformat(self.state.paper_last_entry_at)).total_seconds()
            if age < self.config.paper_entry_cooldown:
                decision = replace(decision, action="hold", reason="paper_entry_cooldown")
        if decision.action == "hold":
            self.state.last_signal_bar = signal_bar
            self._save_state()
            return EngineEvent(asset, decision, self.config.mode, market_snapshot=snapshot)
        if self.config.mode == "paper":
            previous_bar = self.state.last_signal_bar
            self.state.last_signal_bar = signal_bar
            try:
                fill = self._paper_fill(decision, observed=snapshot.observed_at)
            except Exception:
                self.state.last_signal_bar = previous_bar
                raise
            self._paper_risk(Decimal(str(decision.price)), snapshot.observed_at)
            return EngineEvent(asset, decision, self.config.mode, paper_fill=fill, market_snapshot=snapshot)
        self.wallet.require_connected()
        plan = self._build_plan(asset, decision)
        self.state.last_signal_bar = signal_bar
        self._save_state()
        return EngineEvent(asset, decision, self.config.mode, plan=plan, market_snapshot=snapshot)

    def execute_confirmed(self, plan: TradePlan, confirmation: str) -> WalletOrderResult:
        if self.config.mode != "live-confirmed":
            raise RuntimeError("只有 live-confirmed 模式允许提交真实交易")
        if self.state.pending_order_id:
            raise RuntimeError(
                f"已有未决订单 {self.state.pending_order_id}，拒绝重复提交"
            )
        if confirmation.strip() != plan.confirmation:
            raise RuntimeError("逐笔确认码不匹配，拒绝提交")
        if self.state.last_submitted_confirmation == plan.confirmation:
            raise RuntimeError("该逐笔确认码已经提交过，拒绝重复使用")
        if (datetime.now(timezone.utc) - plan.created_at).total_seconds() > self.config.max_quote_age_seconds:
            raise RuntimeError("Quote 已过期，拒绝提交；请重新生成信号和报价")
        if not plan.cost_gate_passed:
            raise RuntimeError("预计波动空间不足以覆盖往返成本和安全余量")
        if self.config.eligibility_file is None:
            raise RuntimeError("实盘模式必须提供当前周 eligibility 文件")
        EligibilitySnapshot.load(self.config.eligibility_file).require_current(plan.asset)
        status = self.catalog.market_status(plan.asset)
        if not status.open_state or status.reason_code != "TRADING":
            raise RuntimeError(f"标的当前不可交易：{status.reason_code}")
        available = self.wallet.token_balance(plan.from_token, chain_id=plan.asset.chain_id)
        if available < Decimal(plan.amount):
            raise RuntimeError(f"钱包余额与交易计划不符：可用 {available}，需要 {plan.amount}")
        result = self.wallet.swap(
            amount=plan.amount, from_token=plan.from_token,
            to_token=plan.to_token, chain_id=plan.asset.chain_id,
            slippage=self.config.slippage,
            on_submitted=lambda order_id, submitted_at: self._record_pending(
                plan, order_id, submitted_at
            ),
        )
        if result.status == "FINISHED":
            self._apply_live_fill(plan, result)
            self._clear_pending()
        elif result.status == "FAILED":
            self._clear_pending()
        return result

    def _record_pending(self, plan: TradePlan, order_id: str,
                        submitted_at: datetime) -> None:
        if self.state.pending_order_id and self.state.pending_order_id != order_id:
            raise RuntimeError(
                f"已有未决订单 {self.state.pending_order_id}，拒绝记录新订单 {order_id}"
            )
        self.state.pending_order_id = order_id
        self.state.pending_action = plan.action
        self.state.pending_from_amount = plan.amount
        self.state.pending_submitted_at = submitted_at.astimezone(timezone.utc).isoformat()
        self.state.last_submitted_confirmation = plan.confirmation
        self._save_state()

    def _clear_pending(self) -> None:
        self.state.pending_order_id = None
        self.state.pending_action = None
        self.state.pending_from_amount = None
        self.state.pending_submitted_at = None
        self._save_state()

    def _reconcile_pending(self) -> SignalDecision | None:
        order_id = self.state.pending_order_id
        if order_id is None:
            return None
        result = self.wallet.order_status(order_id)
        if result is None or result.status not in {"FINISHED", "FAILED"}:
            return SignalDecision("hold", f"pending_order:{order_id}", None, None)
        if result.status == "FAILED":
            self._clear_pending()
            return SignalDecision("hold", f"pending_order_failed:{order_id}", None, None)
        action = self.state.pending_action
        if action not in {"buy", "sell"}:
            raise RuntimeError(f"未决订单 {order_id} 缺少有效 action，拒绝自动恢复")
        self._apply_order_fill(action, result)
        self._clear_pending()
        return SignalDecision("hold", f"pending_order_reconciled:{order_id}", None, None)

    def _build_plan(self, asset: BStockAsset, decision: SignalDecision) -> TradePlan:
        if decision.action == "buy":
            amount, from_token, to_token = str(self.config.order_size_usdc), USDC_BSC, asset.contract_address
        else:
            amount, from_token, to_token = self.state.position_quantity, asset.contract_address, USDC_BSC
        quote = self.wallet.quote(amount=amount, from_token=from_token, to_token=to_token,
                                  chain_id=asset.chain_id, slippage=self.config.slippage)
        round_trip = None
        cost_bps = None
        passed = True
        if decision.action == "buy":
            round_trip = self.wallet.quote(amount=quote.to_amount, from_token=to_token,
                                           to_token=from_token, chain_id=asset.chain_id,
                                           slippage=self.config.slippage)
            initial, returned = Decimal(quote.from_amount), Decimal(round_trip.to_amount)
            cost_bps = ((initial - returned) / initial * Decimal("10000")
                        if initial > 0 else Decimal("Infinity"))
            edge_bps = Decimal(str(decision.expected_edge or 0)) * Decimal("10000")
            passed = edge_bps >= cost_bps + self.config.min_net_edge_bps
        return TradePlan(decision.action, asset, amount, from_token, to_token, quote,
                         round_trip, cost_bps, passed,
                         f"CONFIRM {secrets.token_hex(4).upper()}", decision,
                         datetime.now(timezone.utc))

    def _paper_fill(self, decision: SignalDecision, *, observed=None) -> dict[str, str]:
        previous = EngineState(**asdict(self.state))
        try:
            return self._commit_paper_fill(decision, observed=observed)
        except Exception:
            self.state = previous
            raise

    def _commit_paper_fill(self, decision: SignalDecision, *, observed=None) -> dict[str, str]:
        price, fee_rate = Decimal(str(decision.price)), self.config.paper_fee_rate
        if not price.is_finite() or price <= 0 or decision.action not in ("buy", "sell"):
            raise ValueError("Invalid paper fill signal")
        held = Decimal(self.state.position_quantity)
        if decision.action == "buy" and held > 0:
            raise ValueError("Paper BUY cannot overwrite an existing position")
        if decision.action == "sell" and held <= 0:
            raise ValueError("Paper SELL requires an existing position")
        if decision.action == "buy":
            spend = min(self.config.order_size_usdc, Decimal(self.state.cash_usdc))
            if spend <= 0:
                raise ValueError("Insufficient paper cash")
            if spend > self.config.paper_position_cap:
                raise ValueError("Paper position cost cap exceeded")
            fee, quantity = spend * fee_rate, (spend * (1 - fee_rate)) / price
            self.state.cash_usdc = str(Decimal(self.state.cash_usdc) - spend)
            self.state.position_quantity, self.state.entry_price = str(quantity), str(price)
            self.state.paper_entry_cost = str(spend)
            self.state.paper_daily_entries += 1
            self.state.paper_last_entry_at = (observed or datetime.now(timezone.utc)).isoformat()
            fill = {"side": "buy", "price": str(price), "quantity": str(quantity), "fee": str(fee)}
        else:
            quantity = Decimal(self.state.position_quantity)
            gross = quantity * price
            if self.state.paper_entry_cost is None:
                raise ValueError("Legacy paper position has no verified entry cost; review required")
            cost = Decimal(self.state.paper_entry_cost)
            fee = gross * fee_rate
            self.state.cash_usdc = str(Decimal(self.state.cash_usdc) + gross - fee)
            self.state.realized_pnl = str(Decimal(self.state.realized_pnl) + gross - fee - cost)
            self.state.paper_loss_streak = self.state.paper_loss_streak + 1 if gross - fee - cost < 0 else 0
            self.state.position_quantity, self.state.entry_price = "0", "0"
            self.state.paper_entry_cost = None
            fill = {"side": "sell", "price": str(price), "quantity": str(quantity), "fee": str(fee)}
        self.state.fees_usdc = str(Decimal(self.state.fees_usdc) + fee)
        self._save_state()
        return fill

    def _apply_live_fill(self, plan: TradePlan, result: WalletOrderResult) -> None:
        self._apply_order_fill(plan.action, result)

    def _apply_order_fill(self, action: str, result: WalletOrderResult) -> None:
        if result.to_amount is None:
            raise RuntimeError(
                f"订单 {result.order_id} 已完成但缺少实际到账数量，保留未决状态等待人工核验"
            )
        if Decimal(result.from_amount) <= 0 or Decimal(result.to_amount) <= 0:
            raise RuntimeError(
                f"订单 {result.order_id} 返回非法成交数量，保留未决状态等待人工核验"
            )
        if action == "buy":
            old_qty = Decimal(self.state.position_quantity)
            received, spent = Decimal(result.to_amount), Decimal(result.from_amount)
            new_qty = old_qty + received
            self.state.entry_price = str((old_qty * Decimal(self.state.entry_price) + spent) / new_qty)
            self.state.position_quantity = str(new_qty)
        elif action == "sell":
            received, sold = Decimal(result.to_amount), Decimal(result.from_amount)
            self.state.realized_pnl = str(Decimal(self.state.realized_pnl) + received - sold * Decimal(self.state.entry_price))
            self.state.position_quantity, self.state.entry_price = "0", "0"
        else:
            raise RuntimeError(f"未知订单动作：{action}")

    def _state_path(self) -> Path:
        return self.config.state_file or Path("runtime") / f"{self.config.symbol.lower()}_state.json"

    def _load_state(self) -> EngineState:
        try:
            payload = json.loads(self._state_path().read_text(encoding="utf-8"))
            state = EngineState(**payload)
            if not isinstance(state.paper_buy_pause, str) or state.paper_buy_pause not in ("", "MANUAL", "DAILY_LOSS", "CLOCK_REWIND", "DAILY_ENTRY_LIMIT", "CONSECUTIVE_LOSSES"):
                raise ValueError("Invalid paper pause state")
            for value in (state.paper_daily_entries, state.paper_loss_streak):
                if type(value) is not int or value < 0:
                    raise ValueError("Invalid paper risk counter")
            if state.paper_last_entry_at is not None and datetime.fromisoformat(state.paper_last_entry_at).tzinfo is None:
                raise ValueError("Paper entry timestamp requires timezone")
            if bool(state.paper_risk_day) != (state.paper_risk_baseline is not None):
                raise ValueError("Incomplete paper risk state")
            if state.paper_risk_day:
                datetime.strptime(state.paper_risk_day, "%Y-%m-%d")
            for value in (state.paper_risk_baseline, state.paper_last_equity):
                if value is not None and (not Decimal(value).is_finite() or Decimal(value) < 0):
                    raise ValueError("Invalid paper equity state")
            if state.state_symbol is not None and state.state_symbol != self.config.symbol.upper():
                raise ValueError("State symbol mismatch")
            if state.state_mode is not None and state.state_mode != self.config.mode:
                raise ValueError("State mode mismatch")
            if state.paper_strategy_config is not None:
                if not isinstance(state.paper_strategy_config, dict) or set(state.paper_strategy_config) != set(asdict(MtfEmaConfig())):
                    raise ValueError("Invalid persisted strategy fields")
                MtfEmaConfig(**state.paper_strategy_config)
            for name in ("cash_usdc", "position_quantity", "entry_price", "realized_pnl", "fees_usdc"):
                if not Decimal(getattr(state, name)).is_finite():
                    raise ValueError("Non-finite state value")
            if Decimal(state.entry_price) < 0 or Decimal(state.fees_usdc) < 0:
                raise ValueError("Negative entry price or fees")
            if Decimal(state.position_quantity) == 0 and Decimal(state.entry_price) != 0:
                raise ValueError("Flat position cannot have entry price")
            if state.paper_entry_cost is not None:
                cost = Decimal(state.paper_entry_cost)
                if not cost.is_finite() or cost <= 0 or Decimal(state.position_quantity) <= 0:
                    raise ValueError("Invalid paper entry cost")
            if state.last_signal_bar is not None:
                parsed = datetime.fromisoformat(state.last_signal_bar)
                if parsed.tzinfo is None:
                    raise ValueError("Signal timestamp must include timezone")
            if Decimal(state.cash_usdc) < 0 or Decimal(state.position_quantity) < 0:
                raise ValueError("余额或仓位不能为负数")
            if Decimal(state.position_quantity) > 0 and Decimal(state.entry_price) <= 0:
                raise ValueError("持仓存在时 entry_price 必须大于 0")
            pending_fields = (
                state.pending_action,
                state.pending_from_amount,
                state.pending_submitted_at,
            )
            if state.pending_order_id and any(value is None for value in pending_fields):
                raise ValueError("未决订单记录不完整")
            if state.pending_action not in {None, "buy", "sell"}:
                raise ValueError("未决订单 action 非法")
            if not state.pending_order_id and any(value is not None for value in pending_fields):
                raise ValueError("Orphan pending-order fields")
            if state.pending_order_id:
                pending_amount = Decimal(state.pending_from_amount)
                if not pending_amount.is_finite() or pending_amount <= 0:
                    raise ValueError("Invalid pending amount")
                if datetime.fromisoformat(state.pending_submitted_at).tzinfo is None:
                    raise ValueError("Pending timestamp must include timezone")
            return state
        except FileNotFoundError:
            return EngineState()
        except (OSError, TypeError, ValueError, InvalidOperation) as exc:
            raise RuntimeError(
                f"状态文件损坏或不可读取，已停止以避免误判为空仓：{self._state_path()}"
            ) from exc

    def _save_state(self) -> None:
        if self.config.mode == "paper" and isinstance(self.strategy, MtfEmaStrategy):
            self.state.paper_strategy_config = asdict(self.strategy.config)
        self.state.state_symbol = self.config.symbol.upper()
        self.state.state_mode = self.config.mode
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(self.state), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

