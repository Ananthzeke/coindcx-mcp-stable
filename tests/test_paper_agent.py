import asyncio
import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from coindcx_mcp.paper_agent import PaperAgent, make_handler
from coindcx_mcp.paper_ledger import FUNDING_PERIOD, PaperLedger
from coindcx_mcp.paper_market import (
    PaperSettings,
    PublicForecastFeed,
    decide,
    normalize_candles,
    parse_forecast,
    parse_quote,
)

SYMBOL = "B-DOGE_USDT"
SETTINGS = PaperSettings(symbols=(SYMBOL,), context=32, horizon=2)


def quote(price, now=60_000):
    return {"bid": price, "ask": price + 0.01, "timestamp_ms": now, "received_ms": now}


def forecast(values=None):
    return {
        "values": values or [105, 110],
        "p10": 103,
        "p90": 115,
        "timing": {"queue_ms": 0, "service_ms": 3, "inference_batch_ms": 2, "batch_series": 1},
    }


def enter(ledger, side=1, price=100, now=60_000, end=60_000):
    q = quote(price, now)
    ledger.mark(SYMBOL, q)
    return ledger.record_signal(SYMBOL, end, price, forecast(), q, side, "test signal", now)


@pytest.mark.parametrize("side", [1, -1])
def test_long_and_short_accounting_and_replay(side, tmp_path):
    settings = replace(SETTINGS, stop_percent=10, target_percent=20)
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path, settings)
    assert enter(ledger, side)
    assert not enter(ledger, side)
    assert len(ledger.snapshot()["trades"]) == 1
    position = ledger.snapshot()["account"]["positions"][0]
    assert position["entry_fee"] == pytest.approx(0.06)
    exit_quote = quote(105 if side == 1 else 95, now=position["expiry_ms"])
    ledger.mark(SYMBOL, exit_quote)
    ledger.manage_position(SYMBOL, exit_quote, position["expiry_ms"])
    snapshot = ledger.snapshot()
    trade = snapshot["trades"][0]
    pnl = side * trade["quantity"] * (trade["exit"] - trade["entry"])
    fees = trade["entry_fee"] + trade["exit_fee"]
    assert trade["gross_pnl"] == pytest.approx(pnl)
    assert trade["net_pnl"] == pytest.approx(pnl - fees)
    assert snapshot["account"]["equity"] == pytest.approx(settings.initial_cash + pnl - fees)
    assert not snapshot["account"]["positions"]
    assert snapshot["closed_trades"] == 1
    assert snapshot["win_rate"] == 1
    ledger.close()
    reopened = PaperLedger(path, settings)
    assert reopened.has_signal(SYMBOL, 60_000)
    assert reopened.snapshot()["account"]["equity"] == pytest.approx(snapshot["account"]["equity"])
    reopened.close()


def test_stop_fills_at_observed_quote_not_old_stop(tmp_path):
    ledger = PaperLedger(tmp_path / "db", SETTINGS)
    enter(ledger)
    q = quote(90, now=80_000)
    ledger.mark(SYMBOL, q)
    ledger.manage_position(SYMBOL, q, 80_000)
    trade = ledger.snapshot()["trades"][0]
    assert trade["reason"] == "observed stop"
    assert trade["exit"] == pytest.approx(90 * (1 - SETTINGS.slippage_bps / 10_000))
    assert trade["exit"] < trade["stop"]
    ledger.close()


def test_pause_prevents_entry_but_allows_exit_and_drawdown_is_persisted(tmp_path):
    settings = replace(SETTINGS, stop_percent=20, max_drawdown_percent=0.1)
    ledger = PaperLedger(tmp_path / "db", settings)
    enter(ledger)
    ledger.set_paused(True)
    q = quote(90, now=180_000)
    ledger.mark(SYMBOL, q)
    ledger.manage_position(SYMBOL, q, 180_000)
    ledger.sample(180_000)
    assert ledger.snapshot()["closed_trades"] == 1
    assert ledger.snapshot()["max_drawdown_percent"] > 0.1
    ledger.set_paused(False)
    enter(ledger, now=180_000, end=180_000)
    assert not ledger.snapshot()["account"]["positions"]
    assert ledger.snapshot()["signals"][0]["reason"] == "Paper drawdown limit reached"
    ledger.close()


def test_paused_new_signal_and_profile_mismatch(tmp_path):
    path = tmp_path / "db"
    ledger = PaperLedger(path, SETTINGS)
    ledger.set_paused(True)
    enter(ledger)
    assert not ledger.snapshot()["trades"]
    assert ledger.snapshot()["signals"][0]["reason"] == "New paper trades paused"
    ledger.close()
    with pytest.raises(ValueError, match="different paper rules"):
        PaperLedger(path, replace(SETTINGS, fee_bps=10))


def test_funding_at_utc_boundaries_once(tmp_path):
    ledger = PaperLedger(tmp_path / "db", SETTINGS)
    now = FUNDING_PERIOD - 1000
    enter(ledger, now=now)
    q = quote(100, FUNDING_PERIOD + 1000)
    ledger.mark(SYMBOL, q)
    ledger.manage_position(SYMBOL, q, FUNDING_PERIOD + 1000)
    charged = ledger.snapshot()["account"]["funding"]
    qty = ledger.snapshot()["trades"][0]["quantity"]
    assert charged == pytest.approx(qty * 100.005 * 0.0001)
    ledger.manage_position(SYMBOL, q, FUNDING_PERIOD + 2000)
    assert ledger.snapshot()["account"]["funding"] == charged
    ledger.close()


def test_forward_evaluation_uses_only_future_closes(tmp_path):
    ledger = PaperLedger(tmp_path / "db", SETTINGS)
    ledger.set_paused(True)
    enter(ledger)
    ledger.evaluate(SYMBOL, {0: 100})
    assert ledger.snapshot()["scores"]["evaluated_windows"] == 0
    ledger.evaluate(SYMBOL, {0: 100, 60_000: 105, 120_000: 110})
    scores = ledger.snapshot()["scores"]
    assert scores["model_mape"] == 0
    assert scores["baseline_mape"] > 0
    assert scores["direction_accuracy"] == 1
    ledger.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"model_url": "https://remote.example"},
        {"model_url": "http://user:secret@localhost:8000"},
        {"model_url": "http://localhost:8000/redirect"},
        {"context": 1024},
        {"poll_seconds": 0},
        {"fee_bps": float("nan")},
        {"symbols": ("B-DOGE_INR",)},
        {"symbols": (SYMBOL, SYMBOL)},
    ],
)
def test_invalid_settings(changes):
    with pytest.raises(ValueError):
        replace(SETTINGS, **changes)


def test_incomplete_candles_excluded_and_stale_quotes_rejected():
    candles = normalize_candles(
        {
            "s": "ok",
            "data": [
                {"time": 0, "close": 100},
                {"time": 60_000, "close": 999},
            ],
        },
        60_000,
        80_000,
    )
    assert candles == {0: 100}
    with pytest.raises(ValueError, match="Conflicting"):
        normalize_candles(
            {"s": "ok", "data": [{"time": 0, "close": 100}, {"time": 0, "close": 101}]},
            60_000,
            80_000,
        )
    with pytest.raises(ValueError, match="stale"):
        parse_quote({"ts": 0, "bids": {"100": "1"}, "asks": {"101": "1"}}, 80_000)
    with pytest.raises(ValueError, match="Crossed"):
        parse_quote({"ts": 80_000, "bids": {"101": "1"}, "asks": {"100": "1"}}, 80_000)


def test_signal_requires_edge_and_supporting_uncertainty():
    assert decide(forecast(), quote(100), SETTINGS)[0] == 1
    assert decide({"values": [90, 89], "p10": 85, "p90": 95}, quote(100), SETTINGS)[0] == -1
    assert decide({"values": [90, 110], "p10": 85, "p90": 115}, quote(100), SETTINGS)[0] == 0
    assert (
        decide({"values": [100, 100.02], "p10": 100.01, "p90": 100.03}, quote(100), SETTINGS)[0]
        == 0
    )


def test_feed_cache_and_no_exchange_post_or_credentials():
    requests = []
    now = 60_000 * 100

    def handler(request):
        requests.append(request)
        assert "X-AUTH-APIKEY" not in request.headers
        assert "X-AUTH-SIGNATURE" not in request.headers
        assert request.method == "GET"
        assert request.url.host == "public.coindcx.com"
        assert request.url.params["pcode"] == "f"
        return httpx.Response(
            200,
            json={
                "s": "ok",
                "data": [{"time": t * 60_000, "close": 100 + t} for t in range(60, 101)],
            },
        )

    async def run():
        feed = PublicForecastFeed(SETTINGS, transport=httpx.MockTransport(handler))
        candles, end, cached = await feed.candles(SYMBOL, now)
        assert len(candles) == 32
        assert end == now and not cached
        assert max(candles) < now
        assert (await feed.candles(SYMBOL, now + 1000))[2]
        assert len(requests) == 1
        await feed.close()

    asyncio.run(run())


def test_forecast_mock_and_wrong_timestamp_rejected():
    payload = {
        "id": SYMBOL,
        "context_end": "1970-01-01T00:01:00+00:00",
        "prediction": {"backend": "mock"},
    }
    with pytest.raises(ValueError, match="real TimesFM"):
        parse_forecast(payload, SYMBOL, 60_000, 2)
    with pytest.raises(ValueError, match="timestamp"):
        parse_forecast(payload, SYMBOL, 120_000, 2)


def test_long_suspension_bootstraps_bounded_recent_history():
    requests = []

    def handler(request):
        requests.append(request)
        start = int(request.url.params["from"]) // 60
        end = int(request.url.params["to"]) // 60
        return httpx.Response(
            200,
            json={
                "s": "ok",
                "data": [{"time": i * 60_000, "close": 100 + i} for i in range(start, end + 1)],
            },
        )

    async def run():
        feed = PublicForecastFeed(SETTINGS, transport=httpx.MockTransport(handler))
        await feed.candles(SYMBOL, 100 * 60_000)
        candles, end, _ = await feed.candles(SYMBOL, 200 * 60_000)
        assert end == 200 * 60_000
        assert len(candles) == SETTINGS.context
        assert int(requests[-1].url.params["from"]) == (200 - SETTINGS.context - 3) * 60
        await feed.close()

    asyncio.run(run())


def test_worker_deduplicates_forecasts_and_does_not_backdate_fills(tmp_path):
    class Feed:
        forecasts = 0

        async def quote(self, symbol):
            return quote(100)

        async def candles(self, symbol, now):
            return {0: 100}, 60_000, True

        async def forecast(self, symbol, candles, end):
            self.forecasts += 1
            return forecast()

    ledger = PaperLedger(tmp_path / "db", SETTINGS)
    feed = Feed()
    agent = PaperAgent(SETTINGS, ledger, feed)

    async def run():
        await agent.step()
        await agent.step()

    asyncio.run(run())
    assert feed.forecasts == 1
    assert len(ledger.snapshot()["trades"]) == 1
    assert ledger.snapshot()["trades"][0]["opened_ms"] > 60_000
    assert ledger.snapshot()["health"][0]["error"] is None
    ledger.close()


def test_missing_model_still_exits_existing_paper_position(tmp_path):
    class Feed:
        async def quote(self, symbol):
            return quote(90)

        async def candles(self, symbol, now):
            raise httpx.ConnectError("model/data unavailable")

    ledger = PaperLedger(tmp_path / "db", SETTINGS)
    enter(ledger)
    agent = PaperAgent(SETTINGS, ledger, Feed())
    asyncio.run(agent.step())
    assert ledger.snapshot()["closed_trades"] == 1
    assert not ledger.snapshot()["account"]["positions"]
    assert ledger.snapshot()["health"][0]["error"]
    json.dumps(ledger.snapshot(), allow_nan=False)
    ledger.close()


def test_local_dashboard_origin_protection_and_pause(tmp_path):
    ledger = PaperLedger(tmp_path / "db", SETTINGS)
    http = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = http.server_address[1]
    http.RequestHandlerClass = make_handler(ledger, port)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=origin, trust_env=False, timeout=3) as client:
            assert client.get("/api/status").json()["mode"] == "paper-only"
            assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 403
            assert client.post("/api/pause", json={"paused": True}).status_code == 403
            assert (
                client.post(
                    "/api/pause", json={"paused": True}, headers={"Origin": "https://evil.example"}
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/pause", json={"paused": True}, headers={"Origin": origin}
                ).status_code
                == 200
            )
            assert client.get("/api/status").json()["paused"] is True
            assert client.get("/").status_code == 200
            assert client.get("/app.js").status_code == 200
            assert client.get("/trades.csv").text.startswith("id,symbol,direction")
            assert client.post("/api/live", json={}).status_code == 404
    finally:
        http.shutdown()
        http.server_close()
        ledger.close()
