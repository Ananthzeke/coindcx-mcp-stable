"""MCP 2.x stdio server with explicit schemas and owned HTTP client lifetime."""

import asyncio
import argparse
import copy
import json
import logging
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from functools import partial

import anyio
import mcp.types as types
from mcp import MCPError
from jsonschema import Draft202012Validator, FormatChecker
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from .client import CoinDCXClient, CoinDCXError
from .config import Config
from .tools import READ_TOOLS, build_tools

logger = logging.getLogger(__name__)
TOOLS = {tool.name: tool for tool in build_tools()}
VALIDATORS = {
    name: Draft202012Validator(tool.input_schema, format_checker=FormatChecker())
    for name, tool in TOOLS.items()
}
SPOT_TRADE_NAMES = READ_TOOLS | {"create_order", "cancel_order"}
SPOT_ORDER_SCHEMA = copy.deepcopy(TOOLS["create_order"].input_schema)
SPOT_ORDER_SCHEMA.pop("oneOf", None)
SPOT_ORDER_SCHEMA.pop("allOf", None)
SPOT_ORDER_SCHEMA["properties"] = {
    key: SPOT_ORDER_SCHEMA["properties"][key]
    for key in ("side", "order_type", "market", "price", "total_quantity")
}
SPOT_ORDER_SCHEMA["properties"]["order_type"]["enum"] = ["limit_order"]
SPOT_ORDER_SCHEMA["properties"]["market"]["pattern"] = "^[A-Z0-9]+INR$"
SPOT_ORDER_SCHEMA["required"] = ["side", "order_type", "market", "price", "total_quantity"]
SPOT_PREVIEW_SCHEMA = copy.deepcopy(SPOT_ORDER_SCHEMA)
SPOT_PREVIEW_SCHEMA["properties"].pop("order_type")
SPOT_PREVIEW_SCHEMA["required"].remove("order_type")
SPOT_ORDER_SCHEMA["properties"]["preview_token"] = {
    "type": "string",
    "description": "One-time token from preview_spot_order, valid for 15 minutes",
    "minLength": 1,
}
SPOT_ORDER_SCHEMA["required"].append("preview_token")
SPOT_VALIDATORS = {
    "preview_spot_order": Draft202012Validator(SPOT_PREVIEW_SCHEMA),
    "create_order": Draft202012Validator(SPOT_ORDER_SCHEMA),
}
SPOT_PREVIEW_TOOL = types.Tool(
    name="preview_spot_order",
    description="Preview an INR spot limit order and receive a one-time token; this does not trade.",
    input_schema=SPOT_PREVIEW_SCHEMA,
    annotations=types.ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
SPOT_CREATE_TOOL = copy.deepcopy(TOOLS["create_order"])
SPOT_CREATE_TOOL.input_schema = SPOT_ORDER_SCHEMA
SPOT_CREATE_TOOL.description = (
    "Place one INR spot limit order previously previewed with the exact same inputs; "
    "this spends or sells real assets and requires user approval."
)


def make_client() -> CoinDCXClient:
    config = Config()
    return CoinDCXClient(
        config.api_key, config.secret_key, config.base_url, public_base_url=config.public_base_url
    )


@asynccontextmanager
async def lifespan(server: Server):
    # Snapshot access policy for this connection; never trust client-side filtering.
    config = Config()
    client = make_client()
    try:
        yield {
            "client": client,
            "limiter": anyio.CapacityLimiter(4),
            "read_only": config.read_only,
            "access_mode": config.access_mode,
            "max_spot_order_inr": config.max_spot_order_inr,
            "pending_spot_orders": {},
        }
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


def resolve_mode(read_only: bool | None, access_mode: str | None) -> str:
    if access_mode is not None:
        return access_mode
    if read_only is not None:
        return "portfolio" if read_only else "all"
    return Config().access_mode


async def list_tools(
    *, read_only: bool | None = None, access_mode: str | None = None
) -> list[types.Tool]:
    mode = resolve_mode(read_only, access_mode)
    names = READ_TOOLS if mode == "portfolio" else SPOT_TRADE_NAMES if mode == "spot" else TOOLS
    tools = [tool for name, tool in TOOLS.items() if name in names]
    if mode == "spot":
        tools = [SPOT_CREATE_TOOL if tool.name == "create_order" else tool for tool in tools]
        tools.append(SPOT_PREVIEW_TOOL)
    return tools


async def call_tool(
    name: str,
    arguments: dict,
    *,
    api_client: CoinDCXClient,
    limiter: anyio.CapacityLimiter | None = None,
    read_only: bool | None = None,
    access_mode: str | None = None,
    max_spot_order_inr: Decimal | None = None,
    pending_spot_orders: dict | None = None,
) -> types.CallToolResult:
    mode = resolve_mode(read_only, access_mode)
    if name not in TOOLS and not (mode == "spot" and name == "preview_spot_order"):
        raise MCPError(-32602, "Unknown tool")
    if mode == "portfolio" and name not in READ_TOOLS:
        return response({"error": "This tool is disabled in read-only portfolio mode"}, error=True)
    if mode == "spot" and name not in SPOT_TRADE_NAMES and name != "preview_spot_order":
        return response({"error": "This tool is disabled in spot trading mode"}, error=True)
    try:
        # Reject NaN/Infinity too: Python's JSON parser otherwise accepts them.
        json.dumps(arguments, allow_nan=False)
        validator = (
            SPOT_VALIDATORS[name]
            if mode == "spot" and name in SPOT_VALIDATORS
            else VALIDATORS[name]
        )
        validation_error = next(validator.iter_errors(arguments), None)
        if validation_error:
            path = ".".join(str(part) for part in validation_error.absolute_path) or "arguments"
            return response(
                {"error": f"Invalid {path}: {validation_error.validator} validation failed"},
                error=True,
            )
        if mode == "spot" and name in {"preview_spot_order", "create_order"}:
            cap = max_spot_order_inr or Config().max_spot_order_inr
            notional = Decimal(str(arguments["price"])) * Decimal(str(arguments["total_quantity"]))
            if notional > cap:
                return response({"error": f"Order value exceeds the INR {cap} limit"}, error=True)
            pending = pending_spot_orders if pending_spot_orders is not None else {}
            now = time.monotonic()
            for token, (expiry, _) in list(pending.items()):
                if expiry <= now:
                    pending.pop(token, None)
            order = {key: arguments[key] for key in ("side", "market", "price", "total_quantity")}
            if name == "preview_spot_order":
                token = secrets.token_urlsafe(24)
                if len(pending) >= 16:
                    pending.pop(next(iter(pending)))
                pending[token] = (now + 900, order)
                return response(
                    {
                        "side": order["side"],
                        "market": order["market"],
                        "order_type": "limit_order",
                        "price_inr": order["price"],
                        "quantity": order["total_quantity"],
                        "maximum_order_value_inr": str(notional),
                        "preview_token": token,
                        "expires_in_seconds": 900,
                        "message": "Review these inputs before approving the live order call.",
                    }
                )
            token = arguments["preview_token"]
            preview = pending.pop(token, None)
            if preview is None or preview[1] != order:
                return response(
                    {"error": "Preview missing, expired, or inputs changed"}, error=True
                )
            arguments = {key: value for key, value in arguments.items() if key != "preview_token"}
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
    return types.ListToolsResult(
        tools=await list_tools(access_mode=ctx.lifespan_context["access_mode"])
    )


async def handle_call_tool(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult:
    return await call_tool(
        params.name,
        params.arguments or {},
        api_client=ctx.lifespan_context["client"],
        limiter=ctx.lifespan_context["limiter"],
        read_only=ctx.lifespan_context["read_only"],
        access_mode=ctx.lifespan_context["access_mode"],
        max_spot_order_inr=ctx.lifespan_context["max_spot_order_inr"],
        pending_spot_orders=ctx.lifespan_context["pending_spot_orders"],
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
    parser = argparse.ArgumentParser(description="CoinDCX MCP stdio server")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Enforce portfolio-only access even if COINDCX_READ_ONLY=false",
    )
    parser.add_argument(
        "--spot-trading",
        action="store_true",
        help="Expose INR spot limit orders with previews and a value cap",
    )
    args = parser.parse_args()
    if args.read_only and args.spot_trading:
        parser.error("Choose --read-only or --spot-trading")
    if args.read_only:
        os.environ["COINDCX_READ_ONLY"] = "true"
        os.environ["COINDCX_ACCESS_MODE"] = "portfolio"
    if args.spot_trading:
        os.environ["COINDCX_READ_ONLY"] = "false"
        os.environ["COINDCX_ACCESS_MODE"] = "spot"
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(serve())


if __name__ == "__main__":
    main()
