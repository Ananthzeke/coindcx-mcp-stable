"""Durable paper-only accounting. Simulated fills never leave this SQLite file."""

import json
import sqlite3
import threading
from dataclasses import asdict

FUNDING_PERIOD = 8 * 60 * 60 * 1000


class PaperLedger:
    def __init__(self, path, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, direction INTEGER NOT NULL,
                quantity REAL NOT NULL, entry REAL NOT NULL, opened_ms INTEGER NOT NULL,
                expiry_ms INTEGER NOT NULL, stop REAL NOT NULL, target REAL NOT NULL,
                entry_fee REAL NOT NULL, funding REAL NOT NULL DEFAULT 0,
                funding_bucket INTEGER NOT NULL, exit REAL, closed_ms INTEGER,
                gross_pnl REAL NOT NULL DEFAULT 0, exit_fee REAL NOT NULL DEFAULT 0, reason TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS open_market ON trades(symbol) WHERE closed_ms IS NULL;
            CREATE TABLE IF NOT EXISTS signals (
                symbol TEXT NOT NULL, end_ms INTEGER NOT NULL, last_close REAL NOT NULL,
                forecast TEXT NOT NULL, direction INTEGER NOT NULL, reason TEXT NOT NULL,
                p10 REAL NOT NULL, p90 REAL NOT NULL, timing TEXT NOT NULL,
                created_ms INTEGER NOT NULL, model_mape REAL, baseline_mape REAL, hit INTEGER,
                PRIMARY KEY (symbol, end_ms)
            );
            CREATE TABLE IF NOT EXISTS quotes (
                symbol TEXT PRIMARY KEY, bid REAL NOT NULL, ask REAL NOT NULL,
                timestamp_ms INTEGER NOT NULL, received_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS health (
                symbol TEXT PRIMARY KEY, checked_ms INTEGER NOT NULL, error TEXT,
                cycle_ms REAL NOT NULL, cache_hit INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS equity (
                timestamp_ms INTEGER PRIMARY KEY, value REAL NOT NULL
            );
        """)
        profile = asdict(settings)
        # Operational timing/origin changes do not alter the evaluation's trading rules.
        for key in ("poll_seconds", "model_url"):
            profile.pop(key)
        encoded = json.dumps(profile, sort_keys=True)
        old = self.db.execute("SELECT value FROM meta WHERE key='profile'").fetchone()
        if old and old[0] != encoded:
            self.db.close()
            raise ValueError("This ledger uses different paper rules; choose a new database file")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('profile', ?)", (encoded,))
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('paused', 'false')")
            self.db.execute(
                "INSERT OR IGNORE INTO meta VALUES ('high_water', ?)", (str(settings.initial_cash),)
            )
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('max_drawdown', '0')")

    def close(self):
        with self.lock:
            self.db.close()

    def set_paused(self, paused):
        with self.lock, self.db:
            self.db.execute("UPDATE meta SET value=? WHERE key='paused'", (json.dumps(paused),))

    def meta(self, key):
        return self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0]

    def has_signal(self, symbol, end_ms):
        with self.lock:
            return (
                self.db.execute(
                    "SELECT 1 FROM signals WHERE symbol=? AND end_ms=?", (symbol, end_ms)
                ).fetchone()
                is not None
            )

    def mark(self, symbol, quote):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO quotes VALUES (?,?,?,?,?)",
                (symbol, quote["bid"], quote["ask"], quote["timestamp_ms"], quote["received_ms"]),
            )

    def exit_price(self, trade, quote):
        side = trade["direction"]
        price = quote["bid"] if side == 1 else quote["ask"]
        return price * (1 - side * self.settings.slippage_bps / 10_000)

    def totals(self):
        rows = [dict(row) for row in self.db.execute("SELECT * FROM trades")]
        fees = sum(row["entry_fee"] + row["exit_fee"] for row in rows)
        funding = sum(row["funding"] for row in rows)
        realized = sum(row["gross_pnl"] for row in rows)
        cash = self.settings.initial_cash + realized - fees - funding
        unrealized, anticipated_fees, exposure = 0.0, 0.0, 0.0
        positions = []
        for row in rows:
            if row["closed_ms"] is not None:
                continue
            quote = self.db.execute(
                "SELECT * FROM quotes WHERE symbol=?", (row["symbol"],)
            ).fetchone()
            price = self.exit_price(row, quote) if quote else row["entry"]
            pnl = row["direction"] * row["quantity"] * (price - row["entry"])
            unrealized += pnl
            anticipated_fees += row["quantity"] * price * self.settings.fee_bps / 10_000
            exposure += row["quantity"] * row["entry"]
            positions.append({**row, "mark": price, "unrealized_pnl": pnl})
        return {
            "equity": cash + unrealized - anticipated_fees,
            "cash": cash,
            "fees": fees,
            "funding": funding,
            "realized_gross_pnl": realized,
            "unrealized_pnl": unrealized,
            "exposure": exposure,
            "positions": positions,
        }

    def manage_position(self, symbol, quote, now_ms):
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM trades WHERE symbol=? AND closed_ms IS NULL", (symbol,)
            ).fetchone()
            if row is None:
                return
            bucket = now_ms // FUNDING_PERIOD
            intervals = max(0, bucket - row["funding_bucket"])
            mark = (quote["bid"] + quote["ask"]) / 2
            charge = intervals * row["quantity"] * mark * self.settings.funding_bps_per_8h / 10_000
            if intervals:
                self.db.execute(
                    "UPDATE trades SET funding=funding+?, funding_bucket=? WHERE id=?",
                    (charge, bucket, row["id"]),
                )
            price = self.exit_price(row, quote)
            side = row["direction"]
            reason = None
            if side * (price - row["stop"]) <= 0:
                reason = "observed stop"
            elif side * (price - row["target"]) >= 0:
                reason = "observed target"
            elif now_ms >= row["expiry_ms"]:
                reason = "holding horizon elapsed"
            if reason:
                pnl = side * row["quantity"] * (price - row["entry"])
                fee = row["quantity"] * price * self.settings.fee_bps / 10_000
                self.db.execute(
                    "UPDATE trades SET exit=?, closed_ms=?, gross_pnl=?, exit_fee=?, reason=? WHERE id=?",
                    (price, now_ms, pnl, fee, reason, row["id"]),
                )

    def record_signal(self, symbol, end_ms, last_close, forecast, quote, direction, reason, now_ms):
        with self.lock, self.db:
            if self.has_signal(symbol, end_ms):
                return False
            state = self.totals()
            high_water = max(float(self.meta("high_water")), state["equity"])
            drawdown = max(0, (1 - state["equity"] / high_water) * 100)
            if direction:
                if json.loads(self.meta("paused")):
                    direction, reason = 0, "New paper trades paused"
                elif drawdown >= self.settings.max_drawdown_percent:
                    direction, reason = 0, "Paper drawdown limit reached"
                elif any(row["symbol"] == symbol for row in state["positions"]):
                    direction, reason = 0, "Paper position already open"
                elif state["exposure"] + self.settings.order_notional > state["equity"]:
                    direction, reason = 0, "Insufficient virtual margin for one-times exposure"
            self.db.execute(
                "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
                (
                    symbol,
                    end_ms,
                    last_close,
                    json.dumps(forecast["values"]),
                    direction,
                    reason,
                    forecast["p10"],
                    forecast["p90"],
                    json.dumps(forecast["timing"]),
                    now_ms,
                ),
            )
            if direction:
                price = quote["ask"] if direction == 1 else quote["bid"]
                price *= 1 + direction * self.settings.slippage_bps / 10_000
                qty = self.settings.order_notional / price
                stop = price * (1 - direction * self.settings.stop_percent / 100)
                target = price * (1 + direction * self.settings.target_percent / 100)
                expiry = now_ms + self.settings.horizon * self.settings.interval_ms
                fee = self.settings.order_notional * self.settings.fee_bps / 10_000
                self.db.execute(
                    "INSERT INTO trades (symbol,direction,quantity,entry,opened_ms,expiry_ms,stop,"
                    "target,entry_fee,funding_bucket) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        symbol,
                        direction,
                        qty,
                        price,
                        now_ms,
                        expiry,
                        stop,
                        target,
                        fee,
                        now_ms // FUNDING_PERIOD,
                    ),
                )
            return True

    def evaluate(self, symbol, candles):
        with self.lock, self.db:
            rows = self.db.execute(
                "SELECT * FROM signals WHERE symbol=? AND model_mape IS NULL", (symbol,)
            ).fetchall()
            for row in rows:
                values = json.loads(row["forecast"])
                times = [row["end_ms"] + i * self.settings.interval_ms for i in range(len(values))]
                if not all(t in candles for t in times):
                    continue
                actual = [candles[t] for t in times]
                mape = sum(abs(p - a) / a for p, a in zip(values, actual)) / len(actual) * 100
                baseline = sum(abs(row["last_close"] - a) / a for a in actual) / len(actual) * 100
                predicted = values[-1] - row["last_close"]
                observed = actual[-1] - row["last_close"]
                hit = int(predicted * observed > 0) if predicted and observed else None
                self.db.execute(
                    "UPDATE signals SET model_mape=?, baseline_mape=?, hit=? WHERE symbol=? AND end_ms=?",
                    (mape, baseline, hit, symbol, row["end_ms"]),
                )

    def health(self, symbol, now_ms, elapsed_ms, error=None, cache_hit=False):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO health VALUES (?,?,?,?,?)",
                (symbol, now_ms, error, elapsed_ms, int(cache_hit)),
            )

    def sample(self, now_ms):
        with self.lock, self.db:
            equity = self.totals()["equity"]
            high = max(float(self.meta("high_water")), equity)
            drawdown = max(0.0, (1 - equity / high) * 100)
            maximum = max(float(self.meta("max_drawdown")), drawdown)
            self.db.execute("UPDATE meta SET value=? WHERE key='high_water'", (str(high),))
            self.db.execute("UPDATE meta SET value=? WHERE key='max_drawdown'", (str(maximum),))
            self.db.execute("INSERT OR REPLACE INTO equity VALUES (?,?)", (now_ms, equity))
            self.db.execute(
                "DELETE FROM equity WHERE timestamp_ms NOT IN "
                "(SELECT timestamp_ms FROM equity ORDER BY timestamp_ms DESC LIMIT 10000)"
            )

    def snapshot(self):
        with self.lock:
            state = self.totals()
            trades = [
                dict(row)
                for row in self.db.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 100")
            ]
            for row in trades:
                row["net_pnl"] = (
                    row["gross_pnl"] - row["entry_fee"] - row["exit_fee"] - row["funding"]
                )
            closed = self.db.execute(
                "SELECT COUNT(*) AS n, AVG(CASE WHEN gross_pnl-entry_fee-exit_fee-funding>0 "
                "THEN 1. ELSE 0. END) AS win_rate FROM trades WHERE closed_ms IS NOT NULL"
            ).fetchone()
            score = dict(
                self.db.execute(
                    "SELECT COUNT(model_mape) AS evaluated_windows, AVG(model_mape) AS model_mape, "
                    "AVG(baseline_mape) AS baseline_mape, AVG(hit) AS direction_accuracy FROM signals"
                ).fetchone()
            )
            latest = [
                dict(row)
                for row in self.db.execute(
                    "SELECT s.* FROM signals s JOIN (SELECT symbol,MAX(end_ms) AS e FROM signals "
                    "GROUP BY symbol) m ON s.symbol=m.symbol AND s.end_ms=m.e"
                )
            ]
            for row in latest:
                row["forecast"] = json.loads(row["forecast"])
                row["timing"] = json.loads(row["timing"])
            return {
                "mode": "paper-only",
                "settings": asdict(self.settings),
                "paused": json.loads(self.meta("paused")),
                "account": state,
                "return_percent": (state["equity"] / self.settings.initial_cash - 1) * 100,
                "max_drawdown_percent": float(self.meta("max_drawdown")),
                "closed_trades": closed["n"],
                "win_rate": closed["win_rate"],
                "scores": score,
                "signals": latest,
                "trades": trades,
                "health": [dict(row) for row in self.db.execute("SELECT * FROM health")],
                "quotes": [dict(row) for row in self.db.execute("SELECT * FROM quotes")],
                "equity_history": [
                    dict(row)
                    for row in self.db.execute(
                        "SELECT * FROM (SELECT * FROM equity ORDER BY timestamp_ms DESC LIMIT 200) "
                        "ORDER BY timestamp_ms"
                    )
                ],
            }

    def export_rows(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM trades ORDER BY id")]
