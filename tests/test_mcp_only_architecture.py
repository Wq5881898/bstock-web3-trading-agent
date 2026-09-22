from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "bstock_web3"


def test_private_spot_api_execution_modules_are_absent():
    forbidden_modules = {
        "auto_cli.py",
        "autonomous_runner.py",
        "autonomous_service.py",
        "autonomous_session.py",
        "binance_spot_api.py",
        "spot_api_reconcile.py",
        "spot_signal_source.py",
        "unattended_spot.py",
    }

    assert forbidden_modules.isdisjoint(path.name for path in SOURCE.glob("*.py"))


def test_no_api_key_or_private_order_entrypoint_in_executable_code():
    executable_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(SOURCE.glob("*.py"))
    )
    project_config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "BINANCE_API_KEY" not in executable_text
    assert "BINANCE_API_SECRET" not in executable_text
    assert "/api/v3/order" not in executable_text
    assert "bstock-auto" not in project_config


def test_product_documents_name_the_mcp_only_baseline():
    baseline = (ROOT / "docs" / "AUTONOMOUS_TRADING_PRODUCT_BASELINE.md").read_text(
        encoding="utf-8"
    )
    closeout = (ROOT / "docs" / "CLOSEOUT.md").read_text(encoding="utf-8")

    required = ("MCP-AUTO-010", "existing Agentic sub-account")
    for text in (baseline, closeout):
        assert all(item in text for item in required)
        assert "operator explicitly approved a separate" not in text
