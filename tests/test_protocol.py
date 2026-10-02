import asyncio
import json
import sys
import threading
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from mcp import MCPError
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from coindcx_mcp import server
from coindcx_mcp.client import CoinDCXClient
from coindcx_mcp.tools import READ_TOOLS


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_protocol_discovery_call_and_cleanup(mode, monkeypatch):
    created = []

    def make_client():
        api = CoinDCXClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json=[{"market": "BTCUSDT"}])
            )
        )
        created.append(api)
        return api

    monkeypatch.setattr(server, "make_client", make_client)

    async def run():
        async with Client(server.app, mode=mode) as client:
            result = await client.list_tools()
            assert {tool.name for tool in result.tools} == set(server.TOOLS)
            for tool in result.tools:
                Draft202012Validator.check_schema(tool.input_schema)
                assert tool.annotations.read_only_hint == (tool.name in READ_TOOLS)
            ticker = await client.call_tool("get_ticker", {})
            assert not ticker.is_error
            assert json.loads(ticker.content[0].text) == [{"market": "BTCUSDT"}]
            failure = await client.call_tool("get_balances", {})
            assert failure.is_error
            assert (await client.call_tool("create_order", {})).is_error
            with pytest.raises(MCPError) as error:
                await client.call_tool("unknown", {})
            assert error.value.error.code == -32602

    asyncio.run(run())
    assert created and all(api.client.is_closed for api in created)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("entry", ["console", "module"])
def test_real_stdio_entrypoints_without_credentials(mode, entry, tmp_path):
    command = (
        str(Path(sys.executable).parent / "coindcx-mcp") if entry == "console" else sys.executable
    )
    args = [] if entry == "console" else ["-m", "coindcx_mcp.server"]
    params = StdioServerParameters(
        command=command,
        args=args,
        env={
            "COINDCX_ENV_FILE": str(tmp_path / "absent.env"),
            "COINDCX_API_KEY": "",
            "COINDCX_SECRET_KEY": "",
            "COINDCX_SANDBOX_MODE": "false",
            "COINDCX_READ_ONLY": "false",
            "COINDCX_BASE_URL": "https://api.coindcx.com",
            "COINDCX_PUBLIC_BASE_URL": "https://public.coindcx.com",
        },
        cwd=str(tmp_path),
    )

    async def run():
        async with Client(params, mode=mode, read_timeout_seconds=10) as client:
            assert len((await client.list_tools()).tools) == 41
            assert (await client.call_tool("get_balances", {})).is_error

    asyncio.run(run())


def test_slow_http_does_not_block_event_loop():
    started, release = threading.Event(), threading.Event()

    def handler(request):
        started.set()
        assert release.wait(5)
        return httpx.Response(200, json={"ok": True})

    api = CoinDCXClient(transport=httpx.MockTransport(handler))

    async def run():
        task = asyncio.create_task(server.call_tool("get_ticker", {}, api_client=api))
        try:

            async def wait_started():
                while not started.is_set():
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_started(), timeout=3)
            # A blocked loop would never reach here before handler timed out.
            assert not task.done()
        finally:
            release.set()
        assert not (await task).is_error

    try:
        asyncio.run(run())
    finally:
        api.close()
