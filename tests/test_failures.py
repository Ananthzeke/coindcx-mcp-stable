import asyncio
import json

import httpx
import pytest

from coindcx_mcp.client import CoinDCXClient, CoinDCXError
from coindcx_mcp.server import call_tool

P = "B-BTC_USDT"


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_ticker", {"extra": True}),
        ("get_trades", {"pair": P, "limit": 501}),
        ("get_candles", {"pair": P, "interval": "5m"}),
        ("get_candles", {"pair": P, "interval": "1m", "start_time": 2, "end_time": 1}),
        ("get_market_details", {"pair": " "}),
        ("get_active_orders", {}),
        ("get_order_history", {"limit": 501}),
        ("get_order_status", {"order_id": "uuid"}),
        ("cancel_order", {"order_id": "0"}),
        (
            "create_order",
            {"side": "buy", "market": "BTCUSDT", "order_type": "limit_order", "total_quantity": 1},
        ),
        (
            "create_order",
            {
                "side": "buy",
                "market": "BTCUSDT",
                "order_type": "market_order",
                "quantity": 1,
                "total_quantity": 1,
            },
        ),
        ("create_order", {"side": "buy", "market": "BTCUSDT", "order_type": "market_order"}),
        (
            "create_order",
            {
                "side": "buy",
                "market": "BTCUSDT",
                "order_type": "market_order",
                "quantity": float("nan"),
            },
        ),
        (
            "create_futures_order",
            {
                "pair": P,
                "side": "buy",
                "order_type": "market_order",
                "total_quantity": 1,
                "time_in_force": "good_till_cancel",
            },
        ),
        (
            "create_futures_order",
            {
                "pair": P,
                "side": "buy",
                "order_type": "stop_limit",
                "price": 60000,
                "total_quantity": 1,
            },
        ),
        (
            "create_futures_order",
            {
                "pair": P,
                "side": "buy",
                "order_type": "market_order",
                "total_quantity": 1,
                "margin_currency": "INR",
                "position_margin_type": "crossed",
            },
        ),
        (
            "create_futures_order",
            {"pair": P, "side": "buy", "order_type": "market_order", "total_quantity": -1},
        ),
        ("get_futures_instrument_orderbook", {"pair": P + "?inject=1"}),
        ("get_futures_instrument_orderbook", {"pair": P, "depth": 100}),
        (
            "get_futures_instrument_candlesticks",
            {"pair": P, "resolution": "1", "from_time": 2, "to_time": 1},
        ),
        ("create_futures_tpsl", {"position_id": "test"}),
        (
            "create_futures_tpsl",
            {
                "position_id": "test",
                "take_profit": {"stop_price": "2", "order_type": "take_profit_limit"},
            },
        ),
        (
            "create_futures_tpsl",
            {"position_id": "test", "stop_loss": {"stop_price": "2", "order_type": "stop_limit"}},
        ),
        (
            "create_futures_tpsl",
            {"position_id": "test", "stop_loss": {"stop_price": "0", "order_type": "stop_market"}},
        ),
        ("update_futures_position_leverage", {"leverage": "5"}),
        ("update_futures_position_leverage", {"leverage": "5", "pair": P, "position_id": "test"}),
        ("get_futures_positions_by_filter", {}),
        ("list_futures_positions", {"margin_currencies": []}),
        ("transfer_futures_wallet", {"transfer_type": "deposit", "amount": float("inf")}),
        ("remove_futures_margin", {"position_id": "test", "amount": 0}),
        ("get_futures_trades", {"pair": P, "from_date": "2026-02-30", "to_date": "2026-03-01"}),
    ],
)
def test_invalid_inputs_never_send_request(name, args):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    api = CoinDCXClient("key", "secret", transport=httpx.MockTransport(handler))
    try:
        result = asyncio.run(call_tool(name, args, api_client=api))
        assert result.is_error
        assert not requests
    finally:
        api.close()


def test_public_tool_works_without_credentials_but_private_tool_fails():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[{"market": "BTCUSDT"}])

    api = CoinDCXClient(transport=httpx.MockTransport(handler))
    try:
        assert not asyncio.run(call_tool("get_ticker", {}, api_client=api)).is_error
        assert asyncio.run(call_tool("get_balances", {}, api_client=api)).is_error
        assert len(requests) == 1
    finally:
        api.close()


@pytest.mark.parametrize(
    "response_data",
    [
        {"error": "rejected"},
        {"status": "error", "code": 400},
        {"take_profit": {"success": False, "error": "already exists"}, "stop_loss": {"id": "ok"}},
    ],
)
def test_exchange_error_in_http_200_sets_mcp_error(response_data):
    api = CoinDCXClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_data))
    )
    try:
        result = asyncio.run(call_tool("get_ticker", {}, api_client=api))
        assert result.is_error
        assert json.loads(result.content[0].text) == response_data
    finally:
        api.close()


@pytest.mark.parametrize("failure", ["timeout", "500", "429", "json"])
def test_post_failures_are_not_retried(failure, monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if failure == "json":
            return httpx.Response(200, text="not json")
        return httpx.Response(int(failure), json={"message": "failure"})

    api = CoinDCXClient("key", "secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CoinDCXError) as error:
            api.create_order("buy", "market_order", "BTCUSDT", total_quantity=1)
        assert len(requests) == 1
        if failure != "429":
            assert "outcome may be unknown" in str(error.value).lower()
    finally:
        api.close()


def test_get_retries_are_bounded_and_respect_retry_after(monkeypatch):
    requests, sleeps = [], []
    monkeypatch.setattr("coindcx_mcp.client.time.sleep", sleeps.append)

    def handler(request):
        requests.append(request)
        return httpx.Response(
            429, json={"message": "rate limited"}, headers={"Retry-After": "99999"}
        )

    api = CoinDCXClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CoinDCXError, match="HTTP 429"):
            api.get_ticker()
        assert len(requests) == 3
        assert sleeps == [2.0, 2.0]
    finally:
        api.close()


def test_error_messages_redact_credentials():
    api = CoinDCXClient(
        "test-api-key",
        "test-secret-key",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"message": "test-api-key test-secret-key"})
        ),
    )
    try:
        result = asyncio.run(call_tool("get_balances", {}, api_client=api))
        assert result.is_error
        assert "test-api-key" not in result.content[0].text
        assert "test-secret-key" not in result.content[0].text
    finally:
        api.close()
