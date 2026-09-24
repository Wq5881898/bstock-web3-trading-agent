"""Atomic local handoff of one sanitized MCP host read into a strategy cycle.

Codex still owns every MCP call and the account identity check.  This command
only consumes the host's sanitized JSON on stdin, verifies it against the
existing read request, persists it, and runs one local strategy cycle.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .mcp_bridge import load_mcp_account_binding, load_mcp_read_request
from .mcp_cycle import McpCyclePaths, run_cycle
from .mcp_host_receipt import (verify_spot_host_receipt,
                               write_verified_receipt)


def import_and_cycle(payload: dict, *, request_path: Path,
                     binding_path: Path, verified_path: Path,
                     runtime_dir: Path, now_ms: int | None = None,
                     catalog=None, feed=None, strategy=None) -> dict:
    """Fail closed on any identity, pagination, time, ledger or signal issue."""
    current = now_ms if now_ms is not None else int(
        datetime.now(timezone.utc).timestamp() * 1000)
    if type(current) is not int or current < 0:
        raise ValueError("Invalid MCP host cycle time")
    binding = load_mcp_account_binding(binding_path)
    if binding.fingerprint is None:
        raise ValueError("Existing Agentic account must already be enrolled")
    request = load_mcp_read_request(request_path)
    receipt = verify_spot_host_receipt(
        request, binding, payload,
        now=datetime.fromtimestamp(current / 1000, timezone.utc))
    if receipt.enrolled_now:
        raise ValueError("MCP host cycle cannot enroll a new account")
    write_verified_receipt(receipt, verified_path)
    return run_cycle(McpCyclePaths(
        binding=binding_path, receipt=verified_path,
        equity_guard=runtime_dir / "live/btcusdt-equity-risk.json",
        fill_ledger=runtime_dir / "live/btcusdt-fills.json",
        session=runtime_dir / "live/btcusdt-strategy-session.json",
        candidates=runtime_dir / "live/candidates"),
        now_ms=now_ms, catalog=catalog, feed=feed, strategy=strategy)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify sanitized Binance MCP JSON from stdin and run one local strategy cycle; never submit orders")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--binding-file", type=Path,
        default=Path("runtime/desktop/mcp/account-binding.json"))
    parser.add_argument("--verified-snapshot", type=Path,
        default=Path("runtime/desktop/mcp/btcusdt-verified-snapshot.json"))
    parser.add_argument("--runtime-dir", type=Path,
        default=Path("runtime/desktop/mcp"))
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        parser.error("Sanitized MCP host JSON is required on stdin")
    result = import_and_cycle(
        payload, request_path=args.request,
        binding_path=args.binding_file,
        verified_path=args.verified_snapshot,
        runtime_dir=args.runtime_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
