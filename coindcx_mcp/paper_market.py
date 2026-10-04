"""Public futures observations and local model calls. No exchange account access."""

import math
import re
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

INTERVALS = {"1m": ("1", 60_000), "5m": ("5", 300_000), "1h": ("60", 3_600_000)}
PUBLIC = "https://public.coindcx.com"


def positive(value):
    if isinstance(value, bool):
        raise ValueError("Invalid market number")
    number = float(value)
    if not math.isfinite(number) or not 1e-12 <= number <= 1e12:
        raise ValueError("Invalid market number")
    return number


@dataclass(frozen=True)
class PaperSettings:
    symbols: tuple[str, ...] = ("B-DOGE_USDT", "B-BTC_USDT", "B-ETH_USDT")
    interval: str = "1m"
    context: int = 512
    horizon: int = 4
    poll_seconds: float = 15
    initial_cash: float = 1000
    order_notional: float = 100
    fee_bps: float = 6
    slippage_bps: float = 2
    funding_bps_per_8h: float = 1
    signal_bps: float = 25
    stop_percent: float = 1
    target_percent: float = 2
    max_drawdown_percent: float = 10
    model_url: str = "http://127.0.0.1:8000"

    def __post_init__(self):
        if not self.symbols or len(self.symbols) > 4 or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Choose one to four unique symbols")
        if any(not re.fullmatch(r"[A-Z0-9]+-[A-Z0-9]+_USDT", s) for s in self.symbols):
            raise ValueError("Paper markets must be USDT futures pairs")
        if self.interval not in INTERVALS or not 32 <= self.context <= 998:
            raise ValueError("Unsupported interval or context")
        if not 1 <= self.horizon <= 16 or not 5 <= self.poll_seconds <= 300:
            raise ValueError("Invalid horizon or polling interval")
        for value in (
            self.initial_cash,
            self.order_notional,
            self.stop_percent,
            self.target_percent,
        ):
            positive(value)
        if self.order_notional > self.initial_cash / len(self.symbols):
            raise ValueError("One-times exposure must fit the virtual account")
        for value in (self.fee_bps, self.slippage_bps, self.funding_bps_per_8h, self.signal_bps):
            if not math.isfinite(value) or not 0 <= value <= 1000:
                raise ValueError("Invalid simulation cost or signal threshold")
        if not 0 < self.stop_percent < 50 or not 0 < self.target_percent < 50:
            raise ValueError("Invalid simulated exit threshold")
        if not 0 < self.max_drawdown_percent <= 50:
            raise ValueError("Invalid paper drawdown limit")
        url = urlparse(self.model_url)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("Forecast service must be a local HTTP origin")

    @property
    def interval_ms(self):
        return INTERVALS[self.interval][1]


def normalize_candles(data, interval_ms, now_ms):
    if (
        not isinstance(data, dict)
        or data.get("s") != "ok"
        or not isinstance(data.get("data"), list)
    ):
        raise ValueError("Invalid futures candle response")
    rows = {}
    for row in data["data"]:
        timestamp = row["time"]
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ValueError("Invalid candle timestamp")
        if timestamp % interval_ms:
            raise ValueError("Candle is not aligned to its interval")
        if timestamp + interval_ms > now_ms:
            continue
        close = positive(row["close"])
        if timestamp in rows and rows[timestamp] != close:
            raise ValueError("Conflicting candles")
        rows[timestamp] = close
    return rows


def parse_quote(data, now_ms):
    timestamp = data.get("ts")
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, int)
        or not -5000 <= now_ms - timestamp <= 30_000
    ):
        raise ValueError("Futures quote is stale or has an invalid timestamp")
    bids, asks = data.get("bids"), data.get("asks")
    if not isinstance(bids, dict) or not isinstance(asks, dict):
        raise ValueError("Invalid futures quote")
    bid = max(positive(price) for price, quantity in bids.items() if positive(quantity) > 0)
    ask = min(positive(price) for price, quantity in asks.items() if positive(quantity) > 0)
    if bid >= ask:
        raise ValueError("Crossed or locked futures quote")
    return {"bid": bid, "ask": ask, "timestamp_ms": timestamp, "received_ms": now_ms}


def parse_forecast(data, symbol, end_ms, horizon):
    if data.get("id") != symbol:
        raise ValueError("Forecast market does not match")
    if int(datetime.fromisoformat(data["context_end"]).timestamp() * 1000) != end_ms:
        raise ValueError("Forecast history timestamp does not match")
    prediction = data["prediction"]
    if prediction.get("backend") != "timesfm3":
        raise ValueError("Paper evaluation requires real TimesFM, not a mock baseline")
    rows = prediction["results"]
    if len(rows) != 1 or rows[0]["id"] != symbol or prediction["horizon"] != horizon:
        raise ValueError("Invalid forecast series or horizon")
    row = rows[0]
    values = [positive(value) for value in row["forecast"]]
    p10 = [positive(value) for value in row["quantiles"]["0.1"]]
    p90 = [positive(value) for value in row["quantiles"]["0.9"]]
    if len(values) != horizon or len(p10) != horizon or len(p90) != horizon:
        raise ValueError("Invalid forecast length")
    if any(low > high for low, high in zip(p10, p90)):
        raise ValueError("Crossed forecast quantiles")
    timing = prediction["timing"]
    for key in ("queue_ms", "inference_batch_ms", "service_ms"):
        if (
            not isinstance(timing[key], (int, float))
            or not math.isfinite(timing[key])
            or timing[key] < 0
        ):
            raise ValueError("Invalid forecast timing")
    return {"values": values, "p10": p10[-1], "p90": p90[-1], "timing": timing}


def decide(forecast, quote, settings):
    """An explicitly experimental paper rule, not a profitability claim."""
    costs = 2 * (settings.fee_bps + settings.slippage_bps)
    threshold = settings.signal_bps + costs
    predicted = forecast["values"][-1]
    if (predicted / quote["ask"] - 1) * 10_000 > threshold and forecast["p10"] > quote["ask"]:
        return 1, "Forecast and P10 exceed ask plus assumed costs"
    if (1 - predicted / quote["bid"]) * 10_000 > threshold and forecast["p90"] < quote["bid"]:
        return -1, "Forecast and P90 below bid beyond assumed costs"
    return 0, "No signal: forecast edge or uncertainty test was not met"


class PublicForecastFeed:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.cache = {}

    async def close(self):
        await self.http.aclose()

    async def quote(self, symbol):
        response = await self.http.get(f"{PUBLIC}/market_data/v3/orderbook/{symbol}-futures/10")
        response.raise_for_status()
        return parse_quote(response.json(), int(time.time() * 1000))

    async def candles(self, symbol, now_ms):
        interval = self.settings.interval_ms
        expected_end = now_ms // interval * interval
        cached = self.cache.get(symbol, {})
        if cached and max(cached) + interval == expected_end:
            return cached, expected_end, True
        # After a long suspension, bootstrap a bounded recent window instead of
        # requesting an ever-growing gap that upstream row limits may truncate.
        if cached and expected_end - (max(cached) + interval) >= self.settings.context * interval:
            cached = {}
        start = (
            max(cached) - interval
            if cached
            else expected_end - (self.settings.context + 3) * interval
        )
        response = await self.http.get(
            f"{PUBLIC}/market_data/candlesticks",
            params={
                "pair": symbol,
                "from": start // 1000,
                "to": now_ms // 1000,
                "resolution": INTERVALS[self.settings.interval][0],
                "pcode": "f",
            },
            timeout=5,
        )
        response.raise_for_status()
        fresh = normalize_candles(response.json(), interval, now_ms)
        for timestamp, close in fresh.items():
            if timestamp in cached and cached[timestamp] != close:
                raise ValueError("Completed candle was revised; refusing to reuse history")
        merged = dict(sorted({**cached, **fresh}.items())[-self.settings.context :])
        if len(merged) < self.settings.context:
            raise ValueError("Not enough completed futures candles")
        times = list(merged)
        if any(b - a != interval for a, b in zip(times, times[1:])):
            raise ValueError("Futures candles contain a gap")
        end = times[-1] + interval
        if expected_end - end > interval:
            raise ValueError("Completed futures candles are stale")
        self.cache[symbol] = merged
        return merged, end, False

    async def forecast(self, symbol, candles, end_ms):
        response = await self.http.post(
            self.settings.model_url.rstrip("/") + "/v1/forecast/candles",
            json={
                "id": symbol,
                "candles": [{"timestamp_ms": t, "close": p} for t, p in candles.items()],
                "interval_ms": self.settings.interval_ms,
                "context": self.settings.context,
                "horizon": self.settings.horizon,
                "return_quantiles": True,
                "require_fresh": True,
            },
        )
        response.raise_for_status()
        return parse_forecast(response.json(), symbol, end_ms, self.settings.horizon)
