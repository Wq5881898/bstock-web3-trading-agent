# Demo Guide

This demo is designed to show the agent without risking funds. Use `paper` first; the
live-confirmed path should only be shown after independent wallet and eligibility checks.

## 1. Verify the build

```powershell
.venv\Scripts\python -m pytest
```

Expected result for v1.0.2: `18 passed`.

## 2. Show a live local signal

```powershell
bstock-engine --symbol NVDAB --mode paper --amount 20 --once
```

The JSON output includes the resolved bStock contract, mode, action, reason, completed
signal-bar timestamp, 5m trend spread and expected edge. No wallet call occurs in paper
mode.

## 3. Show the desktop monitor

```powershell
bstock-desktop
```

Select `paper`, keep the default 20 USDC size and start monitoring. The monitor consumes
only completed candles and suppresses duplicate evaluation of the same 1m signal bar.

## 4. Show historical data and replay

```powershell
bstock-history --symbol NVDAB --days 3
bstock-backtest --data <generated-klines_1m.parquet>
```

The history builder resumes partial downloads, creates 1m and 5m bars, records completeness
and writes SHA-256 hashes in its manifest.

## 5. Explain the guarded execution path

For judging, show the command help or code path without confirming a real transaction:

```powershell
bstock-engine --help
```

The live path verifies market status, eligibility, balance, quote age and round-trip cost;
then it displays a one-time confirmation code. After submission, the order ID is saved
before polling so a timeout or restart cannot silently create a duplicate order.

