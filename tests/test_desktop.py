from pathlib import Path
import pytest

from bstock_web3.desktop import desktop_state_file


def test_desktop_state_file_uses_explicit_runtime_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BINANCE_AGENT_RUNTIME_DIR", str(tmp_path))

    assert desktop_state_file(" NVDAB ", "paper") == tmp_path / "nvdab_paper.json"


def test_desktop_state_file_does_not_depend_on_working_directory(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BINANCE_AGENT_RUNTIME_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    state_file = desktop_state_file("NVDAB", "quote")

    assert state_file.name == "nvdab_quote.json"
    assert state_file.parent != tmp_path / "runtime"


@pytest.mark.parametrize("symbol,mode", [("../other", "paper"), ("", "paper"), ("NVDA/B", "quote"), ("NVDAB", "../live")])
def test_desktop_rejects_unsafe_state_names(symbol, mode):
    with pytest.raises(ValueError):
        desktop_state_file(symbol, mode)
