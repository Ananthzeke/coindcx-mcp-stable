# CoinDCX MCP Server

CoinDCX spot and futures tools for MCP assistants. Requires Python 3.10+ and uses the stable MCP Python SDK 2.2.0. All 41 existing tool names are retained. Based on [ayagup/coindcx-mcp](https://github.com/ayagup/coindcx-mcp).

## Install and run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
cd coindcx-mcp
uv sync --locked
cp .env.example .env
uv run --locked --no-dev coindcx-mcp
```

`./install.sh` installs from the lockfile and creates `.env` only if it is absent. The server uses stdio: it waits for an MCP client and writes protocol messages to stdout. Logging goes to stderr. `uv run --locked --no-dev python -m coindcx_mcp.server` is an equivalent entry point.

Public market tools work without credentials. For account and trading tools, set `COINDCX_API_KEY` and `COINDCX_SECRET_KEY` in `.env` or your process environment. Generate keys through your CoinDCX account and give them only the permissions you intend to use.

The server loads `.env` beside the source project, regardless of the launching client's working directory. `COINDCX_ENV_FILE` selects an explicit file, which is useful for an installed wheel. Process environment values take precedence, including explicitly empty values. Existing credentials are never overwritten by installation.

## Connect an MCP client

For clients that accept an `mcpServers` configuration, use an absolute project path and ensure `uv` is on the client's PATH (otherwise use its absolute executable path):

```json
{
  "mcpServers": {
    "coindcx": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/coindcx-mcp", "run", "--locked", "--no-dev", "coindcx-mcp"]
    }
  }
}
```

The SDK supports both current discovery connections and legacy initialize connections. Automated tests cover both over real stdio, including launches from a different directory.

## Tools and request rules

| Area | Tools |
| --- | --- |
| Spot market data | `get_ticker`, `get_markets`, `get_market_details`, `get_trades`, `get_order_book`, `get_candles` |
| Spot account | `get_balances`, `get_user_info`, `get_order_status`, `get_active_orders`, `get_order_history` |
| Spot orders | `create_order`, `cancel_order` |
| Futures market data | `get_futures_active_instruments`, `get_futures_instrument_details`, `get_futures_instrument_trades`, `get_futures_instrument_orderbook`, `get_futures_instrument_candlesticks`, `get_futures_current_prices_rt` |
| Futures account | `get_futures_orders`, `list_futures_positions`, `get_futures_positions_by_filter`, `get_futures_currency_conversion`, `get_futures_cross_margin_details`, `get_futures_pair_stats`, `get_futures_trades`, `get_futures_transactions`, `get_futures_wallet_details`, `get_futures_wallet_transactions` |
| Futures orders and positions | `create_futures_order`, `cancel_futures_order`, `edit_futures_order`, `create_futures_tpsl`, `exit_futures_position`, `cancel_all_futures_open_orders`, `cancel_all_futures_open_orders_for_position`, `change_futures_position_margin_type`, `update_futures_position_leverage`, `add_futures_margin`, `remove_futures_margin` |
| Futures transfers | `transfer_futures_wallet` |

Tool discovery exposes required fields, valid values, and read/write annotations. Unknown fields, missing inputs, invalid date ranges, nonpositive amounts, and nonfinite numbers are rejected before an exchange request.

- Spot order IDs are positive numeric strings. Futures order IDs retain their existing format.
- Spot orders use `total_quantity`. `quantity` is an alias and cannot be supplied with `total_quantity`. Limit variants require `price`; stop/take-profit limit variants also require `stop_price`.
- `get_active_orders` requires `market` and supports `page` and `size` (maximum 200).
- `get_order_history` returns executed trades, not all historical orders. It supports `from_id`, `sort`, and a maximum `limit` of 500. Optional `side` filtering is applied locally to the returned page.
- Spot trade history has a maximum `limit` of 500. Spot candles support the currently documented intervals `1m`, `15m`, `1h`, and `1d`, with a maximum `limit` of 1000.
- Spot candle bounds use milliseconds; futures candlestick bounds use seconds. Requested bounds are preserved. An empty historical response stays empty.
- Fully qualified spot pair identifiers are preserved, including exchange prefixes such as `KC-`. Symbols like `BTCUSDT` resolve through market details; unknown symbols fail instead of using a guessed market.
- Futures market variants omit `price` and `time_in_force`. Trigger variants require `stop_price`; limit variants require `price`. Cross margin is available only for USDT futures.
- Full-position TP/SL supports the documented `take_profit_market` and `stop_market` variants. `limit_price` is currently unsupported.
- Leverage updates and filtered position queries require exactly one target selector.

Instrument-specific tick sizes, quantity steps, notional limits, current leverage, available balances, and exchange-side permissions are still enforced by CoinDCX. Inspect market or instrument details when preparing an order.

## Reliability behavior

HTTP connections are pooled, timed out, and closed on shutdown. Up to four network operations run in worker threads, keeping the async MCP server responsive. Signed JSON is sent as the exact bytes used for HMAC-SHA256; timestamps are milliseconds, following the official Python examples.

GET requests retry transient network failures and HTTP 429/502/503/504 at most twice, with bounded delays. POST requests are sent once. If a write times out or returns an uncertain response, check order, position, or wallet status before retrying: an exchange may have processed it even if the reply was lost. There is no automatic replay of trading or transfer requests.

Exchange errors, including partial TP/SL failures in HTTP 200 responses, set the MCP error flag. Logs omit tool arguments and credentials. Authenticated requests use HTTPS and do not follow redirects.

`COINDCX_BASE_URL` and `COINDCX_PUBLIC_BASE_URL` are configurable HTTPS origins. Set them only to endpoints you trust; authenticated requests send credentials to `COINDCX_BASE_URL`. `COINDCX_SANDBOX_MODE=true` is rejected because the original flag never provided a simulation environment.

## Development and validation

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Tests mock exchange traffic and isolate environment files. They cover all 41 endpoint contracts, signed GET/POST requests, schemas, errors, retries, public access without keys, client shutdown, event-loop responsiveness, and current/legacy MCP stdio connections. `uv run --locked python test_server.py` runs the same offline suite.

The GitHub workflow runs these checks on Python 3.10–3.14. Preserve `uv.lock` and use `--locked` for reproducible installations. Review dependency upgrades deliberately and rerun the suite before adopting them.

See [compatibility notes](docs/compatibility.md) for the official references and documentation ambiguities. Automated tests do not establish live authenticated trading behavior or guarantee exchange uptime.
