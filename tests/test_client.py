import json

import httpx
import pytest

from coindcx_mcp.client import CoinDCXClient, CoinDCXError
from coindcx_mcp.config import Config


@pytest.mark.parametrize("pair", ["KC-BTC_USDT", "B-BTC_USDT", "I-BTC_INR"])
def test_exchange_prefix_is_preserved(pair):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    api = CoinDCXClient(transport=httpx.MockTransport(handler))
    try:
        api.get_order_book(pair)
        assert len(requests) == 1
        assert requests[0].url.params["pair"] == pair
    finally:
        api.close()


def test_symbol_is_resolved_from_market_details_without_inventing_prefix():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("markets_details"):
            return httpx.Response(200, json=[{"coindcx_name": "BTCUSDT", "pair": "KC-BTC_USDT"}])
        return httpx.Response(200, json=[])

    api = CoinDCXClient(transport=httpx.MockTransport(handler))
    try:
        assert api.get_trades("BTCUSDT") == []
        assert len(requests) == 2
        assert requests[1].url.params["pair"] == "KC-BTC_USDT"
        with pytest.raises(ValueError, match="not found"):
            api.get_trades("UNKNOWN")
    finally:
        api.close()


def test_empty_historical_candles_do_not_fall_back_to_recent_data():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    api = CoinDCXClient(transport=httpx.MockTransport(handler))
    try:
        assert api.get_candles("B-BTC_USDT", "1m", 0, 1000) == []
        assert len(requests) == 1
        assert requests[0].url.params["startTime"] == "0"
    finally:
        api.close()


def test_payload_is_not_mutated_and_quantity_alias_uses_documented_field(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    api = CoinDCXClient("key", "secret", transport=httpx.MockTransport(handler))
    try:
        body = {"id": "123"}
        api._make_authenticated_request("POST", "/exchange/v1/orders/status", body)
        assert body == {"id": "123"}
        api.create_order("buy", "market_order", "BTCUSDT", quantity=0.01)
        sent = json.loads(requests[1].content)
        assert sent["total_quantity"] == 0.01
        assert "quantity" not in sent
    finally:
        api.close()


def test_history_side_filter_is_local_and_range_validated():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[{"side": "buy"}, {"side": "sell"}])

    api = CoinDCXClient("key", "secret", transport=httpx.MockTransport(handler))
    try:
        assert api.get_order_history(side="buy") == [{"side": "buy"}]
        assert "side" not in json.loads(requests[0].content)
        with pytest.raises(ValueError):
            api.get_order_history(from_timestamp=2, to_timestamp=1)
        with pytest.raises(ValueError):
            api.get_futures_trades("B-BTC_USDT", "2026-10-02", "2026-10-01")
        assert len(requests) == 1
    finally:
        api.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://api.coindcx.com",
        "https://key:secret@api.coindcx.com",
        "https://api.coindcx.com/?x=1",
        "https://api.coindcx.com/path",
    ],
)
def test_invalid_base_urls_are_rejected(url):
    with pytest.raises(ValueError):
        CoinDCXClient(base_url=url)


def test_redirect_does_not_forward_authentication():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://other.example/"})

    api = CoinDCXClient("key", "secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CoinDCXError, match="307"):
            api.get_balances()
        assert len(requests) == 1
    finally:
        api.close()


def test_explicit_env_file_and_process_environment_precedence(monkeypatch, tmp_path):
    envfile = tmp_path / "config.env"
    envfile.write_text("COINDCX_API_KEY=file-key\nCOINDCX_SECRET_KEY=file-secret\n")
    monkeypatch.setenv("COINDCX_ENV_FILE", str(envfile))
    monkeypatch.setenv("COINDCX_API_KEY", "process-key")
    monkeypatch.delenv("COINDCX_SECRET_KEY")
    config = Config()
    assert config.api_key == "process-key"
    assert config.secret_key == "file-secret"
    assert config.validate()


def test_unused_sandbox_flag_cannot_silently_send_live_trades(monkeypatch):
    monkeypatch.setenv("COINDCX_SANDBOX_MODE", "true")
    with pytest.raises(ValueError, match="unsupported"):
        Config()
