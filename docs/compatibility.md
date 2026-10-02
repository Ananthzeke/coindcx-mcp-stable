# Compatibility review — 2026-10-02

## Sources and decisions

- [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/) identifies 2.x as the stable line and requires Python 3.10+. This project pins SDK 2.2.0 and locks the full dependency graph.
- [MCP v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/) documents constructor-based low-level handlers, complete result objects, snake_case model fields, and removal of automatic tool-schema validation. The server implements explicit JSON Schema validation and retains stdio transport.
- [CoinDCX API reference](https://docs.coindcx.com/) supplies endpoint methods, hosts, query/body parameters, and signing examples. The complete tool-to-request contract is captured in `tests/test_contracts.py`, with one independently specified case for each of the 41 tools.
- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) documents `--locked` as the mode that refuses to change an outdated lockfile. Installation and CI use it.

## Corrections from the original project

Public tools no longer require keys. Spot trades, order books, and candles use the documented `api.coindcx.com` host; the three public futures market-data routes retain `public.coindcx.com`. Futures wallet details and wallet transactions use signed GET requests with JSON bodies. Other account routes retain documented POST methods.

Spot trade limits and account trade-history limits are 500. Spot active-order requests require a market and expose documented pagination. Spot order IDs are numeric strings; no UUID-to-numeric guessing is attempted. Spot order payloads use `total_quantity` and `price_per_unit`; the old `quantity` input is translated to `total_quantity`.

Pair lookup preserves the returned exchange prefix. Candle bounds are neither dropped nor silently replaced with recent data. Current spot candle intervals and supported full-position TP/SL order variants follow the published request definitions.

The installed command now has a synchronous entry point. Worker threads keep synchronous HTTP off the async event loop, with bounded concurrency and lifespan-owned HTTP resources. POSTs are never replayed automatically. MCP failures use `is_error=True`, including documented partial TP/SL failures.

## Documentation ambiguities

CoinDCX's general authentication notes say all authenticated calls use POST, while the futures wallet sections specifically document GET. Endpoint-specific HTTP Request declarations take precedence for those two wallet reads.

The cross-margin-details and currency-conversion Python snippets use GET, but their HTTP Request declarations and JavaScript examples use POST. This project follows the explicit endpoint declarations. No method fallback is attempted.

Some timestamp descriptions say seconds, while the Python examples compute `time.time() * 1000` and JavaScript uses `Date.now()`. Signed requests consistently use milliseconds, matching those executable examples. Futures candlestick query bounds remain seconds because their market-data example explicitly uses epoch seconds.

Futures order request tables sometimes abbreviate `market`/`limit`, but executable examples and responses use `market_order`/`limit_order`. The project keeps those demonstrated wire values.

The full-position TP/SL example includes a stop-limit response, but its current request definitions explicitly allow only `take_profit_market` and `stop_market` and mark `limit_price` unsupported. The server uses the current request definitions.

Spot market details advertise `stop_limit` and `take_profit_limit`; spot order response definitions describe `stop_price`. These are exposed explicitly instead of the original unsupported `stop_order` spelling.

## Validation boundary

Mocked tests verify request construction and protocol behavior. They do not prove that every authenticated route is currently enabled for a particular account. No user credentials are loaded by the tests and no live trading, cancellation, margin change, or transfer is performed. CoinDCX enforces live instrument constraints and permission checks.

## Verified locally

The final offline suite passed all 104 tests on Python 3.10.12 and Python 3.11.1. Both modern and legacy MCP connections passed through the installed command and `python -m`, including launches from a different working directory. Ruff checks, formatting checks, and source/wheel builds passed. Both archives exclude credentials and compiled bytecode.

Four unauthenticated live checks returned HTTP 200 with JSON: the market list, spot BTC/USDT order book, spot BTC/USDT candles, and current futures prices. Authenticated exchange operations were tested with mocked responses only. The Python 3.12–3.14 CI jobs have been configured but were not run locally.
