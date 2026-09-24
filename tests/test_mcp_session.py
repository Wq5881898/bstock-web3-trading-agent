from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest

from bstock_web3.automation_policy import AutomationPolicyConfig
from bstock_web3.catalog import BStockAsset
from bstock_web3.execution_contract import ProductType
from bstock_web3.execution_safety import McpReconciliationEvidence
from bstock_web3.mcp_bridge import McpAccountBinding
from bstock_web3.mcp_session import (McpSessionBinding, McpSessionPhase,
                                     McpTradingSession)
from bstock_web3.strategy import SignalDecision


NOW = 2_000_000_000_000
ASSET = BStockAsset("NVDA", "NVDAB", "0x02fc", "56", "NVDABUSDT", "1")
ACCOUNT = McpAccountBinding(
    "1.0", "agentic-primary", "sha256(salt-bytes+uid-ascii)",
    "a" * 64, "b" * 64)
POLICY = AutomationPolicyConfig()
BINDING = McpSessionBinding.create(
    ACCOUNT, symbol="NVDABUSDT", strategy_id="mtf",
    strategy_config={"fast": 9, "slow": 21}, risk_config=POLICY)


def evidence(**changes):
    values = dict(
        evidence_id="mcp-session-0001", account_ref="agentic-primary",
        symbol="NVDABUSDT", product=ProductType.SPOT,
        risk_day="2033-05-18", observed_at_ms=NOW,
        account_checked=True, balances_checked=True,
        open_orders_checked=True, fills_checked=True, can_trade=True,
        available_quote=Decimal("200"), position_quantity=Decimal("0"),
        position_cost=Decimal("0"), daily_equity_loss=Decimal("0"),
    )
    values.update(changes)
    return McpReconciliationEvidence(**values)


def signal(action="buy", stamp="2033-05-18T03:33:00Z"):
    return SignalDecision(action, "test", 220.0, stamp,
                          expected_edge=0.004, strategy_id="mtf")


def started(tmp_path, **evidence_changes):
    session = McpTradingSession(tmp_path / "session.json", BINDING, POLICY)
    session.start(evidence(**evidence_changes), now_ms=NOW)
    return session


def test_session_binding_is_immutable_and_persistent(tmp_path):
    session = started(tmp_path)
    assert session.phase == McpSessionPhase.RUNNING
    restored = McpTradingSession(session.path, BINDING, POLICY)
    assert restored.phase == McpSessionPhase.RUNNING
    assert restored.binding == BINDING

    changed = McpSessionBinding.create(
        ACCOUNT, symbol="BTCUSDT", strategy_id="mtf",
        strategy_config={"fast": 9, "slow": 21}, risk_config=POLICY)
    with pytest.raises(ValueError, match="Invalid MCP trading session"):
        McpTradingSession(session.path, changed, POLICY)


def test_candidate_is_credential_free_persistent_and_idempotent(tmp_path):
    session = started(tmp_path)
    result = session.prepare_candidate(
        ASSET, signal(), evidence(), ACCOUNT,
        output_dir=tmp_path / "candidates", now_ms=NOW + 1)
    assert result.status == "READY"
    assert result.phase == McpSessionPhase.WAITING_CONFIRMATION
    assert result.plan_path.exists()
    encoded = result.plan_path.read_text(encoding="utf-8").lower()
    assert "api_key" not in encoded and "access_token" not in encoded

    restored = McpTradingSession(session.path, BINDING, POLICY)
    assert restored.phase == McpSessionPhase.WAITING_CONFIRMATION
    restored.dismiss_candidate(outcome="EXPIRED", now_ms=NOW + 2)
    duplicate = restored.prepare_candidate(
        ASSET, signal(), evidence(observed_at_ms=NOW + 3), ACCOUNT,
        output_dir=tmp_path / "candidates", now_ms=NOW + 3)
    assert duplicate.status == "DUPLICATE"
    assert duplicate.reasons == ("signal_already_processed",)


def test_loss_latch_blocks_buy_but_allows_sell(tmp_path):
    session = started(tmp_path, daily_equity_loss=Decimal("10"),
                      position_quantity=Decimal("0.25"),
                      position_cost=Decimal("90"))
    assert session.phase == McpSessionPhase.BUY_PAUSED
    buy = session.prepare_candidate(
        ASSET, signal("buy"), evidence(
            observed_at_ms=NOW + 1, daily_equity_loss=Decimal("10"),
            position_quantity=Decimal("0.25"), position_cost=Decimal("90")),
        ACCOUNT, output_dir=tmp_path / "candidates", now_ms=NOW + 1)
    assert buy.status == "BLOCKED"
    assert "buy_paused:cumulative_loss_limit" in buy.reasons

    sell = session.prepare_candidate(
        ASSET, signal("sell", "2033-05-18T03:34:00Z"), evidence(
            observed_at_ms=NOW + 2, daily_equity_loss=Decimal("10"),
            position_quantity=Decimal("0.25"), position_cost=Decimal("90")),
        ACCOUNT, output_dir=tmp_path / "candidates", now_ms=NOW + 2)
    assert sell.status == "READY"
    assert sell.plan.side == "SELL"
    assert sell.plan.order_arguments["quantity"] == "0.25"


def test_sell_candidate_excludes_reconciled_dust(tmp_path):
    session = started(tmp_path, position_quantity=Decimal("0.00011988"),
                      position_cost=Decimal("9.5"),
                      dust_quantity=Decimal("0.00000988"),
                      dust_cost=Decimal("0.78"))
    result = session.prepare_candidate(
        ASSET, signal("sell"), evidence(
            position_quantity=Decimal("0.00011988"),
            position_cost=Decimal("9.5"),
            dust_quantity=Decimal("0.00000988"),
            dust_cost=Decimal("0.78")),
        ACCOUNT, output_dir=tmp_path / "candidates", now_ms=NOW + 1)
    assert result.status == "READY"
    assert Decimal(result.plan.order_arguments["quantity"]) == Decimal("0.00011")


def test_dust_only_sell_signal_creates_no_candidate(tmp_path):
    session = started(tmp_path, position_quantity=Decimal("0.00000988"),
                      position_cost=Decimal("0.78"),
                      dust_quantity=Decimal("0.00000988"),
                      dust_cost=Decimal("0.78"))
    result = session.prepare_candidate(
        ASSET, signal("sell"), evidence(
            position_quantity=Decimal("0.00000988"),
            position_cost=Decimal("0.78"),
            dust_quantity=Decimal("0.00000988"),
            dust_cost=Decimal("0.78")),
        ACCOUNT, output_dir=tmp_path / "candidates", now_ms=NOW + 1)
    assert result.status == "BLOCKED"
    assert result.reasons == ("no_tradable_position",)


def test_manual_resume_never_bypasses_active_loss(tmp_path):
    session = started(tmp_path, daily_equity_loss=Decimal("10"))
    blocked = session.request_manual_resume(
        evidence(observed_at_ms=NOW + 1,
                 daily_equity_loss=Decimal("10")), now_ms=NOW + 1)
    assert not blocked.allowed
    assert session.phase == McpSessionPhase.BUY_PAUSED

    allowed = session.request_manual_resume(
        evidence(observed_at_ms=NOW + 2,
                 daily_equity_loss=Decimal("9")), now_ms=NOW + 2)
    assert allowed.allowed
    assert session.phase == McpSessionPhase.RUNNING


def test_stop_waits_for_pending_candidate_then_stops(tmp_path):
    session = started(tmp_path)
    session.prepare_candidate(
        ASSET, signal(), evidence(), ACCOUNT,
        output_dir=tmp_path / "candidates", now_ms=NOW + 1)
    assert session.stop(now_ms=NOW + 2) == McpSessionPhase.STOPPING
    assert session.prepare_candidate(
        ASSET, signal("buy", "2033-05-18T03:35:00Z"), evidence(), ACCOUNT,
        output_dir=tmp_path / "candidates", now_ms=NOW + 3).status == "BLOCKED"
    assert session.dismiss_candidate(
        outcome="CANCELLED", now_ms=NOW + 4) == McpSessionPhase.STOPPED
    assert McpTradingSession(session.path, BINDING, POLICY).phase == McpSessionPhase.STOPPED


def test_candidate_write_failure_enters_recovery_without_retry(tmp_path,
                                                                monkeypatch):
    session = started(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("injected write failure")

    monkeypatch.setattr("bstock_web3.mcp_session.write_mcp_plan", fail)
    with pytest.raises(OSError, match="injected"):
        session.prepare_candidate(
            ASSET, signal(), evidence(), ACCOUNT,
            output_dir=tmp_path / "candidates", now_ms=NOW + 1)
    assert session.phase == McpSessionPhase.RECOVERY_ONLY
    restored = McpTradingSession(session.path, BINDING, POLICY)
    assert restored.phase == McpSessionPhase.RECOVERY_ONLY
    blocked = restored.prepare_candidate(
        ASSET, signal(), evidence(), ACCOUNT,
        output_dir=tmp_path / "candidates", now_ms=NOW + 2)
    assert blocked.status == "BLOCKED"


def test_interrupted_start_is_recovered_fail_closed(tmp_path):
    session = started(tmp_path)
    payload = json.loads(session.path.read_text(encoding="utf-8"))
    payload["phase"] = "STARTING"
    session.path.write_text(json.dumps(payload), encoding="utf-8")
    restored = McpTradingSession(session.path, BINDING, POLICY)
    assert restored.phase == McpSessionPhase.RECOVERY_ONLY
    assert restored.recovery_reason == "interrupted_persistent_transition"


@pytest.mark.parametrize(("field", "value"), [
    ("updated_at_ms", -1),
    ("pending", {"status": "READY"}),
    ("phase", "WAITING_CONFIRMATION"),
])
def test_corrupt_or_inconsistent_session_state_is_rejected(tmp_path, field,
                                                            value):
    session = started(tmp_path)
    payload = json.loads(session.path.read_text(encoding="utf-8"))
    payload[field] = value
    session.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid MCP trading session"):
        McpTradingSession(session.path, BINDING, POLICY)


def test_account_or_strategy_drift_is_rejected(tmp_path):
    session = started(tmp_path)
    wrong_account = McpAccountBinding(
        "1.0", "agentic-primary", "sha256(salt-bytes+uid-ascii)",
        "a" * 64, "c" * 64)
    with pytest.raises(ValueError, match="binding changed"):
        session.prepare_candidate(
            ASSET, signal(), evidence(), wrong_account,
            output_dir=tmp_path / "candidates", now_ms=NOW + 1)
    with pytest.raises(ValueError, match="Strategy changed"):
        session.prepare_candidate(
            ASSET, SignalDecision("buy", "test", 220.0,
                "2033-05-18T03:34:00Z", expected_edge=0.004,
                strategy_id="median"), evidence(), ACCOUNT,
            output_dir=tmp_path / "candidates", now_ms=NOW + 1)
