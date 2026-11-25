import pytest


@pytest.fixture(autouse=True)
def _isolate_from_this_machine(tmp_path, monkeypatch):
    """Tests never see the real API keys (no live calls, no cost) or the real
    brand/ logo in the project folder. A test that needs either sets it itself."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("scorm_scorcher.cli.BRAND_DIR", tmp_path / "no-brand-dir")
