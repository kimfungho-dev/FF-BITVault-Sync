# FF-BITVault-Sync

Source code: https://github.com/kimfungho-dev/FF-BITVault-Sync

## What this is

FF-BITVault-Sync is a desktop warehouse for hourly BTCUSDT and ETHUSDT spot candles (OHLCV, quote volume, trade count, and taker buy flow) plus the daily Crypto Fear & Greed index. It stores them in a local SQLite file, `bitvault.db`. No API key is required.

The window title is **FF-BITVault-Sync — Quantitative Crypto Data Warehouse**. The header logo reads **FF-BITVAULT-SYNC**.

## What you need

- Python 3.10 or newer
- An internet connection the first time you load history, and again when you sync
- Tkinter, which ships with python.org builds. On Linux install it if the window does not open: `sudo apt install python3-tk`
- On Windows, leave **tcl/tk and IDLE** checked in the python.org installer

The submitted folder is three files: `bitvault_sync.py`, `README.md`, and `requirements.txt`. You do not need git to run it.

## Run in 3 steps

From the folder that contains those three files:

```bash
pip install -r requirements.txt
python3 bitvault_sync.py
```

On Windows, use `py -m pip install -r requirements.txt` and `py bitvault_sync.py`.

Then click **Initialize Database** once. When that finishes, use **Sync Database** for later updates. Sync does not download the history again.

The program writes `bitvault.db` next to `bitvault_sync.py`, even if you started it from another folder. On a python.org macOS install, if HTTPS fails with a certificate error, run **Install Certificates.command** from the Python folder in Applications and start the app again.

## Run in VS Code

1. **File → Open Folder** and choose the folder that contains `bitvault_sync.py`.
2. **Python: Select Interpreter** and pick Python 3.10 or newer (Command Palette, or the interpreter name in the status bar).
3. Open a terminal (**Terminal → New Terminal**) and run `pip install -r requirements.txt`.
4. Open `bitvault_sync.py` and choose **Run → Run Python File**.

If the terminal says `ModuleNotFoundError: No module named 'requests'` or `No module named 'pydantic'`, the Run button is using a different interpreter from the one that received `pip install`. Select that same interpreter, install again, and run the file once more.

If Python starts and no window appears, Tkinter is missing. On Linux run `sudo apt install python3-tk`. On Windows, reinstall Python from python.org with **tcl/tk and IDLE** checked. Then run the file again.

## Button behaviour

**Initialize Database** is the only action that downloads the full history. It creates `symbols`, `hourly_klines`, and `daily_fear_greed`, then downloads the hourly history from 2026-09-01 00:00:00 UTC (or the earlier fallback if the exchange clock has not reached that date). Until that load has stored BTCUSDT rows, Initialize stays enabled and is the emphasized button. The helper says: "One-time setup: create tables + full history since 2026-09-01 UTC". The status line reads: "Start here: click Initialize Database to create tables and load history since 2026-09-01 UTC."

If BTCUSDT already has rows, Initialize asks:

> The warehouse is already initialized (<N> rows, last record <timestamp> UTC). For routine updates use Sync Database, which only fetches new hours. Re-run the full historical download anyway?

Yes runs the full download again. The primary key upsert refreshes existing hours instead of duplicating them. No leaves the database unchanged and writes `[INITIALIZE] Skipped by user: database already initialized.` to the activity log.

**Sync Database** and **Auto-Sync** are enabled only after initialization. Before that they are greyed out, and the tooltip on both is "Initialize the database first". Sync never downloads the full history. It reads `MAX(open_time)` and fetches only that hour plus any hours that have opened since. The helper, once Sync is enabled, says: "Incremental: fetch only hours after the last stored record".

If `hourly_klines` does not exist, or BTCUSDT has no rows, Sync makes no kline requests. It logs `[SYNC] Skipped: database not initialized. Click Initialize Database first.` and returns. That skip is not a failure: the status line stays on the start-here message, and no error dialog opens.

A badge beside the buttons reads SQLite when the window opens and again after every job:

- Red `● Not initialized` when `hourly_klines` is missing or BTCUSDT has 0 rows.
- Green `● Initialized · <N> rows` otherwise. `<N>` is the BTCUSDT hourly row count.

## Candle status

The Market Microstructure grid has a **Status** column. It is computed when the row is drawn, from the candle's stored `close_time` and the current UTC time in milliseconds. It is not a database column.

- **LIVE** when `close_time >=` now. The row is drawn in amber. That hour is still forming, so open, high, low, close, and volume can change on the next Sync.
- **CLOSED** otherwise. Use these rows for backtesting.

Above the grid, while this view is selected: `LIVE = candle still forming; values update on next Sync. Use CLOSED rows for backtesting.`

## Auto-Sync

**Auto-Sync: OFF** sits to the right of **Sync Database**. It is off, and disabled, until Initialize has stored BTCUSDT rows. Turning it on before that does nothing. After initialization, turning it on runs one incremental sync immediately, unless a job or a dialog is already open, then arms a Tk `after` timer for 5 minutes. The button reads `Auto-Sync: ON · next HH:MM:SS UTC`. When the timer fires it calls the same incremental sync as **Sync Database** and writes `[AUTO-SYNC]` to the activity log. If a job is already running, or a confirmation dialog is open, that tick is skipped and the next one is scheduled 5 minutes later. If Auto-Sync is on and the warehouse is no longer initialized, it switches off and the log says why. Turning it off cancels the timer.

## Verify Integrity

**Verify Integrity** is the secondary button immediately after **Sync Database**. It runs on the background thread, prints each statement in the activity log, and then opens a message box:

- Duplicate keys: `SELECT symbol, open_time, COUNT(*) FROM hourly_klines GROUP BY symbol, open_time HAVING COUNT(*) > 1`. Expect 0 rows.
- Gaps, per symbol: a `LEAD(open_time)` window over `hourly_klines`, counting rows where `next_open - open_time != 3600000`, plus any hours after the last candle through the Binance server hour. Expect 0.
- Expected versus actual hourly rows for each symbol, from its first `open_time` through the later of the last stored hour and the Binance server hour.
- Duplicate Fear & Greed dates: `SELECT date_str, COUNT(*) FROM daily_fear_greed GROUP BY date_str HAVING COUNT(*) > 1`. Expect 0.

The check only reads the database. It does not add columns, tables, or rows.

## Export CSV

**Export CSV** is the secondary button after Verify Integrity. It asks for a path with the default name `ff_bitvault_hourly_<YYYYMMDD_HHMM>.csv` and writes that file with the standard-library `csv` module. Each BTCUSDT hour is joined to the ETHUSDT close on `open_time` and to Fear & Greed on the UTC date of that hour. Columns:

`open_time_utc`, `btc_open`, `btc_high`, `btc_low`, `btc_close`, `btc_volume`, `btc_quote_volume`, `btc_trades`, `btc_taker_buy_pct`, `eth_close`, `btc_eth_ratio`, `fear_greed_value`, `fear_greed_class`, `candle_status`.

`candle_status` uses the same LIVE / CLOSED rule as the grid, evaluated when the file is written. The activity log records the row count and the path.

## What the terminal shows

The window title is `FF-BITVault-Sync — Quantitative Crypto Data Warehouse`. The header logo is `FF-BITVAULT-SYNC`. The header subtitle is `Automated Spot OHLCV, Order-Flow Microstructure & Macro Sentiment Ingestion Engine`.

Five primary controls stay on screen with these exact labels:

| Control | What it does |
| --- | --- |
| **Initialize Database** | Creates the tables and indexes, then downloads the full hourly history in pages of 1000. Runs on a background thread. |
| **Sync Database** | Reads `MAX(open_time)` for `BTCUSDT` and downloads only that candle plus any hours that have opened since. |
| **Total Row Count** | The big number is every stored record: `symbols` + `hourly_klines` + `daily_fear_greed`. The lines under it break that into BTCUSDT klines, ETHUSDT klines, Fear & Greed, and symbols. |
| **First Record Timestamp** | UTC open time of the earliest `BTCUSDT` candle, `YYYY-MM-DD HH:MM:SS UTC`. |
| **Last Record Timestamp** | UTC open time of the latest `BTCUSDT` candle, including the hour that is still forming. |

A fourth card, **Warehouse Enrichment & Health**, sits beside them. It shows the latest Fear & Greed print as `value (classification)` (for example `28 (Fear)`), the latest **BTC/ETH Ratio** (`BTCUSDT close / ETHUSDT close` on the newest shared hour), and **Continuity** (`0 Missing Hours / Verified` when neither symbol has a gap).

Under the cards, three radio buttons switch the grid across the relational tables:

| View | What it shows |
| --- | --- |
| **Market Microstructure (BTC & ETH Joined)** | Latest 15 BTCUSDT hours joined to the ETHUSDT close, plus a **Status** column (`LIVE` in amber, or `CLOSED`). Prices are `76,014.00` style. `1h Chg %` is `(Close - Open) / Open`, shown as `+0.24%` or `-0.56%`, and a closed row is green or red. `Vol (BTC)` is two decimals. `Quote Vol (USDT)` is millions (`$35.62M`). `Taker Buy %` is `taker_buy_base_volume / volume`. |
| **Macro Sentiment (daily_fear_greed table)** | Every stored day: `Date (UTC)`, `Timestamp`, `F&G Index (0-100)`, `Market Regime / Classification`. |
| **Warehouse Schema & Assets (symbols table + DB stats)** | The `symbols` dimension rows, table row counts, and the named indexes. |

The activity log at the bottom records each API call (`startTime` and the number of rows returned), each SQL statement, and each `COMMIT`.

The progress bar and the status line update while a job runs. The window stays responsive because network and database work never run on the Tkinter thread.

## API keys

FF-BITVault-Sync does not use an API key. Binance public market data (`/api/v3/time` and `/api/v3/klines` for `BTCUSDT` and `ETHUSDT`) and the Alternative.me Fear & Greed index (`https://api.alternative.me/fng/`) are keyless. The funding-rate and 24-hour ticker fallbacks are public endpoints as well. No key is embedded in the source, and nothing has to be exported or pasted in before the program will run.

## Data sources

| Series | Endpoint | Grain |
| --- | --- | --- |
| Server clock | `GET https://api.binance.com/api/v3/time` | Used before every load to decide the history window |
| Spot candles | `GET https://api.binance.com/api/v3/klines` | 1 hour, symbols `BTCUSDT` and `ETHUSDT` |
| Fear & Greed | `GET https://api.alternative.me/fng/?limit=0` | 1 day, no API key |
| Fallback 1 | `GET https://fapi.binance.com/fapi/v1/fundingRate` | Used only when Fear & Greed cannot be reached |
| Fallback 2 | `GET https://api.binance.com/api/v3/ticker/24hr` | Used only when funding history also fails |

Every call goes through `requests.get(url, params=params, timeout=15)` followed immediately by `response.raise_for_status()`. JSON is validated with pydantic (`KlineRecord`, `FundingRateRecord`, `FearGreedRecord`) before it is inserted. A candle whose high/low/open/close relationship is impossible is skipped and reported in the log. It is not written.

Binance kline array fields are stored as follows:

| Index | Binance field | Column |
| --- | --- | --- |
| 0 | Open time | `open_time` |
| 1 | Open | `open_price` |
| 2 | High | `high_price` |
| 3 | Low | `low_price` |
| 4 | Close | `close_price` |
| 5 | Base asset volume | `volume` |
| 6 | Close time | `close_time` |
| 7 | Quote asset volume | `quote_asset_volume` |
| 8 | Number of trades | `number_of_trades` |
| 9 | Taker buy base volume | `taker_buy_base_volume` |
| 10 | Taker buy quote volume | `taker_buy_quote_volume` |

The last four numeric columns are the extra microstructure and order-flow measures kept on the hourly fact table. `open_datetime` is the UTC rendering of `open_time` in the form `YYYY-MM-DD HH:MM:SS`.

## Network fallback

Spot market data is requested from `https://api.binance.com` first. If that host returns HTTP 451 or 403, or the connection fails, the same path is tried on `https://data-api.binance.vision`. The activity log records `[HOST] switched to data-api.binance.vision`, and that host is reused for the rest of the session. The three paths that fail over are `/api/v3/time`, `/api/v3/klines`, and `/api/v3/ticker/24hr`. HTTP 451 and 403 are not retried on the same host. The local clock is used for the history window only after every time host has failed. Funding-rate history stays on `fapi.binance.com`.

## History window

History is stored from **1 September 2026 00:00:00 UTC**. The source also keeps the constant `1756684800000`. Those two are not the same instant:

| Constant | UTC instant |
| --- | --- |
| `1788220800000` | 2026-09-01 00:00:00 |
| `1756684800000` (`START_TIMESTAMP_MS`) | 2025-09-01 00:00:00 |

On startup of a load, the app reads `serverTime` from Binance and chooses the start as follows.

| Binance `serverTime` | Start used |
| --- | --- |
| On or after 1 Sep 2026 | `1788220800000` (1 Sep 2026) |
| Before 1 Sep 2026, but after 1 Sep 2025 | `1756684800000` (the printed constant) |
| Before 1 Sep 2025 | 67 days before `serverTime`, floored to the hour |

The chosen start and the reason are written to the activity log. Candles are then requested through the current Binance hour, so the latest row is the in-progress hour rather than yesterday's close. If `/api/v3/time` itself cannot be reached, the local UTC clock is used and a warning is logged.

From 1 Sep 2026 to early November 2026 is about 1,600 hourly candles per symbol, which is two pages of `limit=1000`.

## Schema

`bitvault.db` has three tables. `PRAGMA foreign_keys = ON` is set on every connection. SQLite only enforces the foreign key while that pragma is on.

`symbols` is the instrument dimension. Base asset, quote asset, and market type depend on the symbol alone, so they are stored once.

```sql
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    base_asset TEXT NOT NULL,
    quote_asset TEXT NOT NULL,
    market_type TEXT NOT NULL
);
```

Seed rows:

| symbol | base_asset | quote_asset | market_type |
| --- | --- | --- | --- |
| BTCUSDT | BTC | USDT | SPOT |
| ETHUSDT | ETH | USDT | SPOT |

`hourly_klines` is the fact table. Its grain is one row per symbol per hour. Open, high, low, close, volume, and the microstructure measures are attributes of that hour, so they belong on this table. Copying `base_asset` onto every candle would repeat a `symbols` attribute and break third normal form.

```sql
CREATE TABLE IF NOT EXISTS hourly_klines (
    symbol TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    open_datetime TEXT NOT NULL,
    open_price REAL NOT NULL,
    high_price REAL NOT NULL,
    low_price REAL NOT NULL,
    close_price REAL NOT NULL,
    volume REAL NOT NULL,
    close_time INTEGER NOT NULL,
    quote_asset_volume REAL NOT NULL,
    number_of_trades INTEGER NOT NULL,
    taker_buy_base_volume REAL NOT NULL,
    taker_buy_quote_volume REAL NOT NULL,
    PRIMARY KEY (symbol, open_time),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
);

CREATE INDEX IF NOT EXISTS idx_klines_open_time ON hourly_klines (open_time);
CREATE INDEX IF NOT EXISTS idx_klines_symbol ON hourly_klines (symbol);
```

The composite primary key makes a second row for the same symbol and hour impossible. The foreign key makes a candle for an unknown symbol impossible. `idx_klines_open_time` supports the time-range and `MIN` / `MAX` lookups used by the dashboard. `idx_klines_symbol` supports symbol filters. The primary key already indexes `(symbol, open_time)`; the extra symbol index matches the lookup the sync uses when it filters to one instrument.

`daily_fear_greed` is a different grain: one row per UTC day for the whole market, not per symbol. It is its own table rather than a column on `hourly_klines`. A daily value does not determine an hourly candle, and an hourly candle does not determine the day's index, so neither table should hold the other's measures.

```sql
CREATE TABLE IF NOT EXISTS daily_fear_greed (
    timestamp INTEGER PRIMARY KEY,
    date_str TEXT NOT NULL,
    value INTEGER NOT NULL,
    value_classification TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fear_greed_date ON daily_fear_greed (date_str);
```

`ux_fear_greed_date` is a unique index on `date_str`. Before it is created, rows that share a date are reduced to the one with the latest `timestamp`. New Fear & Greed rows upsert on `date_str`, so a day cannot fan out into two sentiment rows. The CSV export also joins each hour to that single date row.

`timestamp` is UTC midnight in milliseconds. Alternative.me publishes Unix seconds; the loader multiplies by 1000. `value` for the live index is the published 0–100 score, and `value_classification` is the published label (`Fear`, `Neutral`, `Greed`, and the extreme labels).

If Alternative.me cannot be reached, daily BTCUSDT funding rates are aggregated to one row per UTC day. `value` is then `funding_rate × 1,000,000` (so a rate of `0.0001` is stored as `100`) and `value_classification` is prefixed with `Funding fallback (BTCUSDT)`. If funding history also fails, one row is stored from the spot 24-hour ticker and labelled `Ticker 24h fallback`. The next successful Fear & Greed load upserts the real index back onto that date. Kline loading still finishes when every sentiment source fails; the failure is written to the log.

**Total Row Count** adds four `COUNT(*)` results: BTCUSDT hourly rows, ETHUSDT hourly rows, Fear & Greed days, and `symbols`. First and Last Record Timestamp still come from:

```sql
SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = 'BTCUSDT';
```

The market view joins ETHUSDT onto BTCUSDT on `open_time` and keeps the newest 15 Bitcoin hours, including quote volume and taker-buy base volume so the terminal can show quote turnover and taker share. A horizontal scrollbar under the grid reaches the Status column when the window is narrower than the column set.

## How a full load works

**Initialize Database** does all of the following.

1. Create `symbols`, `hourly_klines`, and `daily_fear_greed` if they are missing, create the indexes, and upsert the two symbol rows.
2. Read Binance `serverTime` and resolve the history start described above.
3. Request `BTCUSDT` 1h klines with `startTime` at that start and `limit=1000`.
4. Validate every array with `KlineRecord` and batch-insert it:

   ```sql
   INSERT INTO hourly_klines (...) VALUES (...)
   ON CONFLICT(symbol, open_time) DO UPDATE SET
       open_price = excluded.open_price,
       high_price = excluded.high_price,
       ...
   ```

   The batch is `cursor.executemany(...)`, then `conn.commit()`.
5. If the page contains 1000 rows, set `startTime = last_open_time + 3600_000` and repeat. A short page, an empty page, or a cursor that fails to move ends the loop.
6. Repeat the same paging for `ETHUSDT`.
7. Audit stored open times. Any missing hour is requested on its own, with `endTime` set to that gap. Hours the exchange simply does not have are reported and left absent.
8. Download Fear & Greed with `limit=0`, keep dates on or after the history start, and upsert them.

Running Initialize again is safe. The primary key plus `ON CONFLICT DO UPDATE` refreshes rows that already exist instead of inserting duplicates.

## How incremental sync works

Fetching the whole history on every refresh is the wrong implementation. **Sync Database** asks SQLite what it already has, then asks Binance only for the tail.

1. If `hourly_klines` does not exist, or `SELECT MAX(open_time) FROM hourly_klines WHERE symbol = 'BTCUSDT'` returns `NULL`, Sync stops. The log line is `[SYNC] Skipped: database not initialized. Click Initialize Database first.` No kline request is sent. The full download stays on **Initialize Database**.
2. Otherwise the log records the exact line:

   ```text
   [INCREMENTAL SYNC] Last DB Timestamp: YYYY-MM-DD HH:MM:SS UTC -> Fetching ONLY delta records from YYYY-MM-DD HH:MM:SS UTC to now...
   ```

3. The kline request uses `startTime = last_open_time` (the stored value itself, not one hour after it). That single choice does two things:
   - The hour that was still forming at the previous sync is updated with the latest high, low, close, volume, and trade count.
   - Every hour that has opened since that timestamp is included. Closed hours already stored below `last_open_time` are not requested.
4. The same `while` loop pages this short window. In practice the response is one page of one or two candles, not a 1000-row page.
5. `ON CONFLICT(symbol, open_time) DO UPDATE` writes the fresh OHLC and volume for the overlapping hour. New hours are inserted. The log then reports `new` and `updated` separately. `new` is the change in `COUNT(*)`. `updated` is the rest of the batch.
6. ETHUSDT is synced from its own `MAX(open_time)`. If that symbol is missing, only ETHUSDT is loaded from the history start. BTCUSDT is not downloaded again.
7. Fear & Greed uses `SELECT MAX(timestamp)` and requests only the overlapping day plus any newer days (`limit` is the number of elapsed days plus two). The full `limit=0` history is reserved for the first load.
8. A local gap check walks open times from the first stored hour through the Binance server hour. Each contiguous run of missing hours is its own request, with that run's `startTime` and `endTime`. Hours already stored are not included, even when there are many separate holes. If the exchange hour is still missing after that fetch, those hours stay in the log and the line is not `Continuity OK`. A clean database makes no extra kline call here.

After a sync inside the same clock hour, the BTCUSDT row count stays the same, `updated` is 1, and `new` is 0, while the latest close and volume can change. After an hour boundary, `new` is 1 (or more, if several hours were skipped) and the previous hour is the updated row.

## Suggested check

1. Click **Initialize Database**. Wait until the status returns to Ready and the log shows `COMMIT` plus `[INITIALIZE] Complete`.
2. Confirm **Total Row Count** is greater than 1,000, **First Record Timestamp** is `2026-09-01 00:00:00 UTC` (when Binance's clock is past that date), and **Last Record Timestamp** is the current UTC hour. **Warehouse Enrichment & Health** should show a Fear & Greed value, a BTC/ETH ratio, and `0 Missing Hours / Verified`. The default grid is **Market Microstructure (BTC & ETH Joined)** with 15 rows, a `1h Chg %` column, and an ETH close. Switch to the sentiment and schema radios to inspect `daily_fear_greed` and `symbols`.
3. Click **Sync Database**.
4. In the log, confirm the `[INCREMENTAL SYNC] Last DB Timestamp: ...` line, and confirm the following kline call uses that same `startTime` and returns a handful of rows rather than 1000.
5. Confirm the row count is unchanged if you are still inside the same hour, and that the log reports `new=0` and `updated=1` for BTCUSDT.
6. Click **Sync Database** once more. The same delta behaviour should repeat. The log must not show a second walk from 1 Sep 2026.

The activity log is plain text. Select it and copy if you want to attach it to a report.

## Known limitations

- Quote notionals (`quote_asset_volume` and `taker_buy_quote_volume`) are stored as SQLite `REAL`. A value near 1e8 can differ from Binance's 8-decimal string by `1e-8`, because float64 cannot hold 17 significant digits. Open, high, low, close, and base volume round-trip exactly.
- `open_datetime` is a display copy of `open_time`, written as `YYYY-MM-DD HH:MM:SS` UTC when the candle is stored. It is determined by `open_time`.
- **C9.** Closing the window does not wait for the background worker. The thread is a daemon, so a commit in progress can be interrupted at process exit. SQLite rolls the page back.
- **C10.** Candles that fall outside the requested window are dropped without a count in the log. Validation failures are still logged one by one.
- **C11.** `read_init_state` treats any SQLite error as "not initialized". A locked or unreadable file can look empty.
- **C12.** The Windows font list is Segoe UI and Consolas, then Tk's default faces. A machine without those faces does not try Arial, Tahoma, or Courier New first.

## For developers (GitHub repo only)

Source code: https://github.com/kimfungho-dev/FF-BITVault-Sync

`tests/` and `requirements-dev.txt` are not part of the 3-file submission (`bitvault_sync.py`, `README.md`, `requirements.txt`). They are only in the GitHub repository.

```bash
git clone https://github.com/kimfungho-dev/FF-BITVault-Sync.git
cd FF-BITVault-Sync
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
```

The suite uses a temporary database. It does not read or replace `bitvault.db` next to the script.
