from __future__ import annotations

import pytest

from bqe_reporting.auth import OAuthPKCE, token_record, validate_api_endpoint
from bqe_reporting.config import Settings, _load_dotenv


def test_readwrite_scope_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BQE_SCOPES", "readwrite:core offline_access")
    with pytest.raises(ValueError, match="forbidden"):
        Settings.from_env()


def test_pkce_authorization_url_contains_read_only_scope() -> None:
    pending = OAuthPKCE(Settings(client_id="public-client-id")).prepare()
    assert "read%3Acore" in pending.authorization_url
    assert "readwrite%3Acore" not in pending.authorization_url
    assert "code_challenge_method=S256" in pending.authorization_url
    assert pending.state
    assert len(pending.code_verifier) >= 43


def test_dotenv_loads_without_overriding_environment(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".env"
    path.write_text("BQE_CLIENT_ID=from-file\nBQE_MODE=LIVE\n", encoding="utf-8")
    monkeypatch.setenv("BQE_MODE", "MOCK")
    monkeypatch.delenv("BQE_CLIENT_ID", raising=False)
    _load_dotenv(path)
    assert __import__("os").environ["BQE_CLIENT_ID"] == "from-file"
    assert __import__("os").environ["BQE_MODE"] == "MOCK"


def test_live_native_app_rejects_offline_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BQE_MODE", "LIVE")
    monkeypatch.setenv("BQE_SCOPES", "read:core offline_access")
    with pytest.raises(ValueError, match="do not support offline_access"):
        Settings.from_env()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://company.bqecore.com/api",
        "https://bqecore.com/api",
        "https://company.bqecore.com:8443/api",
        "https://user@company.bqecore.com/api",
        "https://company.example.com/api",
    ],
)
def test_endpoint_allowlist_rejects_unsafe_values(endpoint: str) -> None:
    with pytest.raises(ValueError):
        validate_api_endpoint(endpoint)


def test_token_response_is_minimized_and_validated() -> None:
    record = token_record(
        {
            "access_token": "synthetic-token",
            "endpoint": "https://company.bqecore.com/api/",
            "expires_in": 60,
            "scope": "read:core",
            "token_type": "Bearer",
        }
    )
    assert record.endpoint == "https://company.bqecore.com/api"
    assert not record.expired


def test_token_response_rejects_write_scope_and_refresh_token() -> None:
    base = {
        "access_token": "synthetic-token",
        "endpoint": "https://company.bqecore.com/api",
        "scope": "read:core readwrite:core",
    }
    with pytest.raises(ValueError, match="readwrite"):
        token_record(base)
    base["scope"] = "read:core"
    base["refresh_token"] = "unexpected"
    with pytest.raises(ValueError, match="Unexpected refresh token"):
        token_record(base)
