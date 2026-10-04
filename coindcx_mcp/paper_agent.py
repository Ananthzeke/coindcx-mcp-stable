"""Local paper evaluation worker and dashboard, isolated from live trading tools."""

import argparse
import asyncio
import csv
import fcntl
import io
import json
import logging
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from .paper_ledger import PaperLedger
from .paper_market import PaperSettings, PublicForecastFeed, decide

logger = logging.getLogger(__name__)
ASSETS = Path(__file__).parent


class PaperAgent:
    def __init__(self, settings, ledger, feed):
        self.settings, self.ledger, self.feed = settings, ledger, feed
        self.stopping = asyncio.Event()

    async def market_step(self, symbol):
        start = time.perf_counter()
        cache_hit = False
        error = None
        try:
            quote = await self.feed.quote(symbol)
            now = int(time.time() * 1000)
            self.ledger.mark(symbol, quote)
            # Existing positions can exit even if forecasting is unavailable or entries are paused.
            self.ledger.manage_position(symbol, quote, now)
            candles, end, cache_hit = await self.feed.candles(symbol, now)
            self.ledger.evaluate(symbol, candles)
            if not self.ledger.has_signal(symbol, end):
                forecast = await self.feed.forecast(symbol, candles, end)
                # A fill uses a fresh observed quote after inference, never an earlier candle close.
                quote = await self.feed.quote(symbol)
                now = int(time.time() * 1000)
                self.ledger.mark(symbol, quote)
                self.ledger.manage_position(symbol, quote, now)
                direction, reason = decide(forecast, quote, self.settings)
                self.ledger.record_signal(
                    symbol, end, candles[max(candles)], forecast, quote, direction, reason, now
                )
        except httpx.HTTPStatusError as exc:
            error = f"Data or forecast service returned HTTP {exc.response.status_code}"
        except httpx.HTTPError:
            error = "Data or forecast service could not be reached; no new paper trade"
        except (ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
            error = str(exc) if isinstance(exc, ValueError) else "Invalid data or forecast response"
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            self.ledger.health(symbol, int(time.time() * 1000), elapsed, error, cache_hit)

    async def step(self):
        await asyncio.gather(*(self.market_step(symbol) for symbol in self.settings.symbols))
        self.ledger.sample(int(time.time() * 1000))

    async def run(self):
        try:
            while not self.stopping.is_set():
                start = time.monotonic()
                await self.step()
                wait = max(0.1, self.settings.poll_seconds - (time.monotonic() - start))
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.feed.close()


def make_handler(ledger, port):
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, body, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def check_host(self):
            if self.headers.get("Host") not in hosts:
                self.send(403, b'{"error":"Localhost access required"}')
                return False
            return True

        def do_GET(self):
            if not self.check_host():
                return
            if self.path == "/api/status":
                data = {**ledger.snapshot(), "now_ms": int(time.time() * 1000)}
                self.send(200, json.dumps(data, allow_nan=False).encode())
            elif self.path in {"/", "/app.js"}:
                name = "paper_dashboard.html" if self.path == "/" else "paper_dashboard.js"
                content_type = "text/html; charset=utf-8" if self.path == "/" else "text/javascript"
                self.send(200, (ASSETS / name).read_bytes(), content_type)
            elif self.path == "/trades.csv":
                rows = ledger.export_rows()
                stream = io.StringIO()
                columns = [
                    "id",
                    "symbol",
                    "direction",
                    "quantity",
                    "entry",
                    "opened_ms",
                    "exit",
                    "closed_ms",
                    "gross_pnl",
                    "entry_fee",
                    "exit_fee",
                    "funding",
                    "reason",
                ]
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
                self.send(200, stream.getvalue().encode(), "text/csv; charset=utf-8")
            else:
                self.send(404, b'{"error":"Not found"}')

        def do_POST(self):
            if not self.check_host():
                return
            if self.path != "/api/pause":
                self.send(404, b'{"error":"Not found"}')
                return
            if self.headers.get("Origin") not in origins:
                self.send(403, b'{"error":"Same-origin request required"}')
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 256:
                    raise ValueError()
                self.connection.settimeout(3)
                body = json.loads(self.rfile.read(size))
                if set(body) != {"paused"} or not isinstance(body["paused"], bool):
                    raise ValueError()
                ledger.set_paused(body["paused"])
                self.send(200, b'{"ok":true}')
            except (ValueError, TypeError, TimeoutError):
                self.send(400, b'{"error":"Invalid pause request"}')

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="Private forecasting evaluation; paper trades only"
    )
    parser.add_argument("--symbols", nargs="+", default=list(PaperSettings().symbols))
    parser.add_argument("--interval", choices=["1m", "5m", "1h"], default="1m")
    parser.add_argument("--context", type=int, default=512)
    parser.add_argument("--horizon", type=int, default=4)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--model-url", default="http://127.0.0.1:8000")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument(
        "--db", type=Path, default=Path(__file__).parent.parent / ".local/paper-agent.sqlite3"
    )
    parser.add_argument(
        "--once", action="store_true", help="One observation cycle, without serving a dashboard"
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose an unprivileged local port")
    settings = PaperSettings(
        symbols=tuple(args.symbols),
        interval=args.interval,
        context=args.context,
        horizon=args.horizon,
        poll_seconds=args.poll_seconds,
        model_url=args.model_url,
    )
    args.db.parent.mkdir(parents=True, exist_ok=True)
    lock = args.db.with_suffix(args.db.suffix + ".lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        parser.error("A paper agent already owns this ledger")
    ledger = PaperLedger(args.db, settings)
    feed = PublicForecastFeed(settings)
    agent = PaperAgent(settings, ledger, feed)
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    async def run():
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, agent.stopping.set)
        if args.once:
            try:
                await agent.step()
                print(json.dumps(ledger.snapshot(), allow_nan=False))
            finally:
                await feed.close()
        else:
            await agent.run()

    http = None
    try:
        if not args.once:
            http = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(ledger, args.port))
            threading.Thread(target=http.serve_forever, daemon=True).start()
            logger.info("Paper evaluation dashboard: http://127.0.0.1:%s", args.port)
        asyncio.run(run())
    finally:
        if http:
            http.shutdown()
            http.server_close()
        ledger.close()
        lock.close()


if __name__ == "__main__":
    main()
