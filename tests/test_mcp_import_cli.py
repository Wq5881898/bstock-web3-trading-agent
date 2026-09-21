from datetime import datetime, timedelta, timezone
import json

from bstock_web3.mcp_bridge import (MCP_SPOT_READ_TOOLS,
    McpAccountBinding, build_mcp_spot_read_request,
    load_mcp_account_binding, write_mcp_account_binding,
    write_mcp_read_request)
from bstock_web3.mcp_import_cli import main


def test_import_cli_explicitly_enrolls_and_writes_verified_snapshot(
        monkeypatch, tmp_path, capsys):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    binding = McpAccountBinding("1.0", "agentic-primary",
        "sha256(salt-bytes+uid-ascii)", "1" * 64)
    request = build_mcp_spot_read_request("BTCUSDT", now=now,
        account_binding=binding)
    binding_path = tmp_path / "binding.json"
    request_path = tmp_path / "request.json"
    receipt_path = tmp_path / "receipt.json"
    output_path = tmp_path / "verified.json"
    write_mcp_account_binding(binding, binding_path)
    write_mcp_read_request(request, request_path)
    receipt_path.write_text(json.dumps({
        "schema_version":"1.0", "request_id":request.request_id,
        "operation":"READ_SPOT_SNAPSHOT_RESULT", "host":"codex",
        "transport":"codex-binance-agent-os-mcp", "symbol":"BTCUSDT",
        "account_ref":"agentic-primary", "account_fingerprint":"2" * 64,
        "observed_at":(now + timedelta(milliseconds=100)).isoformat()
            .replace("+00:00", "Z"),
        "completed_tools":list(MCP_SPOT_READ_TOOLS),
        "pagination":{"trades_complete":True, "orders_complete":True},
        "tool_results":{
            "spot.getAccount":{"accountType":"SPOT", "canTrade":True,
                "balances":[{"asset":"USDT", "free":"100", "locked":"0"}]},
            "spot.getOpenOrders":[], "spot.myTrades":[],
            "spot.allOrders":[],
            "spot.accountCommission":{"symbol":"BTCUSDT"},
            "spot.exchangeInfo":{"symbols":[{"symbol":"BTCUSDT",
                "status":"TRADING", "isSpotTradingAllowed":True,
                "baseAsset":"BTC", "quoteAsset":"USDT"}]},
            "spot.tickerBookTicker":{"symbol":"BTCUSDT",
                "bidPrice":"1", "askPrice":"2"}}},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["bstock-mcp-import",
        "--request", str(request_path), "--receipt", str(receipt_path),
        "--binding-file", str(binding_path), "--output", str(output_path),
        "--enroll-account"])
    assert main() == 0
    assert load_mcp_account_binding(binding_path).fingerprint == "2" * 64
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["status"] == "VERIFIED"
    assert saved["tool_results"]["spot.getAccount"]["balances"][0]["free"] == "100"
    printed = json.loads(capsys.readouterr().out)
    assert printed["summary"]["accountRef"] == "agentic-primary"
