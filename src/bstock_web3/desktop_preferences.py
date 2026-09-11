"""Non-secret desktop inputs only; never execution or account state."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import tempfile
from .strategy import MtfEmaConfig
from .median_ticks import TickMedianConfig
from .range_ticks import RangeStrategyConfig
from .range_guard import GuardedRangeMedianConfig
from .range_auto import RangeAutoConfig, RangeMedianAdaptiveConfig


@dataclass(frozen=True)
class DesktopPreferences:
    version: int = 6
    symbol: str = "NVDAB"
    mode: str = "paper"
    order_size_usdc: str = "100"
    paper_daily_loss_limit: str = "10"
    paper_position_cap: str = "100"
    paper_max_daily_entries: int = 20
    paper_max_loss_streak: int = 3
    paper_entry_cooldown: int = 60
    strategy_config: dict = field(default_factory=lambda: asdict(MtfEmaConfig()))
    strategy_kind: str = "mtf"
    median_config: dict = field(default_factory=lambda: asdict(TickMedianConfig()))
    range_config: dict = field(default_factory=lambda: asdict(RangeStrategyConfig()))
    guarded_range_config: dict = field(default_factory=lambda: asdict(GuardedRangeMedianConfig()))
    range_auto_config: dict = field(default_factory=lambda: asdict(RangeAutoConfig()))
    range_adaptive_config: dict = field(default_factory=lambda: asdict(RangeMedianAdaptiveConfig()))

    def __post_init__(self):
        if type(self.version) is not int or self.version != 6:
            raise ValueError("Unsupported preferences version")
        if self.strategy_kind not in ("mtf", "median", "range-ema", "range-median", "range-median-guarded",
                "range-ema-guarded", "range-auto", "range-guarded-auto", "range-median-adaptive") or (self.strategy_kind != "mtf" and self.mode != "paper"):
            raise ValueError("Invalid strategy or non-paper Median")
        if not isinstance(self.median_config, dict) or set(self.median_config) != set(asdict(TickMedianConfig())):
            raise ValueError("Invalid Median fields")
        TickMedianConfig(**self.median_config)
        for key in ("entry_deviation", "exit_deviation"):
            value = self.median_config[key]
            if abs(value * 1000000 - round(value * 1000000)) > 1e-7:
                raise ValueError("Median fractions support six decimal places")
        if not isinstance(self.range_config, dict) or set(self.range_config) != set(asdict(RangeStrategyConfig())):
            raise ValueError("Invalid Range fields")
        range_config = RangeStrategyConfig(**self.range_config)
        if ((self.strategy_kind == "range-ema" and range_config.family != "ema") or
                (self.strategy_kind == "range-median" and range_config.family != "median")):
            raise ValueError("Range strategy family mismatch")
        for key in ("entry_threshold", "exit_threshold", "deviation"):
            value = self.range_config[key]
            if abs(value * 1000000 - round(value * 1000000)) > 1e-7:
                raise ValueError("Range fractions support six decimal places")
        if not isinstance(self.guarded_range_config, dict) or set(self.guarded_range_config) != set(asdict(GuardedRangeMedianConfig())):
            raise ValueError("Invalid guarded Range fields")
        GuardedRangeMedianConfig(**self.guarded_range_config)
        if not isinstance(self.range_auto_config, dict) or set(self.range_auto_config) != set(asdict(RangeAutoConfig())):
            raise ValueError("Invalid Range Auto fields")
        auto_config = RangeAutoConfig(**self.range_auto_config)
        if not isinstance(self.range_adaptive_config, dict) or set(self.range_adaptive_config) != set(asdict(RangeMedianAdaptiveConfig())):
            raise ValueError("Invalid adaptive Range fields")
        adaptive_config = RangeMedianAdaptiveConfig(**self.range_adaptive_config)
        # Preferences are JSON-shaped so save/load equality does not depend on tuple encoding.
        object.__setattr__(self, "range_auto_config", json.loads(json.dumps(asdict(auto_config))))
        object.__setattr__(self, "range_adaptive_config", json.loads(json.dumps(asdict(adaptive_config))))
        if not isinstance(self.strategy_config, dict) or set(self.strategy_config) != set(asdict(MtfEmaConfig())):
            raise ValueError("Invalid strategy fields")
        strategy = MtfEmaConfig(**self.strategy_config)
        for key, value in self.strategy_config.items():
            if key in ("trend_short", "trend_long", "entry_short", "entry_long", "atr_period"):
                if value > 200:
                    raise ValueError("Desktop strategy periods must not exceed 200 closed bars")
            elif abs(value * 1000000 - round(value * 1000000)) > 1e-7:
                raise ValueError("Desktop strategy fractions support six decimal places")
        if self.mode != "paper" and strategy != MtfEmaConfig():
            raise ValueError("Custom strategy settings are paper-only")
        if not isinstance(self.symbol, str) or not re.fullmatch(r"[A-Z0-9]{1,32}", self.symbol):
            raise ValueError("Invalid symbol")
        if self.mode not in ("paper", "quote"):
            raise ValueError("Desktop mode must be paper or quote")
        for key, minimum in (("order_size_usdc", "1"), ("paper_daily_loss_limit", ".01"), ("paper_position_cap", "1")):
            raw = getattr(self, key)
            try:
                if not isinstance(raw, str):
                    raise ValueError("Amounts must be decimal strings")
                value = Decimal(raw)
                if not value.is_finite() or not Decimal(minimum) <= value <= 100000 or value != value.quantize(Decimal(".01")):
                    raise ValueError("Invalid amount or precision")
            except InvalidOperation as exc:
                raise ValueError("Invalid amount") from exc
        if self.mode == "paper" and Decimal(self.order_size_usdc) > Decimal(self.paper_position_cap):
            raise ValueError("Paper order budget exceeds position cost cap")
        for key in ("paper_max_daily_entries", "paper_max_loss_streak", "paper_entry_cooldown"):
            value = getattr(self, key)
            if type(value) is not int or not (0 if key == "paper_entry_cooldown" else 1) <= value <= 100000:
                raise ValueError("Invalid integer limit")


def load_preferences(path: Path) -> DesktopPreferences:
    with path.open("rb") as stream:
        raw = stream.read(8193)
    if len(raw) > 8192:
        raise ValueError("Preferences file too large")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate preferences key")
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique_pairs)
        # The exact previous schema receives the historical, unchanged strategy.
        if isinstance(data, dict) and type(data.get("version")) is int and data["version"] == 1:
            if set(data) != set(asdict(DesktopPreferences())) - {"strategy_config", "strategy_kind", "median_config", "range_config", "guarded_range_config", "range_auto_config", "range_adaptive_config"}:
                raise ValueError("Invalid legacy preferences fields")
            data = {**data, "version": 2, "strategy_config": asdict(MtfEmaConfig())}
        if isinstance(data, dict) and type(data.get("version")) is int and data["version"] == 2:
            if set(data) != set(asdict(DesktopPreferences())) - {"strategy_kind", "median_config", "range_config", "guarded_range_config", "range_auto_config", "range_adaptive_config"}:
                raise ValueError("Invalid v2 preferences fields")
            data = {**data, "version": 3, "strategy_kind": "mtf", "median_config": asdict(TickMedianConfig())}
        if isinstance(data, dict) and type(data.get("version")) is int and data["version"] == 3:
            if set(data) != set(asdict(DesktopPreferences())) - {"range_config", "guarded_range_config", "range_auto_config", "range_adaptive_config"}:
                raise ValueError("Invalid v3 preferences fields")
            data = {**data, "version": 4, "range_config": asdict(RangeStrategyConfig())}
        if isinstance(data, dict) and type(data.get("version")) is int and data["version"] == 4:
            if set(data) != set(asdict(DesktopPreferences())) - {"guarded_range_config", "range_auto_config", "range_adaptive_config"}:
                raise ValueError("Invalid v4 preferences fields")
            data = {**data, "version": 5, "guarded_range_config": asdict(GuardedRangeMedianConfig())}
        if isinstance(data, dict) and type(data.get("version")) is int and data["version"] == 5:
            if set(data) != set(asdict(DesktopPreferences())) - {"range_auto_config", "range_adaptive_config"}:
                raise ValueError("Invalid v5 preferences fields")
            data = {**data, "version": 6, "range_auto_config": asdict(RangeAutoConfig()),
                "range_adaptive_config": asdict(RangeMedianAdaptiveConfig())}
        if not isinstance(data, dict) or set(data) != set(asdict(DesktopPreferences())):
            raise ValueError("Invalid preferences fields")
        return DesktopPreferences(**data)
    except (UnicodeError, TypeError) as exc:
        raise ValueError("Invalid preferences file") from exc


def save_preferences(path: Path, preferences: DesktopPreferences) -> None:
    # Validate again before writing; never serialize arbitrary objects or secrets.
    payload = asdict(DesktopPreferences(**asdict(preferences)))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".preferences-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
