import pytest


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch, tmp_path):
    # Never read the developer's .env or make an authenticated live request.
    monkeypatch.setenv("COINDCX_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("COINDCX_API_KEY", "")
    monkeypatch.setenv("COINDCX_SECRET_KEY", "")
    monkeypatch.setenv("COINDCX_SANDBOX_MODE", "false")
    monkeypatch.delenv("COINDCX_BASE_URL", raising=False)
    monkeypatch.delenv("COINDCX_PUBLIC_BASE_URL", raising=False)
