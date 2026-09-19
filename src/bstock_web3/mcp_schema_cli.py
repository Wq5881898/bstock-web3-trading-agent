"""CLI for one-shot, no-tool-call Agent OS schema acceptance."""
from __future__ import annotations

import argparse
import json
import webbrowser

from .mcp_account import PROJECT_CLIENT_ID
from .mcp_schema_acceptance import discover_confirmed_schema_once


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Authorize Binance Agent OS and validate MCP order schemas without "
        "reading account data or calling an order tool"))
    parser.add_argument("--client-id", default=PROJECT_CLIENT_ID)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    def announce(url):
        print("Open this Binance authorization URL (not persisted):")
        print(url)

    try:
        report = discover_confirmed_schema_once(client_id=args.client_id,
            announce_url=announce,
            browser_open=(lambda _url:None) if args.no_browser else webbrowser.open,
            timeout_seconds=args.timeout_seconds)
    except ValueError as exc:
        print(json.dumps({"success":False, "readAccount":False,
                          "orderCalled":False, "error":str(exc)},
                         ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"success":True, "readAccount":False,
                      "orderCalled":False, "sessionClosed":True,
                      "schema":report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
