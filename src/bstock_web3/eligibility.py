from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from .catalog import BStockAsset


@dataclass(frozen=True)
class EligibilitySnapshot:
    effective_from_utc: datetime
    effective_to_utc: datetime
    contracts: dict[str, str]

    @classmethod
    def load(cls, path: str | Path) -> "EligibilitySnapshot":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        contracts = {str(row["symbol"]).upper(): str(row["contract_address"]).lower()
                     for row in payload["assets"]}
        return cls(_parse(payload["effective_from_utc"]),
                   _parse(payload["effective_to_utc"]), contracts)

    def require_current(self, asset: BStockAsset, *, now: datetime | None = None) -> None:
        current = _utc(now or datetime.now(timezone.utc))
        if not self.effective_from_utc <= current <= self.effective_to_utc:
            raise RuntimeError("eligible bStock 名单已过期或尚未生效")
        if self.contracts.get(asset.symbol) != asset.contract_address.lower():
            raise RuntimeError(f"{asset.symbol} 不在当前 eligible 名单中，或合约地址不匹配")


def _parse(value: str) -> datetime:
    return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

