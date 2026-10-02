"""Public tool schemas, shared by discovery and request validation."""

import mcp.types as types


READ_TOOLS = frozenset(
    {
        "get_ticker",
        "get_markets",
        "get_market_details",
        "get_trades",
        "get_order_book",
        "get_candles",
        "get_balances",
        "get_user_info",
        "get_order_status",
        "get_active_orders",
        "get_order_history",
        "get_futures_active_instruments",
        "get_futures_instrument_details",
        "get_futures_instrument_trades",
        "get_futures_instrument_orderbook",
        "get_futures_instrument_candlesticks",
        "get_futures_orders",
        "list_futures_positions",
        "get_futures_currency_conversion",
        "get_futures_wallet_transactions",
        "get_futures_wallet_details",
        "get_futures_cross_margin_details",
        "get_futures_pair_stats",
        "get_futures_current_prices_rt",
        "get_futures_trades",
        "get_futures_transactions",
        "get_futures_positions_by_filter",
    }
)


def _constrain_properties(schema):
    for name, field in schema.get("properties", {}).items():
        if field.get("type") == "string":
            field["minLength"] = 1
            field["pattern"] = r".*\S.*"
        if name in (
            "price",
            "stop_price",
            "take_profit_price",
            "stop_loss_price",
            "quantity",
            "total_quantity",
            "amount",
            "leverage",
        ):
            if field.get("type") in ("number", "integer"):
                field["exclusiveMinimum"] = 0
            elif field.get("type") == "string":
                field["pattern"] = r"^(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)$"
        if name in (
            "from_time",
            "to_time",
            "start_time",
            "end_time",
            "from_timestamp",
            "to_timestamp",
        ):
            field["minimum"] = 0
        if name in ("from_date", "to_date"):
            field["format"] = "date"
        if field.get("type") == "array":
            field["minItems"] = 1
            field["uniqueItems"] = True
        if field.get("type") == "object":
            _constrain_properties(field)


def build_tools() -> list[types.Tool]:
    """List available tools."""
    tools = [
        types.Tool(
            name="get_ticker",
            description="Get ticker data for all markets on CoinDCX",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_markets",
            description="Get all available trading markets on CoinDCX",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_market_details",
            description="Get detailed information about a specific trading pair",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Trading pair symbol (e.g., 'B-BTC_USDT')",
                    }
                },
                "required": ["pair"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_trades",
            description="Get recent trades for a specific market",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Trading pair symbol (e.g., 'B-BTC_USDT')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of trades to retrieve (default: 30, max: 500)",
                        "minimum": 1,
                        "maximum": 500,
                    },
                },
                "required": ["pair"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_order_book",
            description="Get order book (bids and asks) for a specific market",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Trading pair symbol (e.g., 'B-BTC_USDT')",
                    }
                },
                "required": ["pair"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_active_instruments",
            description="Get list of all active futures instruments on CoinDCX",
            input_schema={
                "type": "object",
                "properties": {
                    "margin_currency": {
                        "type": "string",
                        "description": "Futures margin mode: 'USDT' (default) or 'INR'",
                        "enum": ["USDT", "INR"],
                    }
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_instrument_details",
            description="Get detailed information about a specific futures instrument, including leverage limits, fees, price/quantity increments, funding frequency, and order types",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Futures instrument pair (e.g., 'B-BTC_USDT')",
                    },
                    "margin_currency": {
                        "type": "string",
                        "description": "Futures margin mode: 'USDT' (default) or 'INR'",
                        "enum": ["USDT", "INR"],
                    },
                },
                "required": ["pair"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_instrument_trades",
            description="Get real-time trade history for a specific futures instrument",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Futures instrument pair (e.g., 'B-BTC_USDT')",
                    }
                },
                "required": ["pair"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_instrument_orderbook",
            description="Get order book (bids and asks) for a specific futures instrument",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Futures instrument pair (e.g., 'B-BTC_USDT')",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Order book depth (default: 50)",
                        "enum": [10, 20, 50],
                    },
                },
                "required": ["pair"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_instrument_candlesticks",
            description="Get candlestick (OHLCV) data for a specific futures instrument",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Futures instrument pair (e.g., 'B-BTC_USDT')",
                    },
                    "resolution": {
                        "type": "string",
                        "description": "Candle resolution: '1' (1min), '5' (5min), '60' (1hour), '1D' (1day)",
                        "enum": ["1", "5", "60", "1D"],
                    },
                    "from_time": {
                        "type": "integer",
                        "description": "EPOCH start timestamp in seconds",
                    },
                    "to_time": {"type": "integer", "description": "EPOCH end timestamp in seconds"},
                },
                "required": ["pair", "resolution", "from_time", "to_time"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_candles",
            description="Get spot candles for the requested time range. Timestamps are milliseconds; omitted bounds request recent data.",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Trading pair symbol (e.g., 'BTCUSDT')",
                    },
                    "interval": {
                        "type": "string",
                        "description": "Spot candle interval: 1m, 15m, 1h, 1d",
                        "enum": ["1m", "15m", "1h", "1d"],
                    },
                    "start_time": {
                        "type": "integer",
                        "description": "Start timestamp in milliseconds (optional)",
                    },
                    "end_time": {
                        "type": "integer",
                        "description": "End timestamp in milliseconds (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of candles to retrieve (default: 100, max: 1000)",
                        "minimum": 1,
                        "maximum": 1000,
                    },
                },
                "required": ["pair", "interval"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_balances",
            description="Get account balances for all assets",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_user_info",
            description="Get user account information",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="create_order",
            description="Create a new buy or sell order",
            input_schema={
                "type": "object",
                "properties": {
                    "side": {
                        "type": "string",
                        "description": "Order side",
                        "enum": ["buy", "sell"],
                    },
                    "order_type": {
                        "type": "string",
                        "description": "Order type",
                        "enum": ["market_order", "limit_order", "stop_limit", "take_profit_limit"],
                    },
                    "market": {"type": "string", "description": "Trading pair (e.g., 'BTCUSDT')"},
                    "price": {
                        "type": "number",
                        "description": "Price per unit (required for limit orders)",
                    },
                    "quantity": {
                        "type": "number",
                        "description": "Compatibility alias for total_quantity; provide only one",
                    },
                    "total_quantity": {
                        "type": "number",
                        "description": "Quantity to trade (required unless quantity alias is supplied)",
                    },
                    "client_order_id": {
                        "type": "string",
                        "description": "Custom order ID for tracking",
                    },
                },
                "required": ["side", "order_type", "market"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_order_status",
            description="Get status of a specific order",
            input_schema={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Order ID to check status for"}
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="cancel_order",
            description="Cancel an existing order",
            input_schema={
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "Order ID to cancel"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_active_orders",
            description="Get all active orders",
            input_schema={
                "type": "object",
                "properties": {
                    "market": {
                        "type": "string",
                        "description": "Filter by trading pair (optional)",
                    },
                    "side": {
                        "type": "string",
                        "description": "Filter by order side (optional)",
                        "enum": ["buy", "sell"],
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_order_history",
            description="Get executed account trades (not unfilled or cancelled orders). Side filtering applies to the returned page.",
            input_schema={
                "type": "object",
                "properties": {
                    "market": {
                        "type": "string",
                        "description": "Filter by trading pair (optional)",
                    },
                    "side": {
                        "type": "string",
                        "description": "Filter by order side (optional)",
                        "enum": ["buy", "sell"],
                    },
                    "from_timestamp": {
                        "type": "integer",
                        "description": "Start timestamp in milliseconds (optional)",
                    },
                    "to_timestamp": {
                        "type": "integer",
                        "description": "End timestamp in milliseconds (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of executed trades to retrieve (default: 500, max: 500)",
                        "minimum": 1,
                        "maximum": 500,
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_orders",
            description="List futures orders filtered by status and side",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Comma-separated order statuses (e.g. 'open' or 'open,filled'). Valid values: open, filled, partially_filled, partially_cancelled, cancelled, rejected, untriggered",
                    },
                    "side": {
                        "type": "string",
                        "description": "Order side",
                        "enum": ["buy", "sell"],
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)",
                        "minimum": 1,
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of records per page (default: 10)",
                        "minimum": 1,
                    },
                    "margin_currencies": {
                        "type": "array",
                        "description": "Futures margin modes (default: ['USDT']). Possible values: 'USDT', 'INR'",
                        "items": {"type": "string", "enum": ["USDT", "INR"]},
                    },
                },
                "required": ["status", "side"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="create_futures_order",
            description="Create a new futures order (limit, market, stop, or take-profit)",
            input_schema={
                "type": "object",
                "properties": {
                    "side": {
                        "type": "string",
                        "description": "Order side",
                        "enum": ["buy", "sell"],
                    },
                    "pair": {
                        "type": "string",
                        "description": "Futures instrument pair (e.g., 'B-BTC_USDT')",
                    },
                    "order_type": {
                        "type": "string",
                        "description": "Order type",
                        "enum": [
                            "market_order",
                            "limit_order",
                            "stop_limit",
                            "stop_market",
                            "take_profit_limit",
                            "take_profit_market",
                        ],
                    },
                    "total_quantity": {"type": "number", "description": "Order quantity"},
                    "price": {
                        "type": "number",
                        "description": "Limit price. Required for limit_order, stop_limit, take_profit_limit. Must be omitted for market orders.",
                    },
                    "stop_price": {
                        "type": "number",
                        "description": "Trigger price. Required for stop_limit, stop_market, take_profit_limit, take_profit_market.",
                    },
                    "leverage": {
                        "type": "integer",
                        "description": "Leverage for the position. Should match existing position leverage.",
                    },
                    "notification": {
                        "type": "string",
                        "description": "Notification preference (default: 'no_notification')",
                        "enum": ["no_notification", "email_notification"],
                    },
                    "time_in_force": {
                        "type": "string",
                        "description": "Time in force. Must be omitted for market orders.",
                        "enum": ["good_till_cancel", "fill_or_kill", "immediate_or_cancel"],
                    },
                    "margin_currency": {
                        "type": "string",
                        "description": "Futures margin mode (default: 'USDT')",
                        "enum": ["USDT", "INR"],
                    },
                    "position_margin_type": {
                        "type": "string",
                        "description": "Position margin type. Defaults to the existing position margin type.",
                        "enum": ["isolated", "crossed"],
                    },
                    "take_profit_price": {
                        "type": "number",
                        "description": "Take profit trigger price (for limit_order and market_order only)",
                    },
                    "stop_loss_price": {
                        "type": "number",
                        "description": "Stop loss trigger price (for limit_order and market_order only)",
                    },
                },
                "required": ["side", "pair", "order_type", "total_quantity"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="cancel_futures_order",
            description="Cancel an existing futures order by order ID",
            input_schema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The ID of the futures order to cancel",
                    }
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="list_futures_positions",
            description="List futures positions with optional margin currency filter",
            input_schema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)",
                        "minimum": 1,
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of records per page (default: 10)",
                        "minimum": 1,
                    },
                    "margin_currencies": {
                        "type": "array",
                        "description": "Futures margin modes to filter by (default: ['USDT']). Possible values: 'USDT', 'INR'",
                        "items": {"type": "string", "enum": ["USDT", "INR"]},
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_currency_conversion",
            description="Get the fixed USDT/INR conversion price used for INR-margined futures trading. This rate is set by CoinDCX and may change periodically due to extreme market movements.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="change_futures_position_margin_type",
            description="Change the margin type of a futures position between 'isolated' and 'crossed'. Only supported for USDT-margined futures. The position must have no active quantity and no open orders.",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Instrument pair name, e.g. 'B-BTC_USDT'",
                    },
                    "margin_type": {
                        "type": "string",
                        "enum": ["isolated", "crossed"],
                        "description": "New margin type: 'isolated' or 'crossed'",
                    },
                },
                "required": ["pair", "margin_type"],
            },
        ),
        types.Tool(
            name="edit_futures_order",
            description="Edit an open USDT-margined futures limit order. Updates the total quantity and/or price. Optionally update take profit and stop loss trigger prices. Only works for orders in open status.",
            input_schema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The ID of the futures order to edit",
                    },
                    "total_quantity": {
                        "type": "number",
                        "description": "New total quantity for the order",
                    },
                    "price": {"type": "number", "description": "New limit price for the order"},
                    "take_profit_price": {
                        "type": "number",
                        "description": "Optional new take profit trigger price (market/limit orders only)",
                    },
                    "stop_loss_price": {
                        "type": "number",
                        "description": "Optional new stop loss trigger price (market/limit orders only)",
                    },
                },
                "required": ["order_id", "total_quantity", "price"],
            },
        ),
        types.Tool(
            name="get_futures_wallet_transactions",
            description="Get a paginated list of futures wallet transactions (credits and debits) for USDT and INR futures wallets. Includes transfers, order-related transactions, and funding events.",
            input_schema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": "Page number (default: 1)"},
                    "size": {
                        "type": "integer",
                        "description": "Number of records per page (default: 1000)",
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="get_futures_wallet_details",
            description="Get futures wallet details for both USDT and INR wallets, including balance, locked margin, and cross-margin breakdowns. Total wallet balance = balance + locked_balance.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="transfer_futures_wallet",
            description="Transfer funds between the spot wallet and the futures wallet. Use transfer_type='deposit' to move funds into the futures wallet, or 'withdraw' to move them back to the spot wallet. Supports USDT and INR currencies.",
            input_schema={
                "type": "object",
                "properties": {
                    "transfer_type": {
                        "type": "string",
                        "enum": ["deposit", "withdraw"],
                        "description": "Direction of transfer: 'deposit' into futures wallet, 'withdraw' from futures wallet",
                    },
                    "amount": {"type": "number", "description": "Amount to transfer"},
                    "currency_short_name": {
                        "type": "string",
                        "enum": ["USDT", "INR"],
                        "description": "Currency to transfer. Default: 'USDT'",
                    },
                },
                "required": ["transfer_type", "amount"],
            },
        ),
        types.Tool(
            name="get_futures_cross_margin_details",
            description="Get cross margin account details for USDT-margined futures, including unrealised PnL, margin ratios, wallet balances, and available balances. Cross margin is not supported for INR-margined futures.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_pair_stats",
            description="Get statistics for a futures pair including price change percentages (1H/1D/1W/1M), high/low data, and long/short position sentiment.",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Instrument pair, e.g. 'B-ETH_USDT' or 'B-BTC_USDT'.",
                    }
                },
                "required": ["pair"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_current_prices_rt",
            description="Get real-time current prices for all active futures instruments, including last price, mark price, high, low, volume, price change percent, and funding rate.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_trades",
            description="Get futures trade history for a specific pair within a date range, optionally filtered by order ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "pair": {"type": "string", "description": "Instrument pair, e.g. 'B-ID_USDT'."},
                    "from_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format, e.g. '2024-01-01'.",
                    },
                    "to_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format, e.g. '2024-01-31'.",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1).",
                        "minimum": 1,
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of records per page (default: 10).",
                        "minimum": 1,
                    },
                    "order_id": {
                        "type": "string",
                        "description": "Optional order ID to filter trades for a specific order.",
                    },
                    "margin_currencies": {
                        "type": "array",
                        "description": "Futures margin modes to filter by (default: ['USDT']). Possible values: 'USDT', 'INR'.",
                        "items": {"type": "string", "enum": ["USDT", "INR"]},
                    },
                },
                "required": ["pair", "from_date", "to_date"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_transactions",
            description="Get futures transactions filtered by stage (funding, default, exit, tpsl_exit, liquidation, or all).",
            input_schema={
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "description": "Transaction stage: 'funding' (funding transactions), 'default' (standard order transactions), 'exit' (quick exit transactions), 'tpsl_exit' (full-position TP/SL exit transactions), 'liquidation' (liquidation transactions), 'all' (all types).",
                        "enum": ["funding", "default", "exit", "tpsl_exit", "liquidation", "all"],
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1).",
                        "minimum": 1,
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of records per page (default: 10).",
                        "minimum": 1,
                    },
                    "margin_currencies": {
                        "type": "array",
                        "description": "Futures margin modes to filter by (default: ['USDT']). Possible values: 'USDT', 'INR'.",
                        "items": {"type": "string", "enum": ["USDT", "INR"]},
                    },
                },
                "required": ["stage"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="create_futures_tpsl",
            description="Create Take Profit and/or Stop Loss orders for a futures position. Provide at least one of take_profit or stop_loss.",
            input_schema={
                "type": "object",
                "properties": {
                    "position_id": {
                        "type": "string",
                        "description": "The position ID to attach TP/SL orders to.",
                    },
                    "take_profit": {
                        "type": "object",
                        "description": "Take profit order parameters.",
                        "properties": {
                            "stop_price": {
                                "type": "string",
                                "description": "Trigger price for the take profit order.",
                            },
                            "order_type": {
                                "type": "string",
                                "description": "Order type for take profit.",
                                "enum": ["take_profit_market", "take_profit_limit"],
                            },
                            "limit_price": {
                                "type": "string",
                                "description": "Limit price (required for take_profit_limit orders).",
                            },
                        },
                        "required": ["stop_price", "order_type"],
                        "additionalProperties": False,
                    },
                    "stop_loss": {
                        "type": "object",
                        "description": "Stop loss order parameters.",
                        "properties": {
                            "stop_price": {
                                "type": "string",
                                "description": "Trigger price for the stop loss order.",
                            },
                            "order_type": {
                                "type": "string",
                                "description": "Order type for stop loss.",
                                "enum": ["stop_market", "stop_limit"],
                            },
                            "limit_price": {
                                "type": "string",
                                "description": "Limit price (required for stop_limit orders).",
                            },
                        },
                        "required": ["stop_price", "order_type"],
                        "additionalProperties": False,
                    },
                },
                "required": ["position_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="exit_futures_position",
            description="Exit a futures position entirely by placing a market close order. Large positions may be auto-split; use the returned group_id to track all child orders.",
            input_schema={
                "type": "object",
                "properties": {
                    "position_id": {"type": "string", "description": "The position ID to exit."}
                },
                "required": ["position_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="cancel_all_futures_open_orders_for_position",
            description="Cancel all open orders for a specific futures position identified by its position ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "position_id": {
                        "type": "string",
                        "description": "The position ID whose open orders should be cancelled.",
                    }
                },
                "required": ["position_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="cancel_all_futures_open_orders",
            description="Cancel all open futures orders across all positions for the specified margin mode(s).",
            input_schema={
                "type": "object",
                "properties": {
                    "margin_currencies": {
                        "type": "array",
                        "description": "Futures margin modes to cancel orders for (default: ['USDT']). Possible values: 'USDT', 'INR'.",
                        "items": {"type": "string", "enum": ["USDT", "INR"]},
                    }
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="remove_futures_margin",
            description="Remove margin from a futures position to increase its effective leverage. Removing margin raises liquidation risk.",
            input_schema={
                "type": "object",
                "properties": {
                    "position_id": {
                        "type": "string",
                        "description": "The position ID to remove margin from.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount of margin to remove. In USDT for USDT-margined futures, in INR for INR-margined futures.",
                    },
                },
                "required": ["position_id", "amount"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="add_futures_margin",
            description="Add margin to a futures position to decrease its effective leverage and update the liquidation price.",
            input_schema={
                "type": "object",
                "properties": {
                    "position_id": {
                        "type": "string",
                        "description": "The position ID to add margin to.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount of margin to add. In USDT for USDT-margined futures, in INR for INR-margined futures.",
                    },
                },
                "required": ["position_id", "amount"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="update_futures_position_leverage",
            description="Update the leverage for a futures position. Use either pair or position_id to target the position, not both.",
            input_schema={
                "type": "object",
                "properties": {
                    "leverage": {"type": "string", "description": "New leverage value, e.g. '5'"},
                    "pair": {
                        "type": "string",
                        "description": "Instrument pair, e.g. 'B-LTC_USDT'. Use this OR position_id.",
                    },
                    "position_id": {
                        "type": "string",
                        "description": "Position ID. Use this OR pair.",
                    },
                    "margin_currency": {
                        "type": "string",
                        "description": "Futures margin mode (default: 'USDT').",
                        "enum": ["USDT", "INR"],
                    },
                },
                "required": ["leverage"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="get_futures_positions_by_filter",
            description="Get futures positions filtered by specific pair(s) or position ID(s). Use either pairs or position_ids, not both.",
            input_schema={
                "type": "object",
                "properties": {
                    "pairs": {
                        "type": "string",
                        "description": "Comma-separated instrument pairs (e.g. 'B-BTC_USDT' or 'B-BTC_USDT,B-ETH_USDT'). Use this OR position_ids.",
                    },
                    "position_ids": {
                        "type": "string",
                        "description": "Comma-separated position IDs. Use this OR pairs.",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)",
                        "minimum": 1,
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of records per page (default: 10)",
                        "minimum": 1,
                    },
                    "margin_currencies": {
                        "type": "array",
                        "description": "Futures margin modes to filter by (default: ['USDT']). Possible values: 'USDT', 'INR'",
                        "items": {"type": "string", "enum": ["USDT", "INR"]},
                    },
                },
                "additionalProperties": False,
            },
        ),
    ]

    for tool in tools:
        schema = tool.input_schema
        _constrain_properties(schema)
        tool.annotations = types.ToolAnnotations(
            read_only_hint=tool.name in READ_TOOLS,
            destructive_hint=tool.name not in READ_TOOLS,
            idempotent_hint=tool.name in READ_TOOLS,
            open_world_hint=True,
        )
        if tool.name == "get_market_details":
            schema.pop("required", None)
        if tool.name in ("get_order_status", "cancel_order"):
            schema["properties"]["order_id"]["pattern"] = r"^[1-9][0-9]*$"
            schema["properties"]["order_id"]["description"] = (
                "Positive numeric spot order ID (UUIDs are unsupported)"
            )
        if "futures" in tool.name:
            for field in ("pair", "pairs"):
                if field in schema["properties"]:
                    schema["properties"][field]["pattern"] = (
                        r"^[A-Z0-9]+-[A-Z0-9]+_[A-Z0-9]+$"
                        if field == "pair"
                        else r"^[A-Z0-9]+-[A-Z0-9]+_[A-Z0-9]+(,[A-Z0-9]+-[A-Z0-9]+_[A-Z0-9]+)*$"
                    )
        if tool.name == "get_active_orders":
            schema["required"] = ["market"]
            schema["properties"]["page"] = {"type": "integer", "minimum": 1, "default": 1}
            schema["properties"]["size"] = {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "default": 200,
            }
            schema["properties"]["market"]["description"] = "Required spot market symbol"
        if tool.name == "get_order_history":
            schema["properties"]["from_id"] = {"type": "integer", "minimum": 0}
            schema["properties"]["sort"] = {
                "type": "string",
                "enum": ["asc", "desc"],
                "default": "asc",
            }
        if tool.name == "create_order":
            schema["properties"]["stop_price"] = {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Required trigger price for stop_limit and take_profit_limit",
            }
            schema["oneOf"] = [
                {"required": ["total_quantity"], "not": {"required": ["quantity"]}},
                {"required": ["quantity"], "not": {"required": ["total_quantity"]}},
            ]
            schema["allOf"] = [
                {
                    "if": {
                        "properties": {
                            "order_type": {
                                "enum": ["limit_order", "stop_limit", "take_profit_limit"]
                            }
                        }
                    },
                    "then": {"required": ["price"]},
                    "else": {"not": {"required": ["price"]}},
                }
            ]
        if tool.name == "create_order":
            schema["allOf"].append(
                {
                    "if": {
                        "properties": {"order_type": {"enum": ["stop_limit", "take_profit_limit"]}}
                    },
                    "then": {"required": ["stop_price"]},
                    "else": {"not": {"required": ["stop_price"]}},
                }
            )
        if tool.name in ("update_futures_position_leverage", "get_futures_positions_by_filter"):
            fields = (
                ("pair", "position_id")
                if tool.name.startswith("update")
                else ("pairs", "position_ids")
            )
            schema["oneOf"] = [
                {"required": [fields[0]], "not": {"required": [fields[1]]}},
                {"required": [fields[1]], "not": {"required": [fields[0]]}},
            ]
        if tool.name == "create_futures_tpsl":
            schema["anyOf"] = [{"required": ["take_profit"]}, {"required": ["stop_loss"]}]
            # Full-position TP/SL currently supports market variants only.
            schema["properties"]["take_profit"]["properties"]["order_type"]["enum"] = [
                "take_profit_market"
            ]
            schema["properties"]["stop_loss"]["properties"]["order_type"]["enum"] = ["stop_market"]
            for field in ("take_profit", "stop_loss"):
                schema["properties"][field]["properties"].pop("limit_price", None)
    return tools
