import pytest

from bstock_web3.auto_cli import main


def test_stop_control_is_idempotent_and_has_no_network(tmp_path):
    (tmp_path / "session.json").write_text("{}", encoding="utf-8")
    assert main(["stop", "--state-dir", str(tmp_path)]) == 0
    assert main(["stop", "--state-dir", str(tmp_path)]) == 0
    assert (tmp_path / "stop.request").read_text(encoding="ascii") == "requested\n"


def test_missing_session_cannot_create_control_file(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["resume-buys", "--state-dir", str(tmp_path)])
    assert error.value.code == 2
    assert not (tmp_path / "resume.request").exists()


def test_production_run_without_credentials_is_blocked_before_network(
        tmp_path, monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    with pytest.raises(SystemExit) as error:
        main(["run", "--live", "--state-dir", str(tmp_path)])
    assert error.value.code == 2
    assert not (tmp_path / "session.json").exists()
