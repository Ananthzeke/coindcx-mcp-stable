# Local paper forecasting agent

This is a private evaluation companion for the running local TimesFM service. It
observes CoinDCX **futures** markets, simulates long and short positions, and keeps
a virtual trade journal. It does not load exchange credentials, import the
authenticated CoinDCX client, or have a live trading switch. No OpenAI API key is
used. Account balances and the live MCP connections are separate.

TimesFM 3.0 weights are restricted to non-commercial, non-production evaluation.
See [Google's model license](https://huggingface.co/google/timesfm-3.0-pytorch/blob/main/LICENSE).
The model outputs are not validated trading signals or probabilities of profit.
This lab is for evaluating the model, not commercial decision-making.

## Run

Keep the TimesFM app running at `http://127.0.0.1:8000`, then from this project:

```sh
uv sync --locked
./scripts/run-paper-agent.sh
```

Open **http://127.0.0.1:8011**. The worker checks every 15 seconds and automatically
records simulated trades when its experimental entry rule is met. The dashboard
shows virtual equity, net return, observed drawdown, costs, open positions, the
trade journal, current forecast decisions, worker health, and inference timing.
An empty journal means no qualifying signal has been observed; forecasts do not
force entries. The **Pause new paper trades** button is persistent; existing
positions continue to be monitored and can close while new entries are paused.

`Ctrl+C` stops the worker and dashboard. The journal resumes from
`.local/paper-agent.sqlite3` on the next launch. It is ignored by Git. Only one
worker may own a ledger at a time. The agent runs while this computer and model
service are available; this command does not install a login or reboot service.

For a diagnostic observation cycle without a dashboard:

```sh
./scripts/run-paper-agent.sh --once --db /tmp/paper-diagnostic.sqlite3
```

Symbols, candle interval, context, horizon, local model URL, dashboard port, and
ledger path are configurable through `--help`. Changing the trading rules or
market set requires a new ledger file to avoid mixing incomparable results.
The default 512-candle context is intentionally retained; adding more history
does not establish a better model or trading edge.

## Default experiment

| Setting | Assumption |
| --- | --- |
| Markets | DOGE, BTC, ETH USDT futures |
| Observations | 512 completed 1-minute candles |
| Forecast | 4 future candle closes |
| Virtual starting balance | 1000 USDT |
| Simulated entry size | 100 USDT notional per market |
| Exposure | 1×; one open position per market; no pyramiding |
| Fee | 6 basis points per side, a simulation assumption |
| Extra slippage | 2 basis points per side, in addition to observed spread |
| Funding | 1 basis point charged per UTC 8-hour boundary, an estimate |
| Entry | More than 25 bp forecast move plus round-trip assumed costs; terminal P10/P90 must support the direction |
| Exit | Next observed stop at 1%, target at 2%, or 4-minute maximum hold |
| Entry pause | 10% observed drawdown from virtual equity high-water mark |

Costs are illustrative assumptions, **not a quote of current CoinDCX fees**.
Funding always charges the simulated account; it does not model funding receipts
or reproduce live funding history. Model quantile bands are not calibrated
confidence levels. Entry logic uses the final forecast and fresh ask/bid after
inference. There is no entry at an earlier historical close, no backfilled trade
history, and no replay of an already recorded candle signal.

Exits use the observed bid for longs and ask for shorts plus unfavorable slippage,
even if the price has moved beyond a stop. Polling can miss changes between
checks. During downtime, positions stay open until a new valid quote arrives;
missed exits are not invented. Equity includes estimated costs to close current
positions. Cash deducts entry/exit fees and estimated funding. Contract lot sizes,
liquidity consumed by the order, exchange liquidation, maintenance margin, and
exact funding settlements are not reproduced. These limits mean paper returns
cannot be treated as achievable live returns.

## Speed and evidence

The agent calls the existing model directly over loopback HTTP. It keeps HTTP
connections open and observes markets concurrently so the GPU scheduler can
batch forecasts. Completed candle history is retained in memory; later fetches
request only a short tail. The model is called once per new completed candle,
while quotes and existing paper exits are checked every 15 seconds. It does not
run an LLM between ticks or load another GPU model.

Completed forward windows are scored against subsequently observed futures
closes. The dashboard reports model mean absolute percentage error beside the
last-price baseline, plus terminal direction accuracy. These rolling windows
overlap and are not independent samples. A lower forecast error need not imply a
profitable trading strategy. Net paper P&L is measured separately after costs.

Public price data uses the official [CoinDCX futures candle and orderbook endpoints](https://docs.coindcx.com/#get-instrument-candlesticks).
Unfinished candles, gaps, conflicting revisions, stale quotes, malformed outputs,
and the mock forecast backend prevent new paper entries. Existing positions can
still exit from valid quotes when the model is unavailable. Worker errors are
visible in the dashboard rather than replaced with invented observations.

Tests isolate exchange traffic. They verify long/short accounting, fees, estimated
funding, stop gaps, drawdown, pausing, journal restart, deduplication, future-only
forecast scoring, cache reuse, invalid model/quote data, and local dashboard
Host/Origin checks. The only POST to a forecasting endpoint is to the local
model; exchange requests are public GETs.
