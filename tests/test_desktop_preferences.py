from dataclasses import asdict, replace
import json
import pytest

from bstock_web3.desktop_preferences import DesktopPreferences, load_preferences, save_preferences


def test_roundtrip_and_isolation(tmp_path):
    path = tmp_path / "settings" / "preferences.json"
    settings = replace(DesktopPreferences(), symbol="BTC", order_size_usdc="50.25", paper_entry_cooldown=0)
    save_preferences(path, settings)
    assert load_preferences(path) == settings
    assert set(json.loads(path.read_text())) == set(asdict(settings))
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("changes", [
    {"version": True}, {"version": 3}, {"mode": "live-confirmed"},
    {"symbol": "../BTC"}, {"symbol": None}, {"order_size_usdc": "NaN"},
    {"order_size_usdc": "Infinity"}, {"order_size_usdc": "1.001"},
    {"paper_daily_loss_limit": True}, {"paper_daily_loss_limit": "0"},
    {"paper_position_cap": "50"}, {"paper_max_daily_entries": True},
    {"paper_max_loss_streak": 0}, {"paper_entry_cooldown": -1},
    {"paper_entry_cooldown": 100001},
])
def test_invalid_values_rejected(changes):
    with pytest.raises(ValueError):
        replace(DesktopPreferences(), **changes)


@pytest.mark.parametrize("raw", ['{}', '[]', '{', '{"version":1,"version":1}',
    'x' * 8193, '{"auto_start":true}', '\ud800'])
def test_bad_files_unchanged(tmp_path, raw):
    path = tmp_path / "preferences.json"
    encoded = raw.encode("utf-8", errors="surrogatepass")
    path.write_bytes(encoded)
    with pytest.raises(ValueError):
        load_preferences(path)
    assert path.read_bytes() == encoded


def test_failed_replace_preserves_prior_settings(monkeypatch, tmp_path):
    path = tmp_path / "preferences.json"
    save_preferences(path, DesktopPreferences())
    original = path.read_bytes()
    def fail(*args):
        raise OSError("injected disk failure")
    monkeypatch.setattr("bstock_web3.desktop_preferences.os.replace", fail)
    with pytest.raises(OSError):
        save_preferences(path, replace(DesktopPreferences(), symbol="BTC"))
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
