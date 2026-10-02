"""MCP 2.x stdio server with explicit schemas and owned HTTP client lifetime."""

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from functools import partial

import anyio
import mcp.types as types
from mcp import MCPError
from jsonschema import Draft202012Validator, FormatChecker
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from .client import CoinDCXClient, CoinDCXError
from .config import Config
from .tools import build_tools

logger = logging.getLogger(__name__)
TOOLS = {tool.name: tool for tool in build_tools()}
VALIDATORS = {
    name: Draft202012Validator(tool.input_schema, format_checker=FormatChecker())
    for name, tool in TOOLS.items()
}


def make_client() -> CoinDCXClient:
    config = Config()
    return CoinDCXClient(
        config.api_key, config.secret_key, config.base_url, public_base_url=config.public_base_url
    )


@asynccontextmanager
async def lifespan(server: Server):
    client = make_client()
    try:
        yield {"client": client, "limiter": anyio.CapacityLimiter(4)}
    finally:
        await anyio.to_thread.run_sync(client.close)


def response(data, *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(data, allow_nan=False))],
        is_error=error,
    )


def exchange_failed(data) -> bool:
    """Detect documented API failures, including partially failed TP/SL creation."""
    if isinstance(data, dict):
        if (
            data.get("success") is False
            or data.get("error")
            or data.get("status") in ("error", "failed", "failure")
        ):
            return True
        code = data.get("code")
        if isinstance(code, (int, str)) and str(code).isdigit() and int(code) >= 400:
            return True
        return any(exchange_failed(value) for value in data.values())
    if isinstance(data, list):
        return any(exchange_failed(item) for item in data)
    return False


async def list_tools() -> list[types.Tool]:
    return list(TOOLS.values())


async def call_tool(
    name: str,
    arguments: dict,
    *,
    api_client: CoinDCXClient,
    limiter: anyio.CapacityLimiter | None = None,
) -> types.CallToolResult:
    if name not in TOOLS:
        raise MCPError(-32602, "Unknown tool")
    try:
        # Reject NaN/Infinity too: Python's JSON parser otherwise accepts them.
        json.dumps(arguments, allow_nan=False)
        validation_error = next(VALIDATORS[name].iter_errors(arguments), None)
        if validation_error:
            path = ".".join(str(part) for part in validation_error.absolute_path) or "arguments"
            return response(
                {"error": f"Invalid {path}: {validation_error.validator} validation failed"},
                error=True,
            )
        operation = partial(getattr(api_client, name), **arguments)
        # AnyIO shields cancellation until the worker finishes so shutdown cannot
        # close a client while a write is in flight. No implicit POST retry.
        result = await anyio.to_thread.run_sync(operation, limiter=limiter)
        return response(result, error=exchange_failed(result))
    except (ValueError, CoinDCXError) as exc:
        return response({"error": api_client._redact(str(exc))}, error=True)
    except Exception:
        # Do not expose HTTP headers, signed bodies, or account data in logs.
        logger.error("Unexpected failure in tool %s", name)
        raise MCPError(-32603, "Unexpected server error; see server logs") from None


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    if params is not None and params.cursor is not None:
        raise MCPError(-32602, "This server does not paginate tools")
    return types.ListToolsResult(tools=await list_tools())


async def handle_call_tool(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult:
    return await call_tool(
        params.name,
        params.arguments or {},
        api_client=ctx.lifespan_context["client"],
        limiter=ctx.lifespan_context["limiter"],
    )


app = Server(
    "coindcx-mcp",
    version="0.2.0",
    lifespan=lifespan,
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


async def serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    """Synchronous entry point for both the installed command and python -m."""
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(serve())


if __name__ == "__main__":
    main()
