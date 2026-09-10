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


@dataclass(frozen=True)
class DesktopPreferences:
    version: int = 2
    symbol: str = "NVDAB"
    mode: str = "paper"
    order_size_usdc: str = "100"
    paper_daily_loss_limit: str = "10"
    paper_position_cap: str = "100"
    paper_max_daily_entries: int = 20
    paper_max_loss_streak: int = 3
    paper_entry_cooldown: int = 60
    strategy_config: dict = field(default_factory=lambda: asdict(MtfEmaConfig()))

    def __post_init__(self):
        if type(self.version) is not int or self.version != 2:
            raise ValueError("Unsupported preferences version")
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
            if set(data) != set(asdict(DesktopPreferences())) - {"strategy_config"}:
                raise ValueError("Invalid legacy preferences fields")
            data = {**data, "version": 2, "strategy_config": asdict(MtfEmaConfig())}
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
