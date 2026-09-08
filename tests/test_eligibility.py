from datetime import datetime, timezone
import json

import pytest

from bstock_web3.catalog import BStockAsset
from bstock_web3.eligibility import EligibilitySnapshot


ASSET = BStockAsset("NVDA", "NVDAB", "0xAbC", "56", "NVDABUSDT", "1")


def test_eligibility_checks_time_and_contract(tmp_path):
    path = tmp_path / "eligible.json"
    path.write_text(json.dumps({
        "effective_from_utc": "2026-09-01T00:00:00Z",
        "effective_to_utc": "2026-09-30T23:59:59Z",
        "assets": [{"symbol": "NVDAB", "contract_address": "0xabc"}],
    }), encoding="utf-8")
    snapshot = EligibilitySnapshot.load(path)
    snapshot.require_current(ASSET, now=datetime(2026, 9, 7, tzinfo=timezone.utc))
    with pytest.raises(RuntimeError, match="过期"):
        snapshot.require_current(ASSET, now=datetime(2026, 10, 1, tzinfo=timezone.utc))

