import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from coindcx_mcp import server
from coindcx_mcp.client import CoinDCXClient
from coindcx_mcp.config import Config
from coindcx_mcp.tools import READ_TOOLS


def test_read_only_is_default_and_invalid_values_fail(monkeypatch):
    monkeypatch.delenv("COINDCX_READ_ONLY")
    assert Config().read_only
    monkeypatch.setenv("COINDCX_READ_ONLY", "false")
    assert not Config().read_only
    monkeypatch.setenv("COINDCX_READ_ONLY", "flase")
    with pytest.raises(ValueError, match="COINDCX_READ_ONLY"):
        Config()


@pytest.mark.parametrize("name", sorted(set(server.TOOLS) - READ_TOOLS))
def test_all_mutations_are_blocked_before_dispatch(name):
    class ForbiddenClient:
        def __getattr__(self, name):
            pytest.fail("A disabled operation must not access the API client")

    result = asyncio.run(server.call_tool(name, {}, api_client=ForbiddenClient(), read_only=True))
    assert result.is_error
    assert "disabled" in json.loads(result.content[0].text)["error"]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_read_only_discovery_and_account_reads(mode, monkeypatch):
    requests = []

    def make_client():
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=[{"currency": "BTC", "balance": "1"}])

        return CoinDCXClient("test-key", "test-secret", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(server, "make_client", make_client)
    monkeypatch.setenv("COINDCX_READ_ONLY", "true")

    async def run():
        async with Client(server.app, mode=mode) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == READ_TOOLS
            assert all(tool.annotations.read_only_hint for tool in tools)
            # Changing the environment cannot expand an established connection's access.
            monkeypatch.setenv("COINDCX_READ_ONLY", "false")
            assert (await client.call_tool("transfer_futures_wallet", {})).is_error
            result = await client.call_tool("get_balances", {})
            assert not result.is_error
            assert json.loads(result.content[0].text)[0]["currency"] == "BTC"

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0].url.path == "/exchange/v1/users/balances"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("entry", ["console", "module", "launcher"])
def test_stdio_forces_read_only_despite_environment(mode, entry, tmp_path):
    if entry == "launcher":
        command = str(Path(__file__).resolve().parents[1] / "scripts/run-portfolio.sh")
        args = []
    elif entry == "console":
        command = str(Path(sys.executable).parent / "coindcx-mcp")
        args = ["--read-only"]
    else:
        command = sys.executable
        args = ["-m", "coindcx_mcp.server", "--read-only"]
    params = StdioServerParameters(
        command=command,
        args=args,
        cwd=str(tmp_path),
        env={
            "COINDCX_ENV_FILE": str(tmp_path / "absent.env"),
            "COINDCX_API_KEY": "",
            "COINDCX_SECRET_KEY": "",
            "COINDCX_READ_ONLY": "false",
            "COINDCX_SANDBOX_MODE": "false",
        },
    )

    async def run():
        async with Client(params, mode=mode, read_timeout_seconds=10) as client:
            assert {tool.name for tool in (await client.list_tools()).tools} == READ_TOOLS
            assert (await client.call_tool("get_balances", {})).is_error
            assert (await client.call_tool("create_order", {})).is_error

    asyncio.run(run())
