"""CLI for one-shot read-only Agent OS account verification."""
from __future__ import annotations

import argparse
import json
import webbrowser

from .mcp_account import PROJECT_CLIENT_ID, read_spot_account_once


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Authorize Binance Agent OS and read one Spot account snapshot"
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--client-id", default=PROJECT_CLIENT_ID)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--no-browser", action="store_true",
                        help="print the authorization URL without opening a browser")
    args = parser.parse_args()

    def announce(url):
        print("Open this Binance authorization URL:")
        print(url)

    try:
        summary = read_spot_account_once(
            args.symbol.strip().upper(), client_id=args.client_id,
            announce_url=announce,
            browser_open=(lambda _url: None) if args.no_browser else webbrowser.open,
            timeout_seconds=args.timeout_seconds,
        )
    except ValueError as exc:
        print(json.dumps({"success":False, "error":str(exc)},
                         ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"success":True, "readOnly":True,
                      "account":summary.to_dict()},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
