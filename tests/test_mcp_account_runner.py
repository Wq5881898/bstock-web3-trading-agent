from threading import Event
import time

import pytest

from bstock_web3.mcp_account_runner import McpAccountRunner


def wait_done(runner):
    deadline = time.monotonic() + 2
    while runner.future is not None and not runner.future.done() \
            and time.monotonic() < deadline:
        time.sleep(.005)
    assert runner.future is not None and runner.future.done()


def test_runner_is_single_flight_and_delivers_url_and_result():
    entered, release = Event(), Event()
    def reader(symbol, *, announce_url, cancelled):
        announce_url("https://accounts.example/authorize")
        entered.set(); assert release.wait(2)
        assert not cancelled()
        return symbol
    runner = McpAccountRunner(reader)
    assert runner.start("BTCUSDT")
    assert entered.wait(1)
    assert not runner.start("ETHUSDT")
    assert runner.take_url() == "https://accounts.example/authorize"
    assert runner.take_url() is None
    release.set(); wait_done(runner)
    assert runner.take().result() == "BTCUSDT"
    runner.close()
    assert not runner.start("ETHUSDT")


def test_runner_cancel_is_observed_before_close():
    entered = Event()
    def reader(symbol, *, announce_url, cancelled):
        entered.set()
        while not cancelled():
            time.sleep(.005)
        raise ValueError("MCP account read cancelled")
    runner = McpAccountRunner(reader)
    runner.start("BTCUSDT"); assert entered.wait(1)
    with pytest.raises(RuntimeError, match="running"):
        runner.close()
    runner.cancel(); wait_done(runner)
    with pytest.raises(ValueError, match="cancelled"):
        runner.take().result()
    runner.close()
