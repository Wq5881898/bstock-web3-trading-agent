from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mcp_bridge import (load_mcp_account_binding, load_mcp_read_request,
    write_mcp_account_binding)
from .mcp_host_receipt import (load_json_document, verify_spot_host_receipt,
    write_verified_receipt)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a sanitized receipt returned by the authorized Codex MCP host")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--binding-file", type=Path,
        default=Path("runtime") / "mcp" / "account-binding.json")
    parser.add_argument(
        "--output", type=Path,
        default=Path("runtime") / "mcp" / "latest-verified-snapshot.json")
    parser.add_argument("--enroll-account", action="store_true",
        help="Explicitly pin the first sanitized Agentic account fingerprint")
    args = parser.parse_args()
    request = load_mcp_read_request(args.request)
    binding = load_mcp_account_binding(args.binding_file)
    payload = load_json_document(args.receipt, "MCP host receipt")
    verified = verify_spot_host_receipt(
        request, binding, payload, allow_enroll=args.enroll_account)
    if verified.enrolled_now:
        write_mcp_account_binding(verified.binding, args.binding_file)
    write_verified_receipt(verified, args.output)
    print(json.dumps({"success": True, "verifiedSnapshot": str(
        args.output.resolve()), "summary": verified.summary()},
        ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
