from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bstock_web3.mcp_bridge import (MCP_SPOT_READ_TOOLS,
    McpAccountBinding, build_mcp_spot_read_request,
    load_mcp_account_binding, load_mcp_read_request,
    write_mcp_account_binding, write_mcp_read_request)
from bstock_web3.mcp_host_receipt import (verify_spot_host_receipt,
    write_verified_receipt)
from bstock_web3.mcp_spot_snapshot import LocalRiskMetrics


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
SALT = "1" * 64


def binding(fingerprint=None):
    return McpAccountBinding("1.0", "agentic-primary",
        "sha256(salt-bytes+uid-ascii)", SALT, fingerprint)


def request(value=None):
    return build_mcp_spot_read_request("BTCUSDT", now=NOW,
        account_binding=value or binding())


def payload(req, fingerprint="2" * 64):
    return {
        "schema_version":"1.0",
        "request_id":req.request_id,
        "operation":"READ_SPOT_SNAPSHOT_RESULT",
        "host":"codex",
        "transport":"codex-binance-agent-os-mcp",
        "symbol":"BTCUSDT",
        "account_ref":"agentic-primary",
        "account_fingerprint":fingerprint,
        "observed_at":"2026-09-21T12:00:10Z",
        "completed_tools":list(MCP_SPOT_READ_TOOLS),
        "pagination":{"trades_complete":True, "orders_complete":True},
        "tool_results":{
            "spot.getAccount":{"accountType":"SPOT", "canTrade":True,
                "balances":[
                    {"asset":"BTC", "free":"0.00011988", "locked":"0"},
                    {"asset":"USDT", "free":"190.42", "locked":"0"}]},
            "spot.getOpenOrders":[],
            "spot.myTrades":[{"id":1, "symbol":"BTCUSDT",
                "orderId":456, "time":1_789_992_000_000,
                "qty":"0.00012000", "quoteQty":"9.57959880",
                "commission":"0.00000012", "commissionAsset":"BTC",
                "isBuyer":True}],
            "spot.allOrders":[{"symbol":"BTCUSDT", "orderId":456,
                "status":"FILLED"}],
            "spot.accountCommission":{"symbol":"BTCUSDT"},
            "spot.exchangeInfo":{"symbols":[{"symbol":"BTCUSDT",
                "status":"TRADING", "isSpotTradingAllowed":True,
                "baseAsset":"BTC", "quoteAsset":"USDT"}]},
            "spot.tickerBookTicker":{"symbol":"BTCUSDT",
                "bidPrice":"79800", "askPrice":"79801"},
        },
    }


def test_first_receipt_requires_explicit_enrollment_then_pins_account():
    req = request()
    with pytest.raises(RuntimeError, match="explicit enrollment"):
        verify_spot_host_receipt(req, binding(), payload(req),
                                 now=NOW + timedelta(seconds=20))
    verified = verify_spot_host_receipt(req, binding(), payload(req),
        allow_enroll=True, now=NOW + timedelta(seconds=20))
    assert verified.enrolled_now
    assert verified.binding.fingerprint == "2" * 64
    assert verified.summary() == {
        "requestId":req.request_id, "symbol":"BTCUSDT",
        "accountRef":"agentic-primary", "accountFingerprint":"2" * 64,
        "enrolledNow":True, "canTrade":True,
        "availableQuote":"190.42", "positionQuantity":"0.00011988",
        "positionCost":"9.57959880", "pendingOrderId":None,
        "observedAt":"2026-09-21T12:00:10Z"}
    evidence = verified.to_evidence(risk_day="2026-09-21",
        risk=LocalRiskMetrics(Decimal("3.5"), 2, 1))
    assert evidence.to_snapshot().daily_equity_loss == Decimal("3.5")


def test_enrolled_account_must_match_exact_fingerprint():
    pinned = binding("2" * 64)
    req = request(pinned)
    verified = verify_spot_host_receipt(req, pinned, payload(req),
        now=NOW + timedelta(seconds=20))
    assert not verified.enrolled_now
    changed = payload(req, "3" * 64)
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        verify_spot_host_receipt(req, pinned, changed,
            now=NOW + timedelta(seconds=20))


@pytest.mark.parametrize("change,match", [
    (("request_id", "other"), "match"),
    (("symbol", "ETHUSDT"), "match"),
    (("completed_tools", list(reversed(MCP_SPOT_READ_TOOLS))), "match"),
    (("pagination", {"trades_complete":False,
                     "orders_complete":True}), "match"),
    (("observed_at", "2026-09-21T12:06:00Z"), "outside"),
])
def test_receipt_must_match_request_lifetime_and_full_read_set(change, match):
    pinned = binding("2" * 64); req = request(pinned); value = payload(req)
    value[change[0]] = change[1]
    with pytest.raises(ValueError, match=match):
        verify_spot_host_receipt(req, pinned, value,
            now=NOW + timedelta(minutes=4))


@pytest.mark.parametrize("key,value", [
    ("uid", 1274302954), ("access_token", "secret"),
    ("apiKey", "secret"),
])
def test_receipt_rejects_identity_and_credentials_anywhere(key, value):
    pinned = binding("2" * 64); req = request(pinned); result = payload(req)
    result["tool_results"]["spot.getAccount"][key] = value
    with pytest.raises(ValueError, match="forbidden"):
        verify_spot_host_receipt(req, pinned, result,
            now=NOW + timedelta(seconds=20))


def test_receipt_reconciles_balances_and_complete_fills():
    pinned = binding("2" * 64); req = request(pinned); result = payload(req)
    result["tool_results"]["spot.getAccount"]["balances"][0]["free"] = "1"
    with pytest.raises(ValueError, match="reconcile"):
        verify_spot_host_receipt(req, pinned, result,
            now=NOW + timedelta(seconds=20))


def test_binding_request_and_verified_receipt_round_trip(tmp_path):
    binding_path = tmp_path / "binding.json"
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "verified.json"
    original = binding("2" * 64); req = request(original)
    write_mcp_account_binding(original, binding_path)
    write_mcp_read_request(req, request_path)
    assert load_mcp_account_binding(binding_path) == original
    assert load_mcp_read_request(request_path) == req
    verified = verify_spot_host_receipt(req, original, payload(req),
        now=NOW + timedelta(seconds=20))
    write_verified_receipt(verified, output_path)
    contents = output_path.read_text(encoding="utf-8")
    assert '"status": "VERIFIED"' in contents
    assert "uid" not in contents.lower() and "access_token" not in contents.lower()


def test_document_tampering_and_binding_replacement_fail_closed(tmp_path):
    req = request(binding("2" * 64)); path = tmp_path / "request.json"
    write_mcp_read_request(req, path)
    document = path.read_text(encoding="utf-8").replace(
        '"read_only": true', '"read_only": false')
    path.write_text(document, encoding="utf-8")
    with pytest.raises(ValueError, match="request"):
        load_mcp_read_request(path)
    replaced = binding("2" * 64)
    replaced = McpAccountBinding(replaced.schema_version, "other-account",
        replaced.algorithm, replaced.salt, replaced.fingerprint)
    with pytest.raises(ValueError, match="binding changed"):
        verify_spot_host_receipt(req, replaced, payload(req),
            now=NOW + timedelta(seconds=20))
