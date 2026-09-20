from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mcp_bridge import build_mcp_spot_read_request, write_mcp_read_request


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Export a credential-free read request for the existing "
                     "Codex Binance Agent OS MCP connection")
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--max-age-seconds", type=int, default=300)
    parser.add_argument(
        "--output", type=Path,
        default=Path("runtime") / "mcp" / "latest-read-request.json",
    )
    args = parser.parse_args()
    request = build_mcp_spot_read_request(
        args.symbol, max_age_seconds=args.max_age_seconds)
    write_mcp_read_request(request, args.output)
    print(json.dumps({
        "success": True,
        "requestFile": str(args.output.resolve()),
        "request": request.to_dict(),
        "message": (
            "本命令没有登录Binance或调用MCP。请让已授权的Codex宿主读取该请求。 "
            "This command did not log in or call MCP; hand the request to the "
            "already-authorized Codex host."
        ),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
