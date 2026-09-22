"""Foreground autonomous Spot service and separate stop/resume controls.

This command is deliberately never launched by tests or imports. Credentials
come only from the process environment; production orders require --live.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import time

from .autonomous_runner import AutonomousSpotRunner
from .autonomous_service import SpotServiceCycle
from .autonomous_session import (AutonomousSpotSession, SessionBinding,
    SessionPhase)
from .automation_policy import AutomationPolicy, AutomationPolicyConfig
from .binance_spot_api import (BinanceSpotApi, SpotApiCredentials,
    PRODUCTION_URL, TESTNET_URL)
from .execution_lock import ExecutionLock
from .execution_safety import ExecutionJournal
from .mcp_confirmed import SpotMarketRules
from .provider import BinanceSpotKlineProvider
from .spot_api_reconcile import SpotApiReconciler
from .spot_signal_source import SpotMtfSignalSource
from .strategy import MtfEmaConfig
from .unattended_spot import UnattendedSpotExecutor


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _control(path: Path, name: str):
    session = path / "session.json"
    if not session.is_file():
        raise RuntimeError("No autonomous session exists in this state directory")
    target = path / name
    try:
        with target.open("x", encoding="ascii") as handle:
            handle.write("requested\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        pass


def _service(args):
    credentials = SpotApiCredentials.from_environment()
    api = BinanceSpotApi(credentials,
        base_url=PRODUCTION_URL if args.live else TESTNET_URL)
    policy_config = AutomationPolicyConfig(
        order_budget_quote=Decimal(args.order_budget),
        cumulative_loss_limit=Decimal(args.loss_limit),
        max_position_cost=Decimal(args.max_position_cost))
    policy = AutomationPolicy(policy_config)
    strategy_config = MtfEmaConfig()
    account_ref = "api-" + credentials.fingerprint[:20]
    binding = SessionBinding(account_ref, credentials.fingerprint, args.symbol,
        args.base, args.quote, "mtf", _digest(asdict(strategy_config)),
        _digest({key: str(value) for key, value in asdict(policy_config).items()}),
        args.expected_uid)
    directory = args.state_dir.resolve()
    journal_path = directory / "journal.json"
    lock = ExecutionLock(journal_path.with_suffix(".json.lock"))
    with lock:
        journal = ExecutionJournal(journal_path, lock)
        executor = UnattendedSpotExecutor(api, journal, policy,
            account_ref=account_ref, symbol=args.symbol)
        session = AutonomousSpotSession(directory / "session.json", binding,
                                        executor)
        reconciler = SpotApiReconciler(api, directory,
            account_ref=account_ref, symbol=args.symbol,
            base_asset=args.base, quote_asset=args.quote,
            expected_uid=args.expected_uid)
        market_url = PRODUCTION_URL if args.live else TESTNET_URL
        source = SpotMtfSignalSource(args.symbol, args.base, args.quote,
            config=strategy_config,
            provider=BinanceSpotKlineProvider(base_url=market_url))
        runner = AutonomousSpotRunner(session, reconciler, source)
        if session.phase == SessionPhase.STOPPED and not session.path.exists():
            runner.start(now_ms=int(time.time() * 1000))
        elif session.phase == SessionPhase.RECOVERY_ONLY and args.resume:
            snapshot = reconciler.read(now_ms=int(time.time() * 1000))
            if not session.resume(snapshot.evidence, now_ms=int(time.time() * 1000),
                                  filled_order_ids=snapshot.filled_order_ids):
                raise RuntimeError("Recovery lookup or risk gate is unresolved")
        elif session.phase == SessionPhase.STOPPING:
            pass  # restart completes the original stop; never resumes signals
        else:
            raise RuntimeError("Session exists; restart requires explicit --resume in recovery mode")
        print(json.dumps({"event": "STOPPING_RECOVERY" if session.phase == SessionPhase.STOPPING else "STARTED", "phase": session.phase.value,
            "symbol": args.symbol, "venue": "production" if args.live else "testnet",
            "account_ref": account_ref}, ensure_ascii=False), flush=True)
        service = SpotServiceCycle(session, runner, directory)
        while True:
            event = service.step(now_ms=int(time.time() * 1000))
            if event["event"] not in ("HOLD", "STOPPING") and (
                    event["event"] != "BLOCKED" or event.get("reasons") or event.get("reason")):
                print(json.dumps(event, ensure_ascii=False), flush=True)
            if event["event"] == "STOPPED":
                return 0
            time.sleep(args.poll_seconds)


def _preflight(args):
    credentials = SpotApiCredentials.from_environment()
    api = BinanceSpotApi(credentials,
        base_url=PRODUCTION_URL if args.live else TESTNET_URL)
    account = api.account()
    if (not isinstance(account, dict) or account.get("accountType") != "SPOT"
            or account.get("canTrade") is not True
            or type(account.get("uid")) is not int or account["uid"] <= 0):
        raise ValueError("Spot API account UID is unavailable")
    if args.expected_uid is not None and account["uid"] != args.expected_uid:
        raise ValueError("Spot API account UID mismatch")
    rules = SpotMarketRules.from_exchange_info(api.exchange_info(args.symbol),
                                               args.symbol)
    commission = api.commission(args.symbol)
    book = api.book_ticker(args.symbol)
    open_orders = api.open_orders_all()
    if (not isinstance(commission, dict) or commission.get("symbol") != args.symbol
            or not isinstance(book, dict) or book.get("symbol") != args.symbol
            or not isinstance(open_orders, list)):
        raise ValueError("Spot API preflight reads incomplete")
    balances = account.get("balances")
    if not isinstance(balances, list):
        raise ValueError("Spot API balances unavailable")
    selected = {row["asset"]: {"free": row["free"], "locked": row["locked"]}
        for row in balances if isinstance(row, dict)
        and row.get("asset") in (rules.base_asset, rules.quote_asset)}
    print(json.dumps({"event": "PREFLIGHT_READ_ONLY",
        "venue": "production" if args.live else "testnet",
        "uid": account["uid"], "can_trade": account.get("canTrade"),
        "symbol": rules.symbol, "base_asset": rules.base_asset,
        "quote_asset": rules.quote_asset, "balances": selected,
        "open_order_count": len(open_orders),
        "api_key_fingerprint_prefix": credentials.fingerprint[:12]},
        ensure_ascii=False), flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Single-symbol autonomous Binance Spot runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run in this terminal until stop is requested")
    run.add_argument("--state-dir", type=Path, required=True)
    run.add_argument("--symbol", default="BTCUSDT")
    run.add_argument("--base", default="BTC")
    run.add_argument("--quote", default="USDT")
    venue = run.add_mutually_exclusive_group(required=True)
    venue.add_argument("--live", action="store_true", help="REAL production Spot orders")
    venue.add_argument("--testnet", action="store_true")
    run.add_argument("--resume", action="store_true",
                     help="explicitly resume a restart in recovery-only mode")
    run.add_argument("--order-budget", default="100")
    run.add_argument("--loss-limit", default="10")
    run.add_argument("--max-position-cost", default="100")
    run.add_argument("--poll-seconds", type=int, default=60)
    run.add_argument("--expected-uid", type=int,
        help="required for production; must match read-only preflight UID")
    preflight = sub.add_parser("preflight", help="read-only API account and symbol check")
    preflight.add_argument("--symbol", default="BTCUSDT")
    preflight_venue = preflight.add_mutually_exclusive_group(required=True)
    preflight_venue.add_argument("--live", action="store_true")
    preflight_venue.add_argument("--testnet", action="store_true")
    preflight.add_argument("--expected-uid", type=int)
    for command, name in (("stop", "stop.request"), ("resume-buys", "resume.request")):
        control = sub.add_parser(command)
        control.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command in ("stop", "resume-buys"):
        try:
            _control(args.state_dir, "stop.request" if args.command == "stop"
                     else "resume.request")
        except RuntimeError as exc:
            parser.exit(2, f"Autonomous Spot control blocked: {type(exc).__name__}\n")
        return 0
    if args.command == "run" and args.live and (
            args.expected_uid is None or args.expected_uid <= 0):
        parser.error("production run requires --expected-uid from read-only preflight")
    if args.expected_uid is not None and args.expected_uid <= 0:
        parser.error("expected UID must be positive")
    if args.command == "run" and not 30 <= args.poll_seconds <= 300:
        parser.error("poll seconds must be between 30 and 300")
    try:
        return _preflight(args) if args.command == "preflight" else _service(args)
    except (RuntimeError, ValueError, InvalidOperation) as exc:
        parser.exit(2, f"Autonomous Spot startup blocked: {type(exc).__name__}\n")


if __name__ == "__main__":
    raise SystemExit(main())
