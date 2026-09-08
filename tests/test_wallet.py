import json
from types import SimpleNamespace

from bstock_web3.wallet import AgenticWalletCli


def test_wallet_always_requests_json():
    seen = []

    def runner(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "success": True,
            "data": {"fromCoinSymbol": "USDC", "fromCoinAmount": "20",
                     "toCoinSymbol": "NVDAB", "toCoinAmount": "0.08", "slippage": 0.01},
        }), stderr="")

    quote = AgenticWalletCli(runner=runner).quote(
        amount="20", from_token="0x1", to_token="0x2"
    )
    assert quote.to_amount == "0.08"
    assert seen[0][-1] == "--json"


def test_swap_journals_order_before_status_timeout():
    submitted = []

    def runner(command, **kwargs):
        if command[1:3] == ["wallet", "status"]:
            payload = {"success": True, "data": {"status": "CONNECTED"}}
        elif command[1:3] == ["market-order", "swap"]:
            payload = {"success": True, "data": {"orderId": "order-7"}}
        else:
            payload = {"success": False, "error": "temporary status failure"}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    result = AgenticWalletCli(runner=runner, timeout_seconds=0.02,
                              poll_seconds=0.005).swap(
        amount="20", from_token="0x1", to_token="0x2",
        on_submitted=lambda order_id, at: submitted.append((order_id, at)),
    )
    assert result.status == "PENDING"
    assert result.order_id == "order-7"
    assert submitted[0][0] == "order-7"


def test_order_status_is_read_only_and_parses_actual_fill():
    seen = []

    def runner(command, **kwargs):
        seen.append(command)
        payload = {"success": True, "data": {"list": [{
            "orderId": "order-8", "status": "FINISHED", "txHash": "0xtx",
            "fromTokenQty": "20", "toTokenActualQty": "0.09",
        }]}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    result = AgenticWalletCli(runner=runner).order_status("order-8")
    assert result is not None
    assert result.status == "FINISHED"
    assert result.to_amount == "0.09"
    assert seen[0][1:3] == ["market-order", "list"]

