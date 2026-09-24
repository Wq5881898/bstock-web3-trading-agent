"""Durable public-Spot strategy observer; contains no order transport."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import time

from .catalog import BinanceExchangeSpotCatalogClient
from .market_data import BStockMultiTimeframeFeed
from .mcp_bridge import load_mcp_account_binding
from .mcp_host_receipt import load_verified_receipt
from .strategy import MtfEmaConfig, MtfEmaStrategy, PositionView, SignalDecision


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, allow_nan=False,
                  indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class SpotObserverConfig:
    symbol: str = "BTCUSDT"
    strategy: MtfEmaConfig = MtfEmaConfig()
    state_path: Path = Path("runtime/mcp/spot-observer-state.json")
    output_path: Path = Path("runtime/mcp/latest-spot-signal.json")
    action_output_path: Path = Path(
        "runtime/mcp/latest-actionable-spot-signal.json")


class SpotSignalObserver:
    VERSION = 1

    def __init__(self, config: SpotObserverConfig, *, catalog=None, feed=None,
                 strategy=None):
        if not isinstance(config, SpotObserverConfig):
            raise ValueError("Invalid Spot observer configuration")
        self.config = config
        self.symbol = config.symbol.strip().upper()
        self.catalog = catalog or BinanceExchangeSpotCatalogClient()
        self.feed = feed or BStockMultiTimeframeFeed()
        self.strategy = strategy or MtfEmaStrategy(config.strategy)
        self.strategy_digest = _digest(asdict(config.strategy))
        self.asset = None
        self.last_signal_bar: str | None = None
        if config.state_path.exists():
            self._load()

    def evaluate_once(self, position: PositionView, *,
                      position_observed_at: str | None = None,
                      now=None) -> dict:
        if not isinstance(position, PositionView):
            raise ValueError("Invalid Spot observer position")
        asset = self.asset or self.catalog.resolve(self.symbol)
        self.asset = asset
        status = self.catalog.market_status(asset)
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if not status.open_state or status.reason_code != "TRADING":
            signal = SignalDecision(
                "hold", f"market_unavailable:{status.reason_code}", None, None,
                strategy_id="mtf", strategy_params=asdict(self.config.strategy))
            return self._write_event(
                asset.spot_symbol, signal, observed, duplicate=False,
                position_observed_at=position_observed_at)
        snapshot = self.feed.fetch(asset, now=observed)
        signal = self.strategy.evaluate(snapshot, position)
        signal = replace(signal, strategy_id="mtf",
                         strategy_params=asdict(self.config.strategy))
        duplicate = False
        if signal.signal_bar_time and self.last_signal_bar:
            duplicate = (datetime.fromisoformat(signal.signal_bar_time)
                         <= datetime.fromisoformat(self.last_signal_bar))
        if duplicate:
            signal = replace(signal, action="hold",
                             reason="signal_bar_already_processed")
        elif signal.signal_bar_time and (position_observed_at is None or
                self._position_fresh(snapshot.observed_at,
                                     position_observed_at)):
            self.last_signal_bar = signal.signal_bar_time
            self._persist()
        return self._write_event(
            asset.spot_symbol, signal, snapshot.observed_at,
            duplicate=duplicate, position_observed_at=position_observed_at)

    @staticmethod
    def _position_fresh(observed: datetime, position_observed_at: str) -> bool:
        position_time = datetime.fromisoformat(
            position_observed_at.replace("Z", "+00:00"))
        if position_time.tzinfo is None:
            raise ValueError("Position snapshot requires timezone")
        return 0 <= (observed - position_time).total_seconds() <= 15

    def _write_event(self, symbol: str, signal: SignalDecision,
                     observed: datetime, *, duplicate: bool,
                     position_observed_at: str | None) -> dict:
        position_fresh = None
        if position_observed_at is not None:
            position_fresh = self._position_fresh(
                observed, position_observed_at)
        payload = {
            "schema_version": "1.0",
            "mode": "OBSERVE_ONLY",
            "transport": None,
            "execution_eligible": False,
            "symbol": symbol,
            "observed_at": observed.isoformat(),
            "position_snapshot_observed_at": position_observed_at,
            "position_snapshot_fresh": position_fresh,
            "duplicate_bar": duplicate,
            "signal": asdict(signal),
        }
        _atomic_json(self.config.output_path, payload)
        if position_fresh is not True:
            suppressed = dict(payload)
            suppressed["signal"] = dict(payload["signal"], action="hold",
                                        reason="position_snapshot_not_fresh")
            _atomic_json(self.config.action_output_path, suppressed)
        elif not duplicate and signal.action in {"buy", "sell"}:
            _atomic_json(self.config.action_output_path, payload)
        return payload

    def invalidate_action_output(self, reason: str) -> None:
        """Replace a previous action when account evidence cannot be loaded."""
        if reason != "position_snapshot_unavailable":
            raise ValueError("Invalid action invalidation reason")
        signal = SignalDecision("hold", reason, None, None,
                                strategy_id="mtf",
                                strategy_params=asdict(self.config.strategy))
        _atomic_json(self.config.action_output_path, {
            "schema_version": "1.0", "mode": "OBSERVE_ONLY",
            "transport": None, "execution_eligible": False,
            "symbol": self.symbol,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "position_snapshot_observed_at": None,
            "position_snapshot_fresh": False,
            "duplicate_bar": False, "signal": asdict(signal),
        })

    def _persist(self):
        _atomic_json(self.config.state_path, {
            "version": self.VERSION, "symbol": self.symbol,
            "strategy_id": "mtf", "strategy_digest": self.strategy_digest,
            "last_signal_bar": self.last_signal_bar,
        })

    def _load(self):
        try:
            payload = json.loads(self.config.state_path.read_text("utf-8"))
            expected = {"version", "symbol", "strategy_id",
                        "strategy_digest", "last_signal_bar"}
            if (not isinstance(payload, dict) or set(payload) != expected
                    or payload["version"] != self.VERSION
                    or payload["symbol"] != self.symbol
                    or payload["strategy_id"] != "mtf"
                    or payload["strategy_digest"] != self.strategy_digest
                    or (payload["last_signal_bar"] is not None
                        and datetime.fromisoformat(
                            payload["last_signal_bar"]).tzinfo is None)):
                raise ValueError
            self.last_signal_bar = payload["last_signal_bar"]
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError,
                ValueError):
            raise ValueError("Invalid Spot observer state") from None


def _position_from_verified(snapshot_path: Path, binding_path: Path,
                            symbol: str) -> tuple[PositionView, str]:
    binding = load_mcp_account_binding(binding_path)
    receipt = load_verified_receipt(snapshot_path, binding)
    if receipt.symbol != symbol:
        raise ValueError("Verified account snapshot symbol mismatch")
    quantity, cost = receipt.tradable_position()
    entry = cost / quantity if quantity > 0 and cost > 0 else Decimal("0")
    return PositionView(float(quantity), float(entry)), receipt.observed_at


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Observe a Binance exchange Spot strategy without orders")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--state-file", type=Path,
        default=Path("runtime/mcp/spot-observer-state.json"))
    parser.add_argument("--output", type=Path,
        default=Path("runtime/mcp/latest-spot-signal.json"))
    parser.add_argument("--action-output", type=Path,
        default=Path("runtime/mcp/latest-actionable-spot-signal.json"))
    parser.add_argument("--verified-snapshot", type=Path)
    parser.add_argument("--binding-file", type=Path,
        default=Path("runtime/desktop/mcp/account-binding.json"))
    parser.add_argument("--position-quantity", default="0")
    parser.add_argument("--entry-price", default="0")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol.strip().upper()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    if not args.verified_snapshot:
        quantity, entry = (Decimal(args.position_quantity),
                           Decimal(args.entry_price))
        if (not quantity.is_finite() or not entry.is_finite()
                or quantity < 0 or entry < 0
                or (quantity == 0) != (entry == 0)):
            parser.error("invalid position")
        static_position = PositionView(float(quantity), float(entry))
    observer = SpotSignalObserver(SpotObserverConfig(
        symbol=symbol, state_path=args.state_file, output_path=args.output,
        action_output_path=args.action_output))
    while True:
        try:
            if args.verified_snapshot:
                position, receipt_time = _position_from_verified(
                    args.verified_snapshot, args.binding_file, symbol)
            else:
                position, receipt_time = static_position, None
            payload = observer.evaluate_once(
                position, position_observed_at=receipt_time)
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        except KeyboardInterrupt:
            return 130
        except Exception as exc:
            observer.invalidate_action_output("position_snapshot_unavailable")
            print(json.dumps({"success": False, "error": str(exc)},
                             ensure_ascii=False), flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
