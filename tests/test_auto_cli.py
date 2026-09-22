import pytest

import bstock_web3.auto_cli as auto_cli
from bstock_web3.auto_cli import main


def test_stop_control_is_idempotent_and_has_no_network(tmp_path):
    (tmp_path / "session.json").write_text("{}", encoding="utf-8")
    assert main(["stop", "--state-dir", str(tmp_path)]) == 0
    assert main(["stop", "--state-dir", str(tmp_path)]) == 0
    assert (tmp_path / "stop.request").read_text(encoding="ascii") == "requested\n"


def test_missing_session_cannot_create_control_file(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["resume-buys", "--state-dir", str(tmp_path)])
    assert error.value.code == 2
    assert not (tmp_path / "resume.request").exists()


def test_production_run_without_credentials_is_blocked_before_network(
        tmp_path, monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    with pytest.raises(SystemExit) as error:
        main(["run", "--live", "--state-dir", str(tmp_path)])
    assert error.value.code == 2
    assert not (tmp_path / "session.json").exists()


def test_production_run_requires_expected_uid_before_any_api_call(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["run", "--live", "--state-dir", str(tmp_path)])
    assert error.value.code == 2
    assert not list(tmp_path.iterdir())


def test_preflight_is_read_only_and_reports_bound_uid(monkeypatch, capsys):
    monkeypatch.setenv("BINANCE_API_KEY", "fixture-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "fixture-secret")
    calls = []
    class FakeApi:
        def __init__(self, credentials, *, base_url):
            self.credentials = credentials
        def account(self):
            calls.append("GET account")
            return {"uid": 123, "accountType": "SPOT", "canTrade": True,
                "balances": [{"asset": "USDT", "free": "200", "locked": "0"}]}
        def exchange_info(self, symbol):
            calls.append("GET exchangeInfo")
            return {"symbols": [{"symbol": symbol, "status": "TRADING",
                "isSpotTradingAllowed": True, "quoteOrderQtyMarketAllowed": True,
                "orderTypes": ["MARKET"], "baseAsset": "BTC", "quoteAsset": "USDT",
                "filters": [{"filterType": "LOT_SIZE", "minQty": "0.001",
                    "maxQty": "100", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "5",
                    "applyToMarket": True}]}]}
        def commission(self, symbol):
            calls.append("GET commission")
            return {"symbol": symbol}
        def book_ticker(self, symbol):
            calls.append("GET bookTicker")
            return {"symbol": symbol}
        def open_orders_all(self):
            calls.append("GET openOrders")
            return []
    monkeypatch.setattr(auto_cli, "BinanceSpotApi", FakeApi)
    assert main(["preflight", "--testnet", "--expected-uid", "123"]) == 0
    output = capsys.readouterr().out
    assert '"uid": 123' in output
    assert "fixture-key" not in output and "fixture-secret" not in output
    assert calls == ["GET account", "GET exchangeInfo", "GET commission",
                     "GET bookTicker", "GET openOrders"]
