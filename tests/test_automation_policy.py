from dataclasses import replace
from decimal import Decimal

import pytest

from bstock_web3.automation_policy import (AccountRiskSnapshot,
    AutomationAction, AutomationPolicy, AutomationPolicyConfig)
from bstock_web3.execution_contract import (ExecutionInstrument, ProductType,
    order_intent)
from bstock_web3.strategy import SignalDecision


NOW = 1_800_000_000_000
INSTRUMENT = ExecutionInstrument("NVDABUSDT", ProductType.SPOT, "BINANCE",
    "NVDAB", "USDT")


def intent(action):
    return order_intent(SignalDecision(action, "fixture", 200, "bar",
        strategy_id="range-auto"), INSTRUMENT)


def snapshot(**changes):
    base = AccountRiskSnapshot("agentic-sub:redacted", "NVDABUSDT",
        ProductType.SPOT, "2027-01-15", NOW, True, True, Decimal("200"),
        Decimal("0"), Decimal("0"), Decimal("0"))
    return replace(base, **changes)


def test_defaults_match_agreed_100_order_and_10_cumulative_loss():
    config = AutomationPolicyConfig()
    assert config.order_budget_quote == Decimal("100")
    assert config.cumulative_loss_limit == Decimal("10")
    assert AutomationPolicy(config).evaluate(intent("buy"), snapshot(),
        now_ms=NOW).allowed


def test_cumulative_loss_latches_buys_but_never_suppresses_signal_exit():
    policy = AutomationPolicy()
    buy = policy.evaluate(intent("buy"), snapshot(daily_equity_loss=Decimal("10")),
        now_ms=NOW)
    assert buy.action == AutomationAction.BLOCK
    assert buy.buy_pause_reason == "cumulative_loss_limit"
    assert buy.notify_operator
    sell = policy.evaluate(intent("sell"), snapshot(
        daily_equity_loss=Decimal("11"), position_quantity=Decimal("0.5"),
        position_cost=Decimal("100")), now_ms=NOW)
    assert sell.allowed and sell.buy_pause_reason == "cumulative_loss_limit"
    assert not sell.notify_operator


def test_manual_resume_requires_fresh_reconciled_snapshot_and_inactive_limits():
    policy = AutomationPolicy()
    policy.pause_buys(now_ms=NOW)
    blocked = policy.request_manual_resume(snapshot(
        daily_equity_loss=Decimal("10")), now_ms=NOW)
    assert not blocked.allowed and policy.buy_pause_reason == "manual_pause"
    blocked = policy.request_manual_resume(snapshot(reconciled=False), now_ms=NOW)
    assert "account_not_reconciled" in blocked.reasons
    assert policy.request_manual_resume(snapshot(risk_day="2027-01-16"),
        now_ms=NOW).allowed
    assert policy.buy_pause_reason is None


def test_snapshot_health_pending_order_and_position_limits_fail_closed():
    policy = AutomationPolicy()
    result = policy.evaluate(intent("buy"), snapshot(
        observed_at_ms=NOW-16_000, pending_order_id="pending",
        position_cost=Decimal("1")), now_ms=NOW)
    assert set(result.reasons) >= {"stale_account_snapshot",
        "pending_order_exists", "position_cost_limit"}
    assert not policy.evaluate(intent("sell"), snapshot(), now_ms=NOW).allowed


def test_entry_count_streak_and_cooldown_controls_are_buy_only():
    policy = AutomationPolicy()
    result = policy.evaluate(intent("buy"), snapshot(daily_entries=20,
        consecutive_losses=3, last_entry_ms=NOW-1_000), now_ms=NOW)
    assert not result.allowed
    assert result.buy_pause_reason == "daily_entry_limit"
    assert "entry_cooldown" in result.reasons


def test_latch_checkpoint_survives_restart_and_rejects_corruption():
    policy = AutomationPolicy()
    policy.evaluate(intent("buy"), snapshot(daily_equity_loss=Decimal("10")),
        now_ms=NOW)
    restored = AutomationPolicy.restore(policy.checkpoint())
    assert restored.checkpoint() == policy.checkpoint()
    with pytest.raises(ValueError):
        AutomationPolicy.restore({**policy.checkpoint(), "latched_at_ms": None})
