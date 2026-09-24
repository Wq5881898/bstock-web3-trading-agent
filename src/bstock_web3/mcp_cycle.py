"""One verified Spot strategy cycle after the existing MCP host read.

Public market reads are permitted here.  Private account reads and every
write remain with the already-authorized Codex MCP host.  This module only
joins a fresh host receipt to the durable local strategy session.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from .automation_policy import AutomationPolicyConfig
from .catalog import BinanceExchangeSpotCatalogClient
from .execution_lock import ExecutionLock
from .market_data import BStockMultiTimeframeFeed
from .mcp_bridge import load_mcp_account_binding
from .mcp_equity_guard import McpSpotEquityGuard
from .mcp_host_receipt import load_verified_receipt
from .mcp_session import (McpSessionBinding, McpSessionPhase,
                          McpTradingSession)
from .mcp_spot_snapshot import LocalRiskMetrics
from .spot_accounting import SpotFillLedger, fill_risk_stats
from .strategy import MtfEmaConfig, MtfEmaStrategy, PositionView


@dataclass(frozen=True)
class McpCyclePaths:
    binding: Path
    receipt: Path
    equity_guard: Path
    fill_ledger: Path
    session: Path
    candidates: Path


def _fresh_receipt(paths: McpCyclePaths, *, now_ms: int):
    binding = load_mcp_account_binding(paths.binding)
    receipt = load_verified_receipt(paths.receipt, binding)
    if receipt.symbol != "BTCUSDT":
        raise ValueError("Current MCP strategy cycle supports BTCUSDT only")
    age_ms = now_ms - receipt.observed_at_ms
    if not 0 <= age_ms <= 15_000:
        raise ValueError("MCP strategy cycle requires a fresh account receipt")
    return binding, receipt


def run_cycle(paths: McpCyclePaths, *, now_ms: int | None = None,
              catalog=None, feed=None, strategy=None,
              strategy_config: MtfEmaConfig | None = None):
    """Make at most one durable candidate; never call a private MCP tool."""
    if not isinstance(paths, McpCyclePaths):
        raise ValueError("Invalid MCP cycle paths")
    current = now_ms if now_ms is not None else int(
        datetime.now(timezone.utc).timestamp() * 1000)
    if type(current) is not int or current < 0:
        raise ValueError("Invalid MCP cycle time")
    config = strategy_config or MtfEmaConfig()
    if not isinstance(config, MtfEmaConfig):
        raise ValueError("Invalid MCP cycle strategy configuration")
    policy = AutomationPolicyConfig(
        order_budget_quote=Decimal("100"),
        cumulative_loss_limit=Decimal("10"),
        max_position_cost=Decimal("100"),
        max_daily_entries=20, max_consecutive_losses=3,
        entry_cooldown_seconds=60, snapshot_max_age_seconds=15)
    lock = ExecutionLock(paths.session.with_suffix(paths.session.suffix + ".lock"))
    lock.require()
    try:
        binding, receipt = _fresh_receipt(paths, now_ms=current)
        market = catalog or BinanceExchangeSpotCatalogClient()
        asset = market.resolve(receipt.symbol)
        status = market.market_status(asset)
        if not status.open_state or status.reason_code != "TRADING":
            return {"status": "BLOCKED", "reason": "market_unavailable",
                    "phase": None, "planFile": None}
        snapshot = (feed or BStockMultiTimeframeFeed()).fetch(
            asset, now=datetime.fromtimestamp(current / 1000, timezone.utc))
        checked_at = (current if now_ms is not None else int(
            datetime.now(timezone.utc).timestamp() * 1000))
        checked_binding, checked_receipt = _fresh_receipt(
            paths, now_ms=checked_at)
        if (checked_binding != binding
                or checked_receipt.request_id != receipt.request_id
                or checked_receipt.observed_at != receipt.observed_at
                or checked_receipt.tool_results != receipt.tool_results):
            raise ValueError("MCP account evidence changed during strategy evaluation")
        with McpSpotEquityGuard(
                paths.equity_guard, account_ref=receipt.account_ref,
                account_fingerprint=receipt.account_fingerprint,
                symbol=receipt.symbol) as guard:
            equity = guard.observe(receipt)
        with SpotFillLedger(
                paths.fill_ledger, account_ref=receipt.account_ref,
                symbol=receipt.symbol, base_asset=receipt.base_asset,
                quote_asset=receipt.quote_asset) as ledger:
            ledger.sync(receipt.tool_results["spot.myTrades"],
                        history_complete=True)
        risk_day = datetime.fromtimestamp(
            receipt.observed_at_ms / 1000, timezone.utc).date().isoformat()
        stats = fill_risk_stats(
            receipt.tool_results["spot.myTrades"], receipt.symbol,
            receipt.base_asset, receipt.quote_asset, risk_day)
        evidence = receipt.to_evidence(risk_day=risk_day,
            risk=LocalRiskMetrics(equity.cumulative_loss,
                stats.daily_entries, stats.consecutive_losses,
                stats.last_entry_ms))
        quantity, cost = receipt.tradable_position()
        entry = cost / quantity if quantity > 0 and cost > 0 else Decimal("0")
        signal = (strategy or MtfEmaStrategy(config)).evaluate(
            snapshot, PositionView(float(quantity), float(entry)))
        signal = replace(signal, strategy_id="mtf",
                         strategy_params=asdict(config))
        if signal.signal_bar_time is None:
            if signal.action != "hold":
                raise ValueError("Actionable MCP strategy signal has no closed bar")
            return {"status": "HOLD", "reason": signal.reason,
                    "phase": None, "signal": "hold",
                    "signalBarTime": None, "planFile": None}
        try:
            bar_time = datetime.fromisoformat(
                signal.signal_bar_time.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Invalid MCP strategy signal bar time") from None
        if bar_time.tzinfo is None or not 0 <= checked_at - int(
                bar_time.timestamp() * 1000) <= 180_000:
            raise ValueError("MCP strategy signal bar is stale or future-dated")
        session_binding = McpSessionBinding.create(
            binding, symbol=receipt.symbol, strategy_id="mtf",
            strategy_config=asdict(config), risk_config=policy)
        new_session = not paths.session.exists()
        session = McpTradingSession(paths.session, session_binding, policy)
        if new_session:
            session.start(evidence, now_ms=checked_at)
        if session.phase not in {McpSessionPhase.RUNNING,
                                 McpSessionPhase.BUY_PAUSED}:
            return {"status": "BLOCKED", "reason": "session_not_running",
                    "phase": session.phase.value, "planFile": None}
        result = session.prepare_candidate(
            asset, signal, evidence, binding,
            output_dir=paths.candidates, now_ms=checked_at)
        return {"status": result.status, "reason": ",".join(result.reasons),
                "phase": result.phase.value,
                "signal": signal.action,
                "signalBarTime": signal.signal_bar_time,
                "planFile": str(result.plan_path) if result.plan_path else None}
    finally:
        lock.release()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Join one fresh Binance Agent OS receipt to the durable BTCUSDT strategy session; no order submission")
    parser.add_argument("--verified-snapshot", type=Path, required=True)
    parser.add_argument("--binding-file", type=Path,
        default=Path("runtime/desktop/mcp/account-binding.json"))
    parser.add_argument("--runtime-dir", type=Path,
        default=Path("runtime/desktop/mcp"))
    args = parser.parse_args()
    paths = McpCyclePaths(
        binding=args.binding_file, receipt=args.verified_snapshot,
        equity_guard=args.runtime_dir / "live/btcusdt-equity-risk.json",
        fill_ledger=args.runtime_dir / "live/btcusdt-fills.json",
        session=args.runtime_dir / "live/btcusdt-strategy-session.json",
        candidates=args.runtime_dir / "live/candidates")
    print(json.dumps(run_cycle(paths), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
