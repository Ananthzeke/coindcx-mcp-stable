import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from coindcx_mcp import server
from coindcx_mcp.client import CoinDCXClient
from coindcx_mcp.config import Config
from coindcx_mcp.tools import READ_TOOLS


def unpack(result):
    return json.loads(result.content[0].text)


def test_access_mode_and_cap_configuration(monkeypatch):
    monkeypatch.setenv("COINDCX_READ_ONLY", "true")
    assert Config().access_mode == "portfolio"
    monkeypatch.setenv("COINDCX_ACCESS_MODE", "spot")
    with pytest.raises(ValueError, match="requires portfolio"):
        Config()
    monkeypatch.setenv("COINDCX_READ_ONLY", "false")
    assert Config().access_mode == "spot"
    assert Config().max_spot_order_inr == Decimal("500")
    monkeypatch.setenv("COINDCX_MAX_SPOT_ORDER_INR", "NaN")
    with pytest.raises(ValueError, match="positive"):
        Config()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_spot_preview_one_time_live_call_and_replay_blocked(mode, monkeypatch):
    requests = []

    def make_client():
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"orders": [{"id": "123"}]})

        return CoinDCXClient("test-key", "test-secret", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(server, "make_client", make_client)
    monkeypatch.setenv("COINDCX_ACCESS_MODE", "spot")
    order = {"side": "buy", "market": "BTCINR", "price": 100, "total_quantity": 2}

    async def run():
        async with Client(server.app, mode=mode) as client:
            discovered = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(discovered) == READ_TOOLS | {
                "preview_spot_order",
                "create_order",
                "cancel_order",
            }
            assert discovered["create_order"].input_schema["required"] == [
                "side",
                "order_type",
                "market",
                "price",
                "total_quantity",
                "preview_token",
            ]
            assert (await client.call_tool("create_futures_order", {})).is_error
            assert (await client.call_tool("transfer_futures_wallet", {})).is_error
            assert (
                await client.call_tool("create_order", {**order, "order_type": "limit_order"})
            ).is_error
            preview = await client.call_tool("preview_spot_order", order)
            assert not preview.is_error
            token = unpack(preview)["preview_token"]
            assert requests == []
            changed = {**order, "price": 101, "order_type": "limit_order", "preview_token": token}
            assert (await client.call_tool("create_order", changed)).is_error
            assert requests == []
            # A mismatched call consumes its token, so it cannot later be reused.
            exact = {**order, "order_type": "limit_order", "preview_token": token}
            assert (await client.call_tool("create_order", exact)).is_error
            preview = await client.call_tool("preview_spot_order", order)
            exact["preview_token"] = unpack(preview)["preview_token"]
            assert not (await client.call_tool("create_order", exact)).is_error
            assert (await client.call_tool("create_order", exact)).is_error
            assert (await client.call_tool("preview_spot_order", {**order, "price": 300})).is_error
            assert (
                await client.call_tool("preview_spot_order", {**order, "market": "BTCUSDT"})
            ).is_error
            assert (await client.call_tool("preview_spot_order", {**order, "price": 0})).is_error
            assert len(requests) == 1

    asyncio.run(run())
    assert requests[0].url.path == "/exchange/v1/orders/create"
    payload = json.loads(requests[0].content)
    assert isinstance(payload.pop("timestamp"), int)
    assert payload == {
        "side": "buy",
        "order_type": "limit_order",
        "market": "BTCINR",
        "total_quantity": 2,
        "price_per_unit": 100,
    }


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_spot_launcher_forces_narrow_mode(mode, tmp_path):
    command = str(Path(__file__).resolve().parents[1] / "scripts/run-spot-trading.sh")
    params = StdioServerParameters(
        command=command,
        args=[],
        cwd=str(tmp_path),
        env={
            "COINDCX_ENV_FILE": str(tmp_path / "absent.env"),
            "COINDCX_API_KEY": "",
            "COINDCX_SECRET_KEY": "",
            "COINDCX_READ_ONLY": "true",
            "COINDCX_ACCESS_MODE": "all",
            "COINDCX_MAX_SPOT_ORDER_INR": "100000000",
            "COINDCX_SANDBOX_MODE": "false",
        },
    )

    async def run():
        async with Client(params, mode=mode, read_timeout_seconds=10) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == READ_TOOLS | {"preview_spot_order", "create_order", "cancel_order"}
            assert (await client.call_tool("create_futures_order", {})).is_error
            assert (await client.call_tool("transfer_futures_wallet", {})).is_error
            result = await client.call_tool(
                "preview_spot_order",
                {"side": "buy", "market": "BTCINR", "price": 600, "total_quantity": 1},
            )
            assert result.is_error
            assert "500" in unpack(result)["error"]

    asyncio.run(run())
