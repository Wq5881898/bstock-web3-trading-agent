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
from .autonomous_session import (AutonomousSpotSession, SessionBinding,
    SessionPhase)
from .automation_policy import AutomationPolicy, AutomationPolicyConfig
from .binance_spot_api import (BinanceSpotApi, SpotApiCredentials,
    PRODUCTION_URL, TESTNET_URL)
from .execution_lock import ExecutionLock
from .execution_safety import ExecutionJournal
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
        _digest({key: str(value) for key, value in asdict(policy_config).items()}))
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
            base_asset=args.base, quote_asset=args.quote)
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
        else:
            raise RuntimeError("Session exists; restart requires explicit --resume in recovery mode")
        print(json.dumps({"event": "STARTED", "phase": session.phase.value,
            "symbol": args.symbol, "venue": "production" if args.live else "testnet",
            "account_ref": account_ref}, ensure_ascii=False), flush=True)
        stop_file, resume_file = directory / "stop.request", directory / "resume.request"
        while True:
            now_ms = int(time.time() * 1000)
            if stop_file.exists():
                session.request_stop()
            try:
                if session.phase == SessionPhase.STOPPING:
                    if runner.stop(now_ms=now_ms):
                        stop_file.unlink(missing_ok=True)
                        print('{"event":"STOPPED"}', flush=True)
                        return 0
                else:
                    if resume_file.exists() and session.phase == SessionPhase.BUY_PAUSED:
                        snapshot = reconciler.read(now_ms=now_ms)
                        allowed = session.resume(snapshot.evidence, now_ms=now_ms,
                            filled_order_ids=snapshot.filled_order_ids)
                        resume_file.unlink(missing_ok=True)
                        print(json.dumps({"event": "RESUME", "allowed": allowed}), flush=True)
                    result = runner.tick(now_ms=now_ms)
                    if result.outcome not in ("HOLD", "BLOCKED") or result.reasons:
                        print(json.dumps({"event": result.outcome,
                            "reasons": result.reasons, "order_status": result.order_status,
                            "phase": session.phase.value}), flush=True)
            except Exception as exc:
                # Never print a signed URL, server error body, API key or secret.
                print(json.dumps({"event": "READ_OR_EXECUTION_ERROR",
                    "error_type": type(exc).__name__,
                    "phase": session.phase.value}), flush=True)
            time.sleep(args.poll_seconds)


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
    if not 30 <= args.poll_seconds <= 300:
        parser.error("poll seconds must be between 30 and 300")
    try:
        return _service(args)
    except (RuntimeError, ValueError, InvalidOperation) as exc:
        parser.exit(2, f"Autonomous Spot startup blocked: {type(exc).__name__}\n")


if __name__ == "__main__":
    raise SystemExit(main())
