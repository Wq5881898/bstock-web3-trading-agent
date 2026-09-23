---
name: binance-spot-assistant
description: Handle user-initiated, single-action Binance Agentic Spot account checks and market buy/sell requests through an already-authorized Agent OS MCP connection. Not for unattended strategy execution, futures, or Web3 wallet trades.
---

# Binance Agentic Spot conversation

Use the existing authorized Binance Agent OS MCP host and its selected Agentic Spot sub-account. This skill is a workflow, not a new OAuth client or a source of trading permission. Do not create an account, request an API key, reuse credentials from another host, or fall back to REST or a wallet. If the connection or required permissions are unavailable, stop and explain the missing capability.

For a read request, fetch current MCP data, label its source and observation time, and distinguish Agentic-account data from public market data. Do not infer an account balance or order state from an old chat message.

For a single Spot trade:

1. Resolve the exact symbol, side, order type and sizing unit. A budget such as “用 50 USDT 买 BTC” means a `BTCUSDT` Spot market BUY budget of 50 USDT (`quoteOrderQty`), not 50 BTC or a guaranteed BTC quantity. Ask if the pair, account, amount or SELL quantity is ambiguous. Do not substitute a saved strategy default.
2. Read the selected Agentic Spot account, current balance, symbol status/filters, relevant open orders, current market depth/price and fee rules through the existing MCP tools. For a SELL or a request involving position/PnL, read sufficient fills to establish what can actually be sold or reported. Treat stale, incomplete or contradictory results as a stop, not a reason to guess.
3. Present a compact order preview: Agentic Spot account, symbol, BUY/SELL, MARKET/LIMIT, exact `quoteOrderQty` or base `quantity`, relevant balance and filters, estimated cost/fee, and the fact that a market fill price/quantity may differ. No trade has been placed at this point.
4. Wait for the user's explicit confirmation of **this exact displayed order**. A broad instruction to “continue”, prior consent, strategy signal, or Skill invocation is not order confirmation. Changed parameters require a new preview and confirmation. Respect any further MCP/Binance approval prompt; never bypass it.
5. Immediately before one submission, refresh any evidence that has become stale and verify the account, order parameters and filters again. Use a unique client order identifier where the available tool supports it. Submit once only through the authorized MCP tool. If the result is missing, times out, or is otherwise uncertain, do not submit again; look up the same order identity and report unresolved status honestly.
6. Verify order status, executed quantity, quote spent/received, fees and updated balance before saying “filled”. Separate partial fill, rejection, pending and unknown outcomes. Do not write UID, tokens, authorization codes, exact private balances or order IDs into public repository files.

This workflow does not run a K-line loop or make autonomous strategy decisions. News, sentiment and AI summaries may inform a user-facing explanation but cannot silently change an order or serve as a standalone trade trigger. If the user asks for continuous automatic trading, explain that it belongs to the separate Alpha2/strategy-runner design and requires its own execution approval and risk controls.

For this repository's verified constraints and status, consult `docs/ASSISTANT_MODE_CLOSEOUT.md` when available. The Binance Agentic MCP provider requires user confirmation before every trade, cancellation or internal transfer: <https://developers.binance.com/en/docs/agent-native/mcp-server/agentic>.
