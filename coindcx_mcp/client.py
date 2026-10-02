"""CoinDCX REST client. Signed writes are sent once, never automatically replayed."""

import hashlib
import hmac
import json
import math
import re
import time
from datetime import date
from typing import Any, Dict
from urllib.parse import urlsplit

import httpx


class CoinDCXError(RuntimeError):
    """An exchange or transport failure suitable for displaying to an MCP host."""


class CoinDCXClient:
    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        base_url: str = "https://api.coindcx.com",
        *,
        public_base_url: str = "https://public.coindcx.com",
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = self._validate_base_url(base_url)
        self.public_base_url = self._validate_base_url(public_base_url)
        self.client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0, pool=10.0),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            follow_redirects=False,
            transport=transport,
        )

    @staticmethod
    def _validate_base_url(value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("CoinDCX base URLs must be HTTPS origins without credentials or paths")
        return value.rstrip("/")

    def _generate_signature(self, payload: str) -> str:
        return hmac.new(self.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def _redact(self, message: str) -> str:
        for value in (self.api_key, self.secret_key):
            if value:
                message = message.replace(value, "[redacted]")
        return message[:500]

    def _request(
        self, method: str, url: str, *, payload=None, params=None, authenticated: bool = False
    ) -> Any:
        if authenticated and (not self.api_key or not self.secret_key):
            raise ValueError("Set COINDCX_API_KEY and COINDCX_SECRET_KEY for account tools")
        # GET reads may be retried; an uncertain POST may already have executed.
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            headers = {}
            content = None
            if authenticated:
                body = dict(payload or {})
                body["timestamp"] = int(time.time() * 1000)
                encoded = json.dumps(body, separators=(",", ":"), allow_nan=False)
                headers = {
                    "Content-Type": "application/json",
                    "X-AUTH-APIKEY": self.api_key,
                    "X-AUTH-SIGNATURE": self._generate_signature(encoded),
                }
                content = encoded.encode()
            try:
                response = self.client.request(
                    method, url, headers=headers, content=content, params=params
                )
            except httpx.RequestError as exc:
                if attempt + 1 < attempts:
                    time.sleep(0.25 * (2**attempt))
                    continue
                message = "CoinDCX request failed (network error or timeout)."
                if method != "GET":
                    message += (
                        " Outcome may be unknown; check order or wallet status before retrying."
                    )
                raise CoinDCXError(message) from exc
            if response.status_code in (429, 502, 503, 504) and attempt + 1 < attempts:
                try:
                    delay = float(response.headers.get("Retry-After", 0.25 * (2**attempt)))
                except ValueError:
                    delay = 0.25 * (2**attempt)
                time.sleep(min(max(delay, 0), 2.0) if math.isfinite(delay) else 0.25)
                continue
            if not response.is_success:
                detail = ""
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        detail = str(data.get("message", data.get("error", "")))
                except ValueError:
                    pass
                message = f"CoinDCX HTTP {response.status_code}"
                if detail:
                    message += ": " + self._redact(detail)
                if method != "GET" and response.status_code >= 500:
                    message += "; outcome may be unknown; check status before retrying"
                raise CoinDCXError(message)
            try:
                return response.json()
            except ValueError as exc:
                message = "CoinDCX returned an invalid JSON response"
                if method != "GET":
                    message += "; outcome may be unknown; check status before retrying"
                raise CoinDCXError(message) from exc

    def _make_authenticated_request(
        self, method: str, endpoint: str, payload: Dict[str, Any] | None = None, *, params=None
    ) -> Any:
        if method not in ("POST", "GET"):
            raise ValueError("Unsupported authenticated HTTP method")
        return self._request(
            method, f"{self.base_url}{endpoint}", payload=payload, params=params, authenticated=True
        )

    def _make_public_request(self, endpoint: str, params=None) -> Any:
        return self._request("GET", f"{self.base_url}{endpoint}", params=params)

    def _make_public_market_data_request(self, endpoint: str, params=None) -> Any:
        return self._request("GET", f"{self.public_base_url}{endpoint}", params=params)

    def _format_pair_for_public_api(self, pair: str) -> str:
        # Never invent or rewrite an exchange prefix (KC-, B-, I-, ...).
        pair = pair.strip().upper()
        if re.fullmatch(r"[A-Z0-9]+-[A-Z0-9]+_[A-Z0-9]+", pair):
            return pair
        market = self.get_market_details(pair)
        if not isinstance(market, dict) or not market.get("pair"):
            raise ValueError("Market details did not include a pair identifier")
        return market["pair"]

    @staticmethod
    def _positive(value, name: str) -> None:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a finite positive number")
        try:
            valid = math.isfinite(float(value)) and float(value) > 0
        except (ValueError, TypeError, OverflowError):
            valid = False
        if not valid:
            raise ValueError(f"{name} must be a finite positive number")

    @staticmethod
    def _spot_order_id(order_id: str) -> None:
        if not isinstance(order_id, str) or not re.fullmatch(r"[1-9][0-9]*", order_id):
            raise ValueError("Spot order_id must be a positive numeric string")

    # Public endpoints
    def get_ticker(self) -> Any:
        """Get ticker data for all markets."""
        return self._make_public_request("/exchange/ticker")

    def get_markets(self) -> Any:
        """Get all available markets."""
        return self._make_public_request("/exchange/v1/markets")

    def get_market_details(self, pair: str = None) -> Any:
        """Get market details. If pair is specified, filter for that specific trading pair."""
        all_markets = self._make_public_request("/exchange/v1/markets_details")

        if not isinstance(all_markets, list):
            raise CoinDCXError("Unexpected market details response")
        if pair is not None:
            query = pair.strip().upper()
            for market in all_markets:
                if any(
                    str(market.get(key, "")).upper() == query
                    for key in ("coindcx_name", "symbol", "pair")
                ):
                    return market
            raise ValueError("Trading pair not found in CoinDCX market details")
        return all_markets

    def get_trades(self, pair: str, limit: int = 30) -> Any:
        """Get recent trades for a market."""
        formatted_pair = self._format_pair_for_public_api(pair)
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        params = {"pair": formatted_pair, "limit": limit}
        return self._make_public_request("/market_data/trade_history", params)

    def get_order_book(self, pair: str) -> Any:
        """Get order book for a market."""
        formatted_pair = self._format_pair_for_public_api(pair)
        params = {"pair": formatted_pair}
        return self._make_public_request("/market_data/orderbook", params)

    def get_futures_active_instruments(self, margin_currency: str = "USDT") -> Any:
        """Get list of all active futures instruments.

        Args:
            margin_currency: Futures margin mode. Either 'USDT' (default) or 'INR'.

        Returns:
            List of active futures instrument pair strings (e.g. ['B-BTC_USDT', ...]).
        """
        params = {"margin_currency_short_name[]": margin_currency}
        return self._make_public_request(
            "/exchange/v1/derivatives/futures/data/active_instruments", params
        )

    def get_futures_instrument_details(self, pair: str, margin_currency: str = "USDT") -> Any:
        """Get detailed information about a specific futures instrument.

        Args:
            pair: Instrument pair name (e.g. 'B-BTC_USDT').
            margin_currency: Futures margin mode. Either 'USDT' (default) or 'INR'.

        Returns:
            Dict with 'instrument' key containing full instrument details such as
            leverage limits, fees, price/quantity increments, funding frequency, etc.
        """
        params = {"pair": pair, "margin_currency_short_name": margin_currency}
        return self._make_public_request("/exchange/v1/derivatives/futures/data/instrument", params)

    def get_futures_instrument_trades(self, pair: str) -> Any:
        """Get real-time trade history for a specific futures instrument.

        Args:
            pair: Instrument pair name (e.g. 'B-BTC_USDT').

        Returns:
            List of recent trades, each containing:
                - price: Price of the trade
                - quantity: Quantity of the trade
                - timestamp: EPOCH timestamp of the event (ms)
                - is_maker: True if the trade is a maker trade
        """
        params = {"pair": pair}
        return self._make_public_request("/exchange/v1/derivatives/futures/data/trades", params)

    def get_futures_instrument_orderbook(self, pair: str, depth: int = 50) -> Any:
        """Get order book for a specific futures instrument.

        Args:
            pair: Instrument pair name (e.g. 'B-BTC_USDT').
            depth: Order book depth. Valid values: 10, 20, 50 (default: 50).

        Returns:
            Dict containing:
                - ts: Epoch timestamp
                - vs: Version
                - asks: Dict of ask price -> quantity
                - bids: Dict of bid price -> quantity
        """
        if depth not in (10, 20, 50):
            raise ValueError("depth must be one of: 10, 20, 50")
        return self._make_public_market_data_request(
            f"/market_data/v3/orderbook/{pair}-futures/{depth}"
        )

    def get_futures_instrument_candlesticks(
        self, pair: str, resolution: str, from_time: int, to_time: int
    ) -> Any:
        """Get candlestick (OHLCV) data for a specific futures instrument.

        Args:
            pair: Instrument pair name (e.g. 'B-BTC_USDT').
            resolution: Candle resolution. Valid values:
                '1'  -> 1 minute
                '5'  -> 5 minutes
                '60' -> 1 hour
                '1D' -> 1 day
            from_time: EPOCH start timestamp in seconds.
            to_time: EPOCH end timestamp in seconds.

        Returns:
            Dict containing:
                - s: status ('ok' on success)
                - data: list of candles, each with open, high, low, close, volume, time
        """
        valid_resolutions = ("1", "5", "60", "1D")
        if resolution not in valid_resolutions:
            raise ValueError(f"resolution must be one of: {', '.join(valid_resolutions)}")
        if not 0 <= from_time <= to_time:
            raise ValueError("from_time must not be after to_time; use epoch seconds")
        params = {
            "pair": pair,
            "from": from_time,
            "to": to_time,
            "resolution": resolution,
            "pcode": "f",
        }
        return self._make_public_market_data_request("/market_data/candlesticks", params)

    def get_candles(
        self,
        pair: str,
        interval: str,
        start_time: int = None,
        end_time: int = None,
        limit: int = 100,
    ) -> Any:
        """Get spot candles for the exact requested range, in milliseconds."""
        if interval not in ("1m", "15m", "1h", "1d"):
            raise ValueError("Unsupported spot candle interval; use 1m, 15m, 1h, or 1d")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if start_time is not None and start_time < 0 or end_time is not None and end_time < 0:
            raise ValueError("Candle timestamps must be nonnegative milliseconds")
        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("start_time must not be after end_time")
        params = {
            "pair": self._format_pair_for_public_api(pair),
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._make_public_request("/market_data/candles", params)

    # User endpoints
    def get_balances(self) -> Any:
        """Get account balances."""
        return self._make_authenticated_request("POST", "/exchange/v1/users/balances")

    def get_user_info(self) -> Any:
        """Get user information."""
        return self._make_authenticated_request("POST", "/exchange/v1/users/info")

    # Order endpoints
    def create_order(
        self,
        side: str,
        order_type: str,
        market: str,
        price: float = None,
        quantity: float = None,
        total_quantity: float = None,
        client_order_id: str = None,
        stop_price: float = None,
    ) -> Any:
        """Create a new order."""
        if side not in ("buy", "sell") or order_type not in (
            "market_order",
            "limit_order",
            "stop_limit",
            "take_profit_limit",
        ):
            raise ValueError("Unsupported spot side or order_type")
        if quantity is not None and total_quantity is not None:
            raise ValueError("Provide total_quantity or its quantity alias, not both")
        amount = total_quantity if total_quantity is not None else quantity
        self._positive(amount, "total_quantity")
        if order_type in ("limit_order", "stop_limit", "take_profit_limit"):
            self._positive(price, "price")
        elif price is not None:
            raise ValueError("Omit price for market orders")
        if order_type in ("stop_limit", "take_profit_limit"):
            self._positive(stop_price, "stop_price")
        elif stop_price is not None:
            raise ValueError("stop_price is only valid for trigger orders")
        payload = {
            "side": side,
            "order_type": order_type,
            "market": market,
            "total_quantity": amount,
        }
        if price is not None:
            payload["price_per_unit"] = price
        if stop_price is not None:
            payload["stop_price"] = stop_price
        if client_order_id is not None:
            payload["client_order_id"] = client_order_id
        return self._make_authenticated_request("POST", "/exchange/v1/orders/create", payload)

    def get_order_status(self, order_id: str) -> Any:
        """Get order status."""
        self._spot_order_id(order_id)
        payload = {"id": order_id}
        return self._make_authenticated_request("POST", "/exchange/v1/orders/status", payload)

    def cancel_order(self, order_id: str) -> Any:
        """Cancel an order."""
        self._spot_order_id(order_id)
        payload = {"id": order_id}
        return self._make_authenticated_request("POST", "/exchange/v1/orders/cancel", payload)

    def get_active_orders(
        self, market: str, side: str = None, page: int = 1, size: int = 200
    ) -> Any:
        """Get active orders."""
        if not market or not market.strip():
            raise ValueError("market is required for active orders")
        if page < 1 or not 1 <= size <= 200:
            raise ValueError("page must be positive and size must be between 1 and 200")
        payload = {"page": page, "size": size}
        if market:
            payload["market"] = market
        if side:
            payload["side"] = side
        return self._make_authenticated_request(
            "POST", "/exchange/v1/orders/active_orders", payload
        )

    def get_order_history(
        self,
        market: str = None,
        side: str = None,
        from_timestamp: int = None,
        to_timestamp: int = None,
        limit: int = 500,
        from_id: int = None,
        sort: str = "asc",
    ) -> Any:
        """Get order history."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if (
            from_timestamp is not None
            and to_timestamp is not None
            and from_timestamp > to_timestamp
        ):
            raise ValueError("from_timestamp must not be after to_timestamp")
        if sort not in ("asc", "desc"):
            raise ValueError("sort must be asc or desc")
        payload = {"limit": limit, "sort": sort}
        if from_id is not None:
            if from_id < 0:
                raise ValueError("from_id must be nonnegative")
            payload["from_id"] = from_id
        if market:
            payload["symbol"] = market  # Use 'symbol' instead of 'market'
        if from_timestamp is not None:
            payload["from_timestamp"] = from_timestamp  # Correct parameter name
        if to_timestamp is not None:
            payload["to_timestamp"] = to_timestamp  # Correct parameter name
        result = self._make_authenticated_request(
            "POST", "/exchange/v1/orders/trade_history", payload
        )
        if side and isinstance(result, list):
            return [trade for trade in result if trade.get("side") == side]
        return result

    # Futures order endpoints
    def get_futures_orders(
        self, status: str, side: str, page: int = 1, size: int = 10, margin_currencies: list = None
    ) -> Any:
        """List futures orders filtered by status and side.

        Args:
            status: Comma-separated order statuses. Valid values:
                open, filled, partially_filled, partially_cancelled,
                cancelled, rejected, untriggered.
                Example: 'open' or 'open,filled'
            side: Order side. Either 'buy' or 'sell'.
            page: Page number (default: 1).
            size: Number of records per page (default: 10).
            margin_currencies: List of margin modes, e.g. ['USDT'] or ['INR', 'USDT'].
                Defaults to ['USDT'].

        Returns:
            List of futures order objects.
        """
        if margin_currencies is None:
            margin_currencies = ["USDT"]
        payload = {
            "status": status,
            "side": side,
            "page": str(page),
            "size": str(size),
            "margin_currency_short_name": margin_currencies,
        }
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/orders", payload
        )

    def create_futures_order(
        self,
        side: str,
        pair: str,
        order_type: str,
        total_quantity: float,
        notification: str = "no_notification",
        price: float = None,
        stop_price: float = None,
        leverage: int = None,
        time_in_force: str = None,
        margin_currency: str = "USDT",
        position_margin_type: str = None,
        take_profit_price: float = None,
        stop_loss_price: float = None,
    ) -> Any:
        """Create a new futures order.

        Args:
            side: Order side. 'buy' or 'sell'.
            pair: Futures instrument pair (e.g. 'B-BTC_USDT').
            order_type: One of: 'market_order', 'limit_order', 'stop_limit',
                'stop_market', 'take_profit_limit', 'take_profit_market'.
            total_quantity: Order quantity.
            notification: 'no_notification' (default) or 'email_notification'.
            price: Limit price. Required for limit, stop_limit, take_profit_limit
                orders. Must be None for market orders.
            stop_price: Trigger price. Required for stop_limit, stop_market,
                take_profit_limit, take_profit_market orders.
            leverage: Leverage for the position. Should match existing position
                leverage to avoid rejection.
            time_in_force: 'good_till_cancel', 'fill_or_kill', or
                'immediate_or_cancel'. Must be None for market orders.
            margin_currency: Futures margin mode. 'USDT' (default) or 'INR'.
            position_margin_type: 'isolated' or 'crossed'. Defaults to the
                existing position margin type if not provided.
            take_profit_price: Take profit trigger price (limit/market orders only).
            stop_loss_price: Stop loss trigger price (limit/market orders only).

        Returns:
            List containing the created futures order object.
        """
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        limit_types = ("limit_order", "stop_limit", "take_profit_limit")
        market_types = ("market_order", "stop_market", "take_profit_market")
        trigger_types = ("stop_limit", "stop_market", "take_profit_limit", "take_profit_market")
        if order_type not in limit_types + market_types:
            raise ValueError("Unsupported futures order_type")
        self._positive(total_quantity, "total_quantity")
        if order_type in limit_types:
            self._positive(price, "price")
        elif price is not None or time_in_force is not None:
            raise ValueError("Omit price and time_in_force for market variant orders")
        if order_type in trigger_types:
            self._positive(stop_price, "stop_price")
        elif stop_price is not None:
            raise ValueError("stop_price is only valid for trigger orders")
        if margin_currency == "INR" and position_margin_type == "crossed":
            raise ValueError("Cross margin is only supported for USDT futures")
        for value, name in (
            (leverage, "leverage"),
            (take_profit_price, "take_profit_price"),
            (stop_loss_price, "stop_loss_price"),
        ):
            if value is not None:
                self._positive(value, name)
        if order_type in trigger_types and (
            take_profit_price is not None or stop_loss_price is not None
        ):
            raise ValueError("Attached TP/SL prices are only valid for market_order or limit_order")
        order: Dict[str, Any] = {
            "side": side,
            "pair": pair,
            "order_type": order_type,
            "total_quantity": total_quantity,
            "notification": notification,
        }
        if price is not None:
            order["price"] = price
        if stop_price is not None:
            order["stop_price"] = stop_price
        if leverage is not None:
            order["leverage"] = leverage
        if time_in_force is not None:
            order["time_in_force"] = time_in_force
        if position_margin_type is not None:
            order["position_margin_type"] = position_margin_type
        if take_profit_price is not None:
            order["take_profit_price"] = take_profit_price
        if stop_loss_price is not None:
            order["stop_loss_price"] = stop_loss_price
        if margin_currency != "USDT":
            order["margin_currency_short_name"] = margin_currency

        payload = {"order": order}
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/orders/create", payload
        )

    def cancel_futures_order(self, order_id: str) -> Any:
        """Cancel an existing futures order.

        Args:
            order_id: The ID of the futures order to cancel.

        Returns:
            Confirmation response from the API.
        """
        payload = {"id": order_id}
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/orders/cancel", payload
        )

    def list_futures_positions(
        self, page: int = 1, size: int = 10, margin_currencies: list = None
    ) -> Any:
        """List futures positions.

        Args:
            page: Page number (default: 1).
            size: Number of records per page (default: 10).
            margin_currencies: List of margin modes to filter by, e.g. ['USDT']
                or ['INR', 'USDT']. Defaults to ['USDT'].

        Returns:
            List of futures position objects, each containing:
                - id: Position id (fixed per pair)
                - pair: Futures pair name
                - active_pos: Position quantity (negative for short)
                - avg_price: Average entry price
                - liquidation_price: Liquidation price (isolated margin only)
                - locked_margin: Margin locked in the position
                - leverage: Position leverage
                - maintenance_margin: Margin required to avoid liquidation
                - mark_price: Mark price at last update
                - margin_type: 'crossed' or 'isolated'
                - margin_currency_short_name: Futures margin mode
                - updated_at: Last updated timestamp
        """
        if margin_currencies is None:
            margin_currencies = ["USDT"]
        payload = {
            "page": str(page),
            "size": str(size),
            "margin_currency_short_name": margin_currencies,
        }
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions", payload
        )

    def get_futures_currency_conversion(self) -> Any:
        """Get the USDT <> INR currency conversion price used for INR-margined futures.

        CoinDCX notionally converts INR to USDT (and vice-versa) at a fixed
        conversion rate for INR futures. This rate may change periodically
        due to extreme market movements.

        Returns:
            List containing conversion rate objects, each with:
                - symbol: Symbol name (e.g. 'USDTINR')
                - margin_currency_short_name: 'INR'
                - target_currency_short_name: 'USDT'
                - conversion_price: Current fixed INR/USDT conversion rate
                - last_updated_at: Timestamp when the rate was last changed
        """
        return self._make_authenticated_request(
            "POST", "/api/v1/derivatives/futures/data/conversions", {}
        )

    def change_futures_position_margin_type(self, pair: str, margin_type: str) -> Any:
        """Change the margin type for a futures position between isolated and crossed.

        Only supported for USDT-margined futures. The position must have no
        active quantity and no open orders before the margin type can be changed.

        Args:
            pair: Instrument pair name, e.g. 'B-BTC_USDT'.
            margin_type: New margin type. Either 'isolated' or 'crossed'.

        Returns:
            List containing the updated position object, including:
                - id: Position id
                - pair: Futures pair name
                - active_pos: Current position quantity
                - margin_type: Updated margin type
                - leverage: Position leverage
                - locked_margin, locked_user_margin, locked_order_margin
                - take_profit_trigger, stop_loss_trigger
                - maintenance_margin, mark_price
                - updated_at: Last update timestamp
        """
        payload = {"pair": pair, "margin_type": margin_type}
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/margin_type", payload
        )

    def edit_futures_order(
        self,
        order_id: str,
        total_quantity: float,
        price: float,
        take_profit_price: float = None,
        stop_loss_price: float = None,
    ) -> Any:
        """Edit an open futures order's quantity and/or price.

        Only supported for USDT-margined futures. The order must be in open status.

        Args:
            order_id: The ID of the futures order to edit.
            total_quantity: New total quantity for the order.
            price: New limit price for the order.
            take_profit_price: Optional new take profit trigger price.
                Applies only to market_order or limit_order; ignored for
                reduce-only orders (no error raised).
            stop_loss_price: Optional new stop loss trigger price.
                Applies only to market_order or limit_order; ignored for
                reduce-only orders (no error raised).

        Returns:
            List containing the updated futures order object.
        """
        self._positive(total_quantity, "total_quantity")
        self._positive(price, "price")
        payload: Dict[str, Any] = {"id": order_id, "total_quantity": total_quantity, "price": price}
        if take_profit_price is not None:
            payload["take_profit_price"] = take_profit_price
        if stop_loss_price is not None:
            payload["stop_loss_price"] = stop_loss_price
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/orders/edit", payload
        )

    def get_futures_wallet_transactions(self, page: int = 1, size: int = 1000) -> Any:
        """Get a list of futures wallet transactions for both USDT and INR wallets.

        Args:
            page: Page number (default: 1).
            size: Number of records per page (default: 1000).

        Returns:
            List of transaction objects, each containing:
                - derivatives_futures_wallet_id: Futures wallet id
                - transaction_type: 'credit' (into futures wallet) or
                  'debit' (from futures wallet)
                - amount: Transaction amount
                - currency_short_name: Currency of the wallet
                - currency_full_name: Full name of the currency
                - reason: Reason for the transaction:
                    'by_universal_wallet' - transfers between spot and futures
                    'by_futures_order'    - transactions due to a futures order
                    'by_futures_funding'  - funding (cross-margined positions)
                - created_at: Timestamp when the transaction was created
        """
        endpoint = f"/exchange/v1/derivatives/futures/wallets/transactions?page={page}&size={size}"
        return self._make_authenticated_request("GET", endpoint, {})

    def get_futures_wallet_details(self) -> Any:
        """Get wallet details for the futures account (both USDT and INR wallets).

        Returns:
            List of wallet objects, each containing:
                - id: Futures wallet id
                - currency_short_name: Currency of the wallet ('USDT' or 'INR')
                - balance: Ignore this
                - locked_balance: Total initial margin locked in isolated
                  margined orders and positions
                - cross_order_margin: Total initial margin locked in
                  cross-margined orders
                - cross_user_margin: Total initial margin locked in
                  cross-margined positions

            Note: Total wallet balance = balance + locked_balance
        """
        return self._make_authenticated_request(
            "GET", "/exchange/v1/derivatives/futures/wallets", {}
        )

    def transfer_futures_wallet(
        self, transfer_type: str, amount: float, currency_short_name: str = "USDT"
    ) -> Any:
        """Transfer funds between the spot wallet and futures wallet.

        Args:
            transfer_type: Direction of transfer. Use 'deposit' to move funds
                into the futures wallet, or 'withdraw' to move funds out of
                the futures wallet back to the spot wallet.
            amount: Amount to transfer, denominated in `currency_short_name`.
            currency_short_name: Currency to transfer. 'USDT' (default) or 'INR'.

        Returns:
            List containing a wallet snapshot with:
                - id: Futures wallet transaction id
                - currency_short_name: Currency transferred
                - balance: Ignore this
                - locked_balance: Total initial margin locked in isolated orders/positions
                - cross_order_margin: Total initial margin locked in cross-margined orders
                - cross_user_margin: Total initial margin locked in cross-margined positions

            Note: Total wallet balance = balance + locked_balance
        """
        self._positive(amount, "amount")
        if transfer_type not in ("deposit", "withdraw"):
            raise ValueError("transfer_type must be deposit or withdraw")
        payload = {
            "transfer_type": transfer_type,
            "amount": amount,
            "currency_short_name": currency_short_name,
        }
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/wallets/transfer", payload
        )

    def get_futures_cross_margin_details(self) -> Any:
        """Get cross margin account details for USDT-margined futures.

        Returns unrealised PnL, margin ratios, wallet balances, and available
        balances for both cross and isolated margin modes.

        Note: Cross margin mode is not supported on INR-margined futures.

        Returns:
            Dict containing:
                - pnl: Unrealised PnL across all cross margin positions
                - maintenance_margin: Cumulative maintenance margin (cross positions)
                - total_wallet_balance: Total wallet balance (excl. active position PnL)
                - total_initial_margin: Cumulative initial margin (cross + isolated)
                - total_initial_margin_crossed: Initial margin for cross positions only
                - total_open_order_initial_margin_crossed: Margin locked in open orders
                - available_balance_cross: Balance available for cross margin trading
                - available_balance_isolated: Balance available for isolated margin trading
                - margin_ratio_cross: Cross margin ratio (liquidation if >= 1)
                - withdrawable_balance: Balance withdrawable to spot wallet
                - total_account_equity: total_wallet_balance + pnl
        """
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/cross_margin_details", {}
        )

    def get_futures_pair_stats(self, pair: str) -> Any:
        """Get statistics for a specific futures pair.

        Returns price change percentages (1H, 1D, 1W, 1M), high/low data,
        and position sentiment (long/short percentages by count and value).

        Args:
            pair: Instrument pair, e.g. 'B-ETH_USDT'.

        Returns:
            Dict containing:
                - price_change_percent: dict with 1H, 1D, 1W, 1M keys
                - high_and_low: dict with 1D and 1W high/low values
                - position: dict with count_percent and value_percent
                  (each with 'long' and 'short' keys)
        """
        # pair is sent as a URL query parameter; timestamp/signature go in the body
        return self._make_authenticated_request(
            "POST", "/api/v1/derivatives/futures/data/stats", {}, params={"pair": pair}
        )

    def get_futures_current_prices_rt(self) -> Any:
        """Get real-time current prices for all active futures instruments.

        Returns a snapshot with per-instrument fields including last price (ls),
        mark price (mp), high (h), low (l), volume (v), price change percent (pc),
        funding rate (fr), and various timestamps.

        Returns:
            Dict with 'ts' (timestamp), 'vs' (version), and 'prices' mapping
            each instrument pair to its current price data.
        """
        return self._make_public_market_data_request(
            "/market_data/v3/current_prices/futures/rt", {}
        )

    def get_futures_trades(
        self,
        pair: str,
        from_date: str,
        to_date: str,
        page: int = 1,
        size: int = 10,
        order_id: str = None,
        margin_currencies: list = None,
    ) -> Any:
        """Get futures trade history for a pair within a date range.

        Args:
            pair: Instrument pair, e.g. 'B-ID_USDT'.
            from_date: Start date in 'YYYY-MM-DD' format.
            to_date: End date in 'YYYY-MM-DD' format.
            page: Page number (default: 1).
            size: Number of records per page (default: 10).
            order_id: Optional order ID to filter trades for a specific order.
            margin_currencies: List of margin modes, e.g. ['USDT'] or ['INR', 'USDT'].
                Defaults to ['USDT'].

        Returns:
            List of trade objects with price, quantity, fees, side, etc.
        """
        if margin_currencies is None:
            margin_currencies = ["USDT"]
        if date.fromisoformat(from_date) > date.fromisoformat(to_date):
            raise ValueError("from_date must not be after to_date")
        payload: Dict[str, Any] = {
            "pair": pair,
            "from_date": from_date,
            "to_date": to_date,
            "page": str(page),
            "size": str(size),
            "margin_currency_short_name": margin_currencies,
        }
        if order_id:
            payload["order_id"] = order_id
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/trades", payload
        )

    def get_futures_transactions(
        self, stage: str, page: int = 1, size: int = 10, margin_currencies: list = None
    ) -> Any:
        """Get a list of futures transactions filtered by stage.

        Args:
            stage: Transaction stage to filter by. Possible values:
                'funding'     - Transactions due to funding.
                'default'     - Transactions for standard orders (non-exit, non-tpsl).
                'exit'        - Transactions for quick exit orders.
                'tpsl_exit'   - Transactions for full-position TP/SL exit orders.
                'liquidation' - Transactions for liquidation orders.
                'all'         - All transaction types.
            page: Page number (default: 1).
            size: Number of records per page (default: 10).
            margin_currencies: List of margin modes, e.g. ['USDT'] or ['INR', 'USDT'].
                Defaults to ['USDT'].

        Returns:
            List of transaction objects.
        """
        if margin_currencies is None:
            margin_currencies = ["USDT"]
        payload = {
            "stage": stage,
            "page": str(page),
            "size": str(size),
            "margin_currency_short_name": margin_currencies,
        }
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/transactions", payload
        )

    def create_futures_tpsl(
        self, position_id: str, take_profit: dict = None, stop_loss: dict = None
    ) -> Any:
        """Create Take Profit and/or Stop Loss orders for a futures position.

        At least one of take_profit or stop_loss must be provided.

        Args:
            position_id: The position ID to attach TP/SL orders to.
            take_profit: Dict with keys:
                - stop_price (str, required): Trigger price for the TP order.
                - order_type (str, required): 'take_profit_market'.
            stop_loss: Dict with keys:
                - stop_price (str, required): Trigger price for the SL order.
                - order_type (str, required): 'stop_market'.

        Returns:
            Dict with 'take_profit' and/or 'stop_loss' order details, including
            a 'success' flag and 'error' message on failure.
        """
        if not take_profit and not stop_loss:
            raise ValueError("At least one of 'take_profit' or 'stop_loss' must be provided.")
        for settings, expected in ((take_profit, "take_profit_market"), (stop_loss, "stop_market")):
            if settings is not None:
                if settings.get("order_type") != expected or "limit_price" in settings:
                    raise ValueError("Full-position TP/SL supports market variants only")
                self._positive(settings.get("stop_price"), "stop_price")
        payload: Dict[str, Any] = {"id": position_id}
        if take_profit:
            payload["take_profit"] = take_profit
        if stop_loss:
            payload["stop_loss"] = stop_loss
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/create_tpsl", payload
        )

    def exit_futures_position(self, position_id: str) -> Any:
        """Exit a futures position by placing a market order to close it entirely.

        Large positions may be auto-split into smaller orders; all split parts
        share the same group_id returned in the response.

        Args:
            position_id: The position ID to exit.

        Returns:
            Dict with message, status, code, and data.group_id.
        """
        payload = {"id": position_id}
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/exit", payload
        )

    def cancel_all_futures_open_orders_for_position(self, position_id: str) -> Any:
        """Cancel all open orders for a specific futures position.

        Args:
            position_id: The position ID whose open orders should be cancelled.

        Returns:
            Dict with message/status/code indicating success.
        """
        payload = {"id": position_id}
        return self._make_authenticated_request(
            "POST",
            "/exchange/v1/derivatives/futures/positions/cancel_all_open_orders_for_position",
            payload,
        )

    def cancel_all_futures_open_orders(self, margin_currencies: list = None) -> Any:
        """Cancel all open futures orders across all positions.

        Args:
            margin_currencies: List of margin modes to cancel orders for,
                e.g. ['USDT'] or ['INR', 'USDT']. Defaults to ['USDT'].

        Returns:
            Dict with message/status/code indicating success.
        """
        if margin_currencies is None:
            margin_currencies = ["USDT"]
        payload = {"margin_currency_short_name": margin_currencies}
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/cancel_all_open_orders", payload
        )

    def remove_futures_margin(self, position_id: str, amount: float) -> Any:
        """Remove margin from a futures position to increase effective leverage.

        Args:
            position_id: The position ID to remove margin from.
            amount: Amount of margin to remove. In USDT for USDT-margined futures,
                in INR for INR-margined futures. Removing margin increases the risk
                of the position (liquidation price will be updated).

        Returns:
            Dict with message/status/code indicating success.
        """
        self._positive(amount, "amount")
        payload = {"id": position_id, "amount": amount}
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/remove_margin", payload
        )

    def add_futures_margin(self, position_id: str, amount: float) -> Any:
        """Add margin to a futures position to decrease effective leverage.

        Args:
            position_id: The position ID to add margin to.
            amount: Amount of margin to add. In USDT for USDT-margined futures,
                in INR for INR-margined futures.

        Returns:
            Dict with message/status/code indicating success.
        """
        self._positive(amount, "amount")
        payload = {"id": position_id, "amount": amount}
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/add_margin", payload
        )

    def update_futures_position_leverage(
        self,
        leverage: str,
        pair: str = None,
        position_id: str = None,
        margin_currency: str = "USDT",
    ) -> Any:
        """Update the leverage for a futures position.

        Use either `pair` or `position_id` to target the position — not both.

        Args:
            leverage: New leverage value as a string, e.g. '5'.
            pair: Instrument pair, e.g. 'B-LTC_USDT'. Use this OR position_id.
            position_id: Position ID. Use this OR pair.
            margin_currency: Futures margin mode ('USDT' or 'INR'). Default 'USDT'.

        Returns:
            Dict with message/status/code indicating success or failure.
        """
        self._positive(leverage, "leverage")
        if bool(pair) == bool(position_id):
            raise ValueError("Provide exactly one of 'pair' or 'position_id'.")
        payload: Dict[str, Any] = {
            "leverage": str(leverage),
            "margin_currency_short_name": margin_currency,
        }
        if pair:
            payload["pair"] = pair
        if position_id:
            payload["id"] = position_id
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions/update_leverage", payload
        )

    def get_futures_positions_by_filter(
        self,
        page: int = 1,
        size: int = 10,
        pairs: str = None,
        position_ids: str = None,
        margin_currencies: list = None,
    ) -> Any:
        """Get futures positions filtered by pair(s) or position ID(s).

        Use either `pairs` or `position_ids` — not both.

        Args:
            page: Page number (default: 1).
            size: Number of records per page (default: 10).
            pairs: Comma-separated instrument pairs to filter by,
                e.g. 'B-BTC_USDT' or 'B-BTC_USDT,B-ETH_USDT'.
            position_ids: Comma-separated position IDs to filter by,
                e.g. '7830d2d6-0c3d-11ef-9b57-0fb0912383a7'.
            margin_currencies: List of margin modes, e.g. ['USDT'] or ['INR', 'USDT'].
                Defaults to ['USDT'].

        Returns:
            List of futures position objects matching the filter.
        """
        if bool(pairs) == bool(position_ids):
            raise ValueError("Provide exactly one of 'pairs' or 'position_ids'.")
        if margin_currencies is None:
            margin_currencies = ["USDT"]
        payload: Dict[str, Any] = {
            "page": str(page),
            "size": str(size),
            "margin_currency_short_name": margin_currencies,
        }
        if pairs:
            payload["pairs"] = pairs
        if position_ids:
            payload["position_ids"] = position_ids
        return self._make_authenticated_request(
            "POST", "/exchange/v1/derivatives/futures/positions", payload
        )

    def close(self):
        """Close the HTTP client."""
        self.client.close()
