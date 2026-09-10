from dataclasses import asdict, replace
from decimal import Decimal
import json

import pytest

from bstock_web3.desktop_preferences import DesktopPreferences, load_preferences, save_preferences
from bstock_web3.engine import BStockEngine, BStockEngineConfig
from bstock_web3.strategy import MtfEmaConfig, SignalDecision


def test_legacy_preferences_migrate_in_memory_only(tmp_path):
    path = tmp_path / "preferences.json"
    data = asdict(DesktopPreferences())
    data.pop("strategy_config")
    data.pop("strategy_kind")
    data.pop("median_config")
    data.pop("range_config")
    data["version"] = 1
    original = json.dumps(data)
    path.write_text(original)
    loaded = load_preferences(path)
    assert loaded.version == 4
    assert loaded.strategy_config == asdict(MtfEmaConfig())
    assert path.read_text() == original
    save_preferences(path, loaded)
    assert json.loads(path.read_text())["version"] == 4


@pytest.mark.parametrize("changes", [
    {"entry_short": 21}, {"trend_long": 201}, {"stop_loss": float("nan")},
    {"min_expected_edge": .0000001}, {"atr_period": True}, {"atr_period": 1},
])
def test_preferences_reject_bad_strategy(changes):
    with pytest.raises(ValueError):
        DesktopPreferences(strategy_config={**asdict(MtfEmaConfig()), **changes})


def test_strategy_parameters_reach_engine_and_lock_open_position(tmp_path):
    strategy = replace(MtfEmaConfig(), entry_short=5, entry_long=13, stop_loss=.006)
    config = BStockEngineConfig(state_file=tmp_path / "paper.json", strategy_config=strategy)
    engine = BStockEngine(config)
    assert engine.strategy.config == strategy
    engine._paper_fill(SignalDecision("buy", "fixture", 100, None))
    original = config.state_file.read_bytes()
    restored = BStockEngine(config)
    assert restored.strategy.config == strategy
    assert restored.state.paper_strategy_config == asdict(strategy)
    with pytest.raises(RuntimeError, match="original strategy"):
        BStockEngine(replace(config, strategy_config=MtfEmaConfig()))
    assert config.state_file.read_bytes() == original
    restored.paper_control("pause")
    restored._paper_fill(SignalDecision("sell", "fixture", 100, None))
    changed = BStockEngine(replace(config, strategy_config=MtfEmaConfig()))
    assert changed.state.paper_buy_pause == "MANUAL"
    assert changed.state.paper_daily_entries == 1
    assert Decimal(changed.state.realized_pnl) < 0
    changed._save_state()
    assert changed.state.paper_strategy_config == asdict(MtfEmaConfig())


def test_legacy_held_state_allows_only_historical_default(tmp_path):
    config = BStockEngineConfig(state_file=tmp_path / "paper.json")
    engine = BStockEngine(config)
    engine._paper_fill(SignalDecision("buy", "fixture", 100, None))
    data = json.loads(config.state_file.read_text())
    data.pop("paper_strategy_config")
    original = json.dumps(data)
    config.state_file.write_text(original)
    BStockEngine(config)
    with pytest.raises(RuntimeError, match="original strategy"):
        BStockEngine(replace(config, strategy_config=replace(MtfEmaConfig(), stop_loss=.005)))
    assert config.state_file.read_text() == original


@pytest.mark.parametrize("mode", ["quote", "live-confirmed"])
def test_custom_settings_cannot_change_real_execution_path(mode):
    with pytest.raises(ValueError, match="paper-only"):
        BStockEngineConfig(mode=mode, strategy_config=replace(MtfEmaConfig(), entry_short=5))


def test_corrupt_strategy_state_is_not_overwritten(tmp_path):
    config = BStockEngineConfig(state_file=tmp_path / "paper.json")
    engine = BStockEngine(config)
    engine._save_state()
    data = json.loads(config.state_file.read_text())
    data["paper_strategy_config"] = {"stop_loss": .1}
    original = json.dumps(data)
    config.state_file.write_text(original)
    with pytest.raises(RuntimeError):
        BStockEngine(config)
    assert config.state_file.read_text() == original
