from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import secrets
from typing import Literal

from .catalog import BStockAsset, BStockCatalogClient
from .eligibility import EligibilitySnapshot
from .market_data import BStockMultiTimeframeFeed
from .strategy import MtfEmaStrategy, PositionView, SignalDecision
from .wallet import AgenticWalletCli, USDC_BSC, WalletOrderResult, WalletQuote


EngineMode = Literal["paper", "quote", "live-confirmed"]


@dataclass
class EngineState:
    cash_usdc: str = "1000"
    position_quantity: str = "0"
    entry_price: str = "0"
    realized_pnl: str = "0"
    fees_usdc: str = "0"
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

    def __post_init__(self) -> None:
        if self.order_size_usdc <= 0:
            raise ValueError("order_size_usdc 必须大于 0")
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


class BStockEngine:
    def __init__(self, config: BStockEngineConfig, *,
                 catalog: BStockCatalogClient | None = None,
                 feed: BStockMultiTimeframeFeed | None = None,
                 strategy: MtfEmaStrategy | None = None,
                 wallet: AgenticWalletCli | None = None) -> None:
        self.config = config
        self.catalog = catalog or BStockCatalogClient()
        self.feed = feed or BStockMultiTimeframeFeed()
        self.strategy = strategy or MtfEmaStrategy()
        self.wallet = wallet or AgenticWalletCli()
        self.asset: BStockAsset | None = None
        self.state = self._load_state()

    def adopt_position(self, *, quantity: Decimal, entry_price: Decimal) -> None:
        if quantity <= 0 or entry_price <= 0:
            raise ValueError("接管仓位时 quantity 和 entry_price 必须大于 0")
        current = Decimal(self.state.position_quantity)
        if current > 0 and (current != quantity or Decimal(self.state.entry_price) != entry_price):
            raise RuntimeError("引擎已有不同仓位；拒绝覆盖，请先人工核对状态文件")
        self.state.position_quantity, self.state.entry_price = str(quantity), str(entry_price)
        self._save_state()

    def evaluate_once(self, *, now: datetime | None = None) -> EngineEvent:
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
        signal_bar = snapshot.signal_bar_time.isoformat() if snapshot.signal_bar_time else None
        if signal_bar is not None and signal_bar == self.state.last_signal_bar:
            return EngineEvent(asset, SignalDecision(
                "hold", "signal_bar_already_processed", None, signal_bar
            ), self.config.mode)
        decision = self.strategy.evaluate(snapshot, self.state.position)
        if decision.action == "hold":
            self.state.last_signal_bar = signal_bar
            self._save_state()
            return EngineEvent(asset, decision, self.config.mode)
        if self.config.mode == "paper":
            self.state.last_signal_bar = signal_bar
            return EngineEvent(asset, decision, self.config.mode, paper_fill=self._paper_fill(decision))
        self.wallet.require_connected()
        plan = self._build_plan(asset, decision)
        self.state.last_signal_bar = signal_bar
        self._save_state()
        return EngineEvent(asset, decision, self.config.mode, plan=plan)

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

    def _paper_fill(self, decision: SignalDecision) -> dict[str, str]:
        price, fee_rate = Decimal(str(decision.price)), self.config.paper_fee_rate
        if decision.action == "buy":
            spend = min(self.config.order_size_usdc, Decimal(self.state.cash_usdc))
            fee, quantity = spend * fee_rate, (spend * (1 - fee_rate)) / price
            self.state.cash_usdc = str(Decimal(self.state.cash_usdc) - spend)
            self.state.position_quantity, self.state.entry_price = str(quantity), str(price)
            fill = {"side": "buy", "price": str(price), "quantity": str(quantity), "fee": str(fee)}
        else:
            quantity = Decimal(self.state.position_quantity)
            gross, cost = quantity * price, quantity * Decimal(self.state.entry_price)
            fee = gross * fee_rate
            self.state.cash_usdc = str(Decimal(self.state.cash_usdc) + gross - fee)
            self.state.realized_pnl = str(Decimal(self.state.realized_pnl) + gross - fee - cost)
            self.state.position_quantity, self.state.entry_price = "0", "0"
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
            return state
        except FileNotFoundError:
            return EngineState()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"状态文件损坏或不可读取，已停止以避免误判为空仓：{self._state_path()}"
            ) from exc

    def _save_state(self) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(self.state), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

