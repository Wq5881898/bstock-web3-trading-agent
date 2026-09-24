from datetime import datetime, timezone

import pytest

from bstock_web3.mcp_bridge import (
    MCP_SPOT_READ_TOOLS, build_mcp_spot_read_request,
    write_mcp_account_binding, write_mcp_read_request,
)
from bstock_web3.mcp_equity_guard import McpSpotEquityGuard
from bstock_web3.mcp_host_cycle import import_and_cycle

from test_mcp_cycle import Catalog, Feed, Strategy
from test_mcp_equity_guard import BINDING, BASE_TIME, receipt


def setup(tmp_path, *, baseline=True):
    binding_path = tmp_path / "binding.json"
    request_path = tmp_path / "request.json"
    verified_path = tmp_path / "verified.json"
    runtime_dir = tmp_path / "runtime"
    write_mcp_account_binding(BINDING, binding_path)
    request = build_mcp_spot_read_request(
        "BTCUSDT", account_binding=BINDING,
        now=datetime.fromtimestamp(BASE_TIME / 1000, timezone.utc))
    write_mcp_read_request(request, request_path)
    if baseline:
        risk_path = runtime_dir / "live/btcusdt-equity-risk.json"
        with McpSpotEquityGuard(risk_path, account_ref="agentic-primary",
                account_fingerprint="b" * 64, symbol="BTCUSDT") as guard:
            guard.initialize(receipt(), operator_confirmed=True)
    read = receipt(request.request_id, when=BASE_TIME + 1000)
    payload = {
        "schema_version": "1.0", "request_id": request.request_id,
        "operation": "READ_SPOT_SNAPSHOT_RESULT", "host": "codex",
        "transport": "codex-binance-agent-os-mcp", "symbol": "BTCUSDT",
        "account_ref": "agentic-primary", "account_fingerprint": "b" * 64,
        "observed_at": read.observed_at,
        "completed_tools": list(MCP_SPOT_READ_TOOLS),
        "pagination": {"trades_complete": True, "orders_complete": True},
        "tool_results": read.tool_results,
    }
    return payload, request_path, binding_path, verified_path, runtime_dir


def invoke(payload, request_path, binding_path, verified_path, runtime_dir,
           *, now_ms=BASE_TIME + 1000):
    return import_and_cycle(payload, request_path=request_path,
        binding_path=binding_path, verified_path=verified_path,
        runtime_dir=runtime_dir, now_ms=now_ms,
        catalog=Catalog(), feed=Feed(), strategy=Strategy())


def test_atomic_import_and_cycle_emits_one_candidate(tmp_path):
    args = setup(tmp_path)
    result = invoke(*args)
    assert result["status"] == "READY"
    assert args[3].is_file()
    assert len(list((args[4] / "live/candidates").glob("candidate-*.json"))) == 1
    second = invoke(*args)
    assert second["status"] == "BLOCKED"
    assert second["reason"] == "session_not_running"


def test_account_mismatch_rejected_before_verified_file_or_candidate(tmp_path):
    args = setup(tmp_path)
    args[0]["account_fingerprint"] = "c" * 64
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        invoke(*args)
    assert not args[3].exists()
    assert not (args[4] / "live/btcusdt-strategy-session.json").exists()


def test_stale_host_receipt_cannot_start_session(tmp_path):
    args = setup(tmp_path)
    with pytest.raises(ValueError, match="fresh account receipt"):
        invoke(*args, now_ms=BASE_TIME + 16_001)
    assert not (args[4] / "live/btcusdt-strategy-session.json").exists()
    assert not list((args[4] / "live/candidates").glob("candidate-*.json"))


def test_missing_equity_baseline_fails_closed(tmp_path):
    args = setup(tmp_path, baseline=False)
    with pytest.raises(RuntimeError, match="baseline"):
        invoke(*args)
    assert not (args[4] / "live/btcusdt-strategy-session.json").exists()
