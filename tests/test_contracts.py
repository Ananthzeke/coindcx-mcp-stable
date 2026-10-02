"""Request contracts derived from https://docs.coindcx.com/ (2026-10-02)."""

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from coindcx_mcp.client import CoinDCXClient
from coindcx_mcp.server import TOOLS, call_tool

API = "api.coindcx.com"
PUBLIC = "public.coindcx.com"
F = "/exchange/v1/derivatives/futures"
P = "B-BTC_USDT"

# tool, input, HTTP method, host, path, signed JSON fields, query fields
CONTRACTS = [
    ("get_ticker", {}, "GET", API, "/exchange/ticker", None, {}),
    ("get_markets", {}, "GET", API, "/exchange/v1/markets", None, {}),
    ("get_market_details", {}, "GET", API, "/exchange/v1/markets_details", None, {}),
    (
        "get_trades",
        {"pair": P},
        "GET",
        API,
        "/market_data/trade_history",
        None,
        {"pair": P, "limit": "30"},
    ),
    ("get_order_book", {"pair": P}, "GET", API, "/market_data/orderbook", None, {"pair": P}),
    (
        "get_candles",
        {"pair": P, "interval": "1m", "start_time": 0, "end_time": 1000},
        "GET",
        API,
        "/market_data/candles",
        None,
        {"pair": P, "interval": "1m", "limit": "100", "startTime": "0", "endTime": "1000"},
    ),
    (
        "get_futures_active_instruments",
        {},
        "GET",
        API,
        F + "/data/active_instruments",
        None,
        {"margin_currency_short_name[]": "USDT"},
    ),
    (
        "get_futures_instrument_details",
        {"pair": P},
        "GET",
        API,
        F + "/data/instrument",
        None,
        {"pair": P, "margin_currency_short_name": "USDT"},
    ),
    (
        "get_futures_instrument_trades",
        {"pair": P},
        "GET",
        API,
        F + "/data/trades",
        None,
        {"pair": P},
    ),
    (
        "get_futures_instrument_orderbook",
        {"pair": P},
        "GET",
        PUBLIC,
        "/market_data/v3/orderbook/" + P + "-futures/50",
        None,
        {},
    ),
    (
        "get_futures_instrument_candlesticks",
        {"pair": P, "resolution": "60", "from_time": 0, "to_time": 3600},
        "GET",
        PUBLIC,
        "/market_data/candlesticks",
        None,
        {"pair": P, "from": "0", "to": "3600", "resolution": "60", "pcode": "f"},
    ),
    ("get_balances", {}, "POST", API, "/exchange/v1/users/balances", {}, {}),
    ("get_user_info", {}, "POST", API, "/exchange/v1/users/info", {}, {}),
    (
        "create_order",
        {
            "side": "buy",
            "order_type": "limit_order",
            "market": "BTCUSDT",
            "price": 60000,
            "total_quantity": 0.01,
            "client_order_id": "test-1",
        },
        "POST",
        API,
        "/exchange/v1/orders/create",
        {
            "side": "buy",
            "order_type": "limit_order",
            "market": "BTCUSDT",
            "price_per_unit": 60000,
            "total_quantity": 0.01,
            "client_order_id": "test-1",
        },
        {},
    ),
    (
        "get_order_status",
        {"order_id": "123"},
        "POST",
        API,
        "/exchange/v1/orders/status",
        {"id": "123"},
        {},
    ),
    (
        "cancel_order",
        {"order_id": "123"},
        "POST",
        API,
        "/exchange/v1/orders/cancel",
        {"id": "123"},
        {},
    ),
    (
        "get_active_orders",
        {"market": "BTCUSDT"},
        "POST",
        API,
        "/exchange/v1/orders/active_orders",
        {"market": "BTCUSDT", "page": 1, "size": 200},
        {},
    ),
    (
        "get_order_history",
        {
            "market": "BTCUSDT",
            "from_timestamp": 0,
            "to_timestamp": 1000,
            "from_id": 4,
            "sort": "desc",
        },
        "POST",
        API,
        "/exchange/v1/orders/trade_history",
        {
            "symbol": "BTCUSDT",
            "from_timestamp": 0,
            "to_timestamp": 1000,
            "from_id": 4,
            "sort": "desc",
            "limit": 500,
        },
        {},
    ),
    (
        "get_futures_orders",
        {"status": "open", "side": "buy"},
        "POST",
        API,
        F + "/orders",
        {
            "status": "open",
            "side": "buy",
            "page": "1",
            "size": "10",
            "margin_currency_short_name": ["USDT"],
        },
        {},
    ),
    (
        "create_futures_order",
        {"side": "sell", "pair": P, "order_type": "market_order", "total_quantity": 0.01},
        "POST",
        API,
        F + "/orders/create",
        {
            "order": {
                "side": "sell",
                "pair": P,
                "order_type": "market_order",
                "total_quantity": 0.01,
                "notification": "no_notification",
            }
        },
        {},
    ),
    (
        "cancel_futures_order",
        {"order_id": "futures-uuid"},
        "POST",
        API,
        F + "/orders/cancel",
        {"id": "futures-uuid"},
        {},
    ),
    (
        "list_futures_positions",
        {},
        "POST",
        API,
        F + "/positions",
        {"page": "1", "size": "10", "margin_currency_short_name": ["USDT"]},
        {},
    ),
    (
        "get_futures_currency_conversion",
        {},
        "POST",
        API,
        "/api/v1/derivatives/futures/data/conversions",
        {},
        {},
    ),
    (
        "change_futures_position_margin_type",
        {"pair": P, "margin_type": "isolated"},
        "POST",
        API,
        F + "/positions/margin_type",
        {"pair": P, "margin_type": "isolated"},
        {},
    ),
    (
        "edit_futures_order",
        {"order_id": "futures-uuid", "total_quantity": 0.01, "price": 60000},
        "POST",
        API,
        F + "/orders/edit",
        {"id": "futures-uuid", "total_quantity": 0.01, "price": 60000},
        {},
    ),
    (
        "get_futures_wallet_transactions",
        {},
        "GET",
        API,
        F + "/wallets/transactions",
        {},
        {"page": "1", "size": "1000"},
    ),
    ("get_futures_wallet_details", {}, "GET", API, F + "/wallets", {}, {}),
    (
        "transfer_futures_wallet",
        {"transfer_type": "deposit", "amount": 1},
        "POST",
        API,
        F + "/wallets/transfer",
        {"transfer_type": "deposit", "amount": 1, "currency_short_name": "USDT"},
        {},
    ),
    (
        "get_futures_cross_margin_details",
        {},
        "POST",
        API,
        F + "/positions/cross_margin_details",
        {},
        {},
    ),
    (
        "get_futures_pair_stats",
        {"pair": P},
        "POST",
        API,
        "/api/v1/derivatives/futures/data/stats",
        {},
        {"pair": P},
    ),
    (
        "get_futures_current_prices_rt",
        {},
        "GET",
        PUBLIC,
        "/market_data/v3/current_prices/futures/rt",
        None,
        {},
    ),
    (
        "get_futures_trades",
        {"pair": P, "from_date": "2026-09-01", "to_date": "2026-09-30"},
        "POST",
        API,
        F + "/trades",
        {
            "pair": P,
            "from_date": "2026-09-01",
            "to_date": "2026-09-30",
            "page": "1",
            "size": "10",
            "margin_currency_short_name": ["USDT"],
        },
        {},
    ),
    (
        "get_futures_transactions",
        {"stage": "all"},
        "POST",
        API,
        F + "/positions/transactions",
        {"stage": "all", "page": "1", "size": "10", "margin_currency_short_name": ["USDT"]},
        {},
    ),
    (
        "create_futures_tpsl",
        {
            "position_id": "position-uuid",
            "stop_loss": {"stop_price": "59000", "order_type": "stop_market"},
        },
        "POST",
        API,
        F + "/positions/create_tpsl",
        {"id": "position-uuid", "stop_loss": {"stop_price": "59000", "order_type": "stop_market"}},
        {},
    ),
    (
        "exit_futures_position",
        {"position_id": "position-uuid"},
        "POST",
        API,
        F + "/positions/exit",
        {"id": "position-uuid"},
        {},
    ),
    (
        "cancel_all_futures_open_orders_for_position",
        {"position_id": "position-uuid"},
        "POST",
        API,
        F + "/positions/cancel_all_open_orders_for_position",
        {"id": "position-uuid"},
        {},
    ),
    (
        "cancel_all_futures_open_orders",
        {},
        "POST",
        API,
        F + "/positions/cancel_all_open_orders",
        {"margin_currency_short_name": ["USDT"]},
        {},
    ),
    (
        "remove_futures_margin",
        {"position_id": "position-uuid", "amount": 1},
        "POST",
        API,
        F + "/positions/remove_margin",
        {"id": "position-uuid", "amount": 1},
        {},
    ),
    (
        "add_futures_margin",
        {"position_id": "position-uuid", "amount": 1},
        "POST",
        API,
        F + "/positions/add_margin",
        {"id": "position-uuid", "amount": 1},
        {},
    ),
    (
        "update_futures_position_leverage",
        {"leverage": "5", "position_id": "position-uuid"},
        "POST",
        API,
        F + "/positions/update_leverage",
        {"leverage": "5", "id": "position-uuid", "margin_currency_short_name": "USDT"},
        {},
    ),
    (
        "get_futures_positions_by_filter",
        {"pairs": P},
        "POST",
        API,
        F + "/positions",
        {"pairs": P, "page": "1", "size": "10", "margin_currency_short_name": ["USDT"]},
        {},
    ),
]


def test_contracts_cover_all_tools():
    assert {case[0] for case in CONTRACTS} == set(TOOLS)
    assert len(CONTRACTS) == 41


@pytest.mark.parametrize(
    "name,args,method,host,path,body,query", CONTRACTS, ids=[c[0] for c in CONTRACTS]
)
def test_documented_request_contract(name, args, method, host, path, body, query, monkeypatch):
    requests = []
    monkeypatch.setattr("coindcx_mcp.client.time.time", lambda: 1800000000.125)

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[] if name == "get_market_details" else {"ok": True})

    api = CoinDCXClient("test-key", "test-secret", transport=httpx.MockTransport(handler))
    try:
        result = asyncio.run(call_tool(name, args, api_client=api))
    finally:
        api.close()
    assert not result.is_error, result.content
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == host
    assert request.url.path == path
    assert dict(request.url.params) == query
    if body is None:
        assert not request.content
        assert "X-AUTH-APIKEY" not in request.headers
    else:
        assert json.loads(request.content) == dict(body, timestamp=1800000000125)
        assert request.headers["X-AUTH-APIKEY"] == "test-key"
        expected = hmac.new(b"test-secret", request.content, hashlib.sha256).hexdigest()
        assert request.headers["X-AUTH-SIGNATURE"] == expected
        assert request.headers["Content-Type"] == "application/json"
