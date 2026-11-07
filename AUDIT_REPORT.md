# E2E audit: FF-BITVault-Sync

Audited `bitvault_sync.py` on branch `audit/e2e-tests`. The application file was not modified. No `bitvault.db` and no CSV were committed.

Checks call `bitvault_sync` against a temporary SQLite file. GUI checks run under Xvfb (`xvfb-run`), because this machine has no display. Live HTTP probes were run on 7 Nov 2026 at about 11:16 Asia/Shanghai (03:16 UTC).

## Part A — requirement compliance

| # | Requirement | Result | Evidence |
| --- | --- | --- | --- |
| 1 | SQLite is the database engine | PASS | `sqlite3.connect` in `connect()` (`bitvault_sync.py:551-556`). Schema is `symbols`, `hourly_klines`, `daily_fear_greed` (`bitvault_sync.py:408-455`). A live load created those three tables in a SQLite file. |
| 2 | BTCUSDT hourly spot klines from 2026-09-01 00:00 UTC, with open/high/low/close/volume | PASS | `HISTORY_START_MS = 1788220800000` is 2026-09-01 00:00:00 UTC (`bitvault_sync.py:38`). Klines use `interval=1h` on `/api/v3/klines` (`bitvault_sync.py:48`, `886-891`). Columns `open_price`, `high_price`, `low_price`, `close_price`, `volume` are on `hourly_klines` (`bitvault_sync.py:417-426`). With the host swapped in memory to a host that returns HTTP 200, the first stored row was `(1788220800000, '2026-09-01 00:00:00', 78581.3, 78900.01, 78562.0, 78652.0, 522.70913)`, matching the Vision payload. An unmodified run against `api.binance.com` stores 0 klines. See finding C1. |
| 3 | At least one additional source (ETHUSDT klines, Alternative.me Fear & Greed) | PASS | ETHUSDT is fetched on the same kline endpoint (`bitvault_sync.py:54-58`, `1184-1188`). Fear & Greed uses `https://api.alternative.me/fng/` (`bitvault_sync.py:51`, `1037-1063`). The live Alternative.me call returned HTTP 200 (`value` 25, `Extreme Fear`). The Vision-host load stored 1,612 ETHUSDT hours and 68 Fear & Greed days (`2026-09-01` through `2026-11-07`). |
| 4 | GUI: Initialize Database, Sync Database, Total Row Count, First Record Timestamp, Last Record Timestamp | PASS | Buttons at `bitvault_sync.py:2031-2046`. Metric titles at `bitvault_sync.py:2122-2128`. Test 10 walks the widget tree and requires those five strings. Under Xvfb they are present. |
| 5 | Complete, accurate, up to date, no missing or duplicate records | PASS | Primary key `(symbol, open_time)` plus `ON CONFLICT DO UPDATE` (`bitvault_sync.py:432`, `466-485`). `verify_integrity` checks duplicate keys, hourly gaps, expected counts, and duplicate Fear & Greed dates (`bitvault_sync.py:1402-1481`). On the Vision-host load: `Integrity: PASS`, BTCUSDT and ETHUSDT each `actual 1,612, expected 1,612` from `2026-09-01 00:00:00` to `2026-11-07 03:00:00 UTC`, duplicate keys 0, Fear & Greed duplicate dates 0. Test 01 repeats that check on a two-page window. Residual holes that did not show up in this dataset are C2 and C3. |
| 6 | Runs with no manual API-key setup | PASS | `requests.get` sends no API-key header (`bitvault_sync.py:344-347`). README states no key is required (`README.md:13`, `README.md:135-137`). Vision klines and Alternative.me both returned 200 with no key. The HTTP 451 from `api.binance.com` is a region block (`code: 0`, eligibility message), not an auth challenge. |
| 7 | README explains how to run | PASS | `README.md:7-13` and `README.md:32-52`: install `requirements.txt`, run `python3 bitvault_sync.py` (Windows: `py bitvault_sync.py`), click Initialize once, then Sync. Dependencies and the no-key note are in the same file. |
| 8 | Sync must not re-download history. Prove it with every request `startTime` | PASS | `incremental_sync` sets the kline `startTime` to `MAX(open_time)` (`bitvault_sync.py:1222-1248` for BTCUSDT, `1254-1272` for ETHUSDT). Test 02 prints every kline `startTime` across five syncs; each one equals that symbol's `MAX(open_time)` before the call, and none is `1788220800000`. The same function, pointed at Vision, issued exactly two kline requests on the follow-up sync, both `startTime=1794020400000` (`2026-11-07 03:00:00 UTC`), one row each, `new=0 updated=1`. Row count stayed 1,612. The unmodified client never reaches this second sync: the first kline call raises HTTP 451 (C1). |

### Live hosts

Probed from this VM. `api.binance.com` and `fapi.binance.com` answer **HTTP 451**. `https://data-api.binance.vision` answers **HTTP 200** for `/api/v3/time`, `/api/v3/klines`, and `/api/v3/ticker/24hr`. `https://api.alternative.me/fng/` answers **HTTP 200**.

The string `data-api.binance.vision` does not occur in `bitvault_sync.py`. `request_json` retries only 418, 429, 500, 502, 503, and 504 (`bitvault_sync.py:367-385`). A 451 is raised on the first attempt.

Unmodified `incremental_sync` on an empty database (11:16 Asia/Shanghai):

```text
WARNING: Binance server time is unavailable (451 Client Error: for url:
  https://api.binance.com/api/v3/time). Using the local UTC clock 2026-11-07 03:16:53 UTC.
[INITIALIZE] ... Loading hourly candles from 2026-09-01 00:00:00 UTC (1788220800000).
HTTPError 451 Client Error: for url:
  https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&startTime=1788220800000&limit=1000
```

`fetch_server_time_ms` swallows that 451 and substitutes the local clock (`bitvault_sync.py:395-401`). The kline call then raises. Schema commit had already happened. BTCUSDT count was 0.

To see what the same functions do when the host answers, the three spot URL constants were reassigned in that process only (the file on disk was not edited) to `https://data-api.binance.vision`. Initialize requests, in order:

| # | Host | startTime | UTC |
| --- | --- | --- | --- |
| 1 | `.../api/v3/time` | — | serverTime 1794021444040 |
| 2 | `.../api/v3/klines` BTCUSDT | 1788220800000 | 2026-09-01 00:00:00 |
| 3 | `.../api/v3/klines` BTCUSDT | 1791820800000 | 2026-10-12 16:00:00 (page 2, +1000 hours) |
| 4 | `.../api/v3/klines` ETHUSDT | 1788220800000 | 2026-09-01 00:00:00 |
| 5 | `.../api/v3/klines` ETHUSDT | 1791820800000 | 2026-10-12 16:00:00 |
| 6 | `api.alternative.me/fng/` | — | `limit=0` |

The follow-up `incremental_sync` requests were only:

| # | Host | startTime | UTC | Rows |
| --- | --- | --- | --- | --- |
| 1 | `.../api/v3/time` | — | — | serverTime |
| 2 | `.../api/v3/klines` BTCUSDT | 1794020400000 | 2026-11-07 03:00:00 | 1 |
| 3 | `.../api/v3/klines` ETHUSDT | 1794020400000 | 2026-11-07 03:00:00 | 1 |
| 4 | `api.alternative.me/fng/` | — | `limit=2` | 2 |

`1794020400000` was `MAX(open_time)` for both symbols before that sync. Log line: `BTCUSDT delta complete: API rows=1, new=0, updated=1` (ETHUSDT the same). No `startTime` of `1788220800000` on the sync. `verify_integrity` stayed `Integrity: PASS`.

## Part B — edge-case tests

Command (no display on this machine, so Xvfb wraps pytest):

```bash
xvfb-run -a -s "-screen 0 1600x1200x24" python3 -m pytest tests/test_e2e.py -vv -p no:cacheprovider -s
```

Result: **11 passed in 0.95s**. Tests 01–10 are the ten edge cases. Test 11 is the Auto-Sync timer check used in Part C. HTTP is stubbed inside the suite so a 451 from `api.binance.com` cannot make the edge cases flake. The live host result is Part A and finding C1.

Log lines below that look like `[03:39:49 UTC]` are the app's own UTC stamps. 03:39 UTC is 11:39 Asia/Shanghai.

```text
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-7.4.4, pluggy-1.4.0 -- /usr/bin/python3
rootdir: /workspace
collecting ... collected 11 items

tests/test_e2e.py::test_01_fresh_sync_auto_initializes_and_is_continuous TEST1 auto-init pages BTC startTimes=[1788220800000, 1791820800000] ETH startTimes=[1788220800000, 1791820800000] rows=1050 integrity=PASS
PASSED
tests/test_e2e.py::test_02_five_syncs_do_not_redownload_or_duplicate TEST2 startTime capture (every kline request during each sync)
  sync 1 elapsed_hours=0 before_max=1788328800000 kline_requests=['BTCUSDT:1788328800000', 'ETHUSDT:1788328800000'] btc_delta=0
  sync 2 elapsed_hours=0 before_max=1788328800000 kline_requests=['BTCUSDT:1788328800000', 'ETHUSDT:1788328800000'] btc_delta=0
  sync 3 elapsed_hours=0 before_max=1788328800000 kline_requests=['BTCUSDT:1788328800000', 'ETHUSDT:1788328800000'] btc_delta=0
  sync 4 elapsed_hours=1 before_max=1788328800000 kline_requests=['BTCUSDT:1788328800000', 'ETHUSDT:1788328800000'] btc_delta=1
  sync 5 elapsed_hours=2 before_max=1788332400000 kline_requests=['BTCUSDT:1788332400000', 'ETHUSDT:1788332400000'] btc_delta=2
PASSED
tests/test_e2e.py::test_03_auto_sync_tick_skips_while_manual_sync_holds_lock [03:39:48 UTC] No bitvault.db yet. Click Initialize Database to create the schema and load history.
[03:39:48 UTC] manual sync holding write lock
[03:39:49 UTC] [AUTO-SYNC] Skipped: a job is already running.
[03:39:49 UTC] A database job is already running.
TEST3 second job skipped; log has no 'database is locked'; threads=1
[03:39:49 UTC] [INCREMENTAL SYNC] Synced BTCUSDT new=0 updated=0.
[03:39:49 UTC] bitvault.db has no hourly_klines table yet. Click Initialize Database.
PASSED
tests/test_e2e.py::test_04_manual_sync_after_auto_sync_keeps_counts [03:39:49 UTC] SQL: SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ? | params=('BTCUSDT',)
[03:39:49 UTC] SQL: SELECT latest 15 BTCUSDT hourly_klines LEFT JOIN ETHUSDT close, quote volume, taker buy base | LIMIT 15
[03:39:49 UTC] [AUTO-SYNC]
[03:39:49 UTC] SQL: PRAGMA foreign_keys = ON -> 1
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS confirmed symbols, hourly_klines, daily_fear_greed, and idx_klines_open_time.
[03:39:49 UTC] SQL: executemany INSERT INTO symbols (symbol, base_asset, quote_asset, market_type) VALUES (?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET ...
[03:39:49 UTC] COMMIT symbols: BTCUSDT and ETHUSDT dimension rows are stored.
[03:39:49 UTC] SQL: SELECT MAX(open_time) FROM hourly_klines WHERE symbol = 'BTCUSDT'
[03:39:49 UTC] API GET https://api.binance.com/api/v3/time params={} -> serverTime=1788242400000
[03:39:49 UTC] [INCREMENTAL SYNC] Last DB Timestamp: 2026-09-01 06:00:00 UTC -> Fetching ONLY delta records from 2026-09-01 06:00:00 UTC to now...
[03:39:49 UTC] [INCREMENTAL SYNC] BTCUSDT startTime=1788242400000. The request begins at the last stored hour, so only that candle and any newly elapsed hours are returned.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'BTCUSDT', 'interval': '1h', 'startTime': 1788242400000, 'limit': 1000} -> 1 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=BTCUSDT rows=1
[03:39:49 UTC] COMMIT hourly_klines symbol=BTCUSDT inserted=0 updated=1
[03:39:49 UTC] [INCREMENTAL SYNC] BTCUSDT delta complete: API rows=1, new=0, updated=1.
[03:39:49 UTC] SQL: SELECT MAX(open_time) FROM hourly_klines WHERE symbol = 'ETHUSDT'
[03:39:49 UTC] [INCREMENTAL SYNC] ETHUSDT last DB timestamp: 2026-09-01 06:00:00 UTC -> Fetching ONLY delta records from 2026-09-01 06:00:00 UTC to now...
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'ETHUSDT', 'interval': '1h', 'startTime': 1788242400000, 'limit': 1000} -> 1 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=ETHUSDT rows=1
[03:39:49 UTC] COMMIT hourly_klines symbol=ETHUSDT inserted=0 updated=1
[03:39:49 UTC] [INCREMENTAL SYNC] ETHUSDT delta complete: API rows=1, new=0, updated=1.
[03:39:49 UTC] [INCREMENTAL SYNC] Fear & Greed last date 2026-09-01 -> fetching only that day and newer (limit=2).
[03:39:49 UTC] API GET https://api.alternative.me/fng/ params={'limit': 2} -> 1 rows
[03:39:49 UTC] Fear & Greed source=alternative.me days=1 from 2026-09-01 to 2026-09-01.
[03:39:49 UTC] SQL: executemany INSERT INTO daily_fear_greed (timestamp, date_str, value, value_classification) VALUES (?, ?, ?, ?) ON CONFLICT(timestamp) DO UPDATE SET ... | rows=1
[03:39:49 UTC] COMMIT daily_fear_greed inserted=0 updated=1
[03:39:49 UTC] Continuity OK BTCUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-09-01 06:00:00 UTC.
[03:39:49 UTC] Continuity OK ETHUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-09-01 06:00:00 UTC.
[03:39:49 UTC] [INCREMENTAL SYNC] Synced BTCUSDT new=0 updated=1 (API rows=1); ETHUSDT new=0 updated=1 (API rows=1); Fear & Greed source=alternative.me new=0 updated=1.
[03:39:49 UTC] SQL: SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ? | params=('BTCUSDT',)
[03:39:49 UTC] SQL: SELECT latest 15 BTCUSDT hourly_klines LEFT JOIN ETHUSDT close, quote volume, taker buy base | LIMIT 15
[03:39:49 UTC] SQL: PRAGMA foreign_keys = ON -> 1
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS confirmed symbols, hourly_klines, daily_fear_greed, and idx_klines_open_time.
[03:39:49 UTC] SQL: executemany INSERT INTO symbols (symbol, base_asset, quote_asset, market_type) VALUES (?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET ...
[03:39:49 UTC] COMMIT symbols: BTCUSDT and ETHUSDT dimension rows are stored.
[03:39:49 UTC] SQL: SELECT MAX(open_time) FROM hourly_klines WHERE symbol = 'BTCUSDT'
[03:39:49 UTC] API GET https://api.binance.com/api/v3/time params={} -> serverTime=1788242400000
[03:39:49 UTC] [INCREMENTAL SYNC] Last DB Timestamp: 2026-09-01 06:00:00 UTC -> Fetching ONLY delta records from 2026-09-01 06:00:00 UTC to now...
[03:39:49 UTC] [INCREMENTAL SYNC] BTCUSDT startTime=1788242400000. The request begins at the last stored hour, so only that candle and any newly elapsed hours are returned.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'BTCUSDT', 'interval': '1h', 'startTime': 1788242400000, 'limit': 1000} -> 1 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=BTCUSDT rows=1
[03:39:49 UTC] COMMIT hourly_klines symbol=BTCUSDT inserted=0 updated=1
[03:39:49 UTC] [INCREMENTAL SYNC] BTCUSDT delta complete: API rows=1, new=0, updated=1.
[03:39:49 UTC] SQL: SELECT MAX(open_time) FROM hourly_klines WHERE symbol = 'ETHUSDT'
[03:39:49 UTC] [INCREMENTAL SYNC] ETHUSDT last DB timestamp: 2026-09-01 06:00:00 UTC -> Fetching ONLY delta records from 2026-09-01 06:00:00 UTC to now...
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'ETHUSDT', 'interval': '1h', 'startTime': 1788242400000, 'limit': 1000} -> 1 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=ETHUSDT rows=1
[03:39:49 UTC] COMMIT hourly_klines symbol=ETHUSDT inserted=0 updated=1
[03:39:49 UTC] [INCREMENTAL SYNC] ETHUSDT delta complete: API rows=1, new=0, updated=1.
[03:39:49 UTC] [INCREMENTAL SYNC] Fear & Greed last date 2026-09-01 -> fetching only that day and newer (limit=2).
[03:39:49 UTC] API GET https://api.alternative.me/fng/ params={'limit': 2} -> 1 rows
[03:39:49 UTC] Fear & Greed source=alternative.me days=1 from 2026-09-01 to 2026-09-01.
[03:39:49 UTC] SQL: executemany INSERT INTO daily_fear_greed (timestamp, date_str, value, value_classification) VALUES (?, ?, ?, ?) ON CONFLICT(timestamp) DO UPDATE SET ... | rows=1
[03:39:49 UTC] COMMIT daily_fear_greed inserted=0 updated=1
[03:39:49 UTC] Continuity OK BTCUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-09-01 06:00:00 UTC.
[03:39:49 UTC] Continuity OK ETHUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-09-01 06:00:00 UTC.
[03:39:49 UTC] [INCREMENTAL SYNC] Synced BTCUSDT new=0 updated=1 (API rows=1); ETHUSDT new=0 updated=1 (API rows=1); Fear & Greed source=alternative.me new=0 updated=1.
[03:39:49 UTC] SQL: SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ? | params=('BTCUSDT',)
[03:39:49 UTC] SQL: SELECT latest 15 BTCUSDT hourly_klines LEFT JOIN ETHUSDT close, quote volume, taker buy base | LIMIT 15
TEST4 after auto then manual auto_start=[1788242400000] manual_start=[1788242400000] btc_rows=7 duplicates=0
PASSED
tests/test_e2e.py::test_05_hour_boundary_updates_closed_candle_and_inserts_live TEST5 hour boundary updated_open=1788231600000 close 70003.0 -> 70028.0 inserted=1788235200000 status CLOSED/LIVE delta=+1
PASSED
tests/test_e2e.py::test_06_fear_greed_day_boundary_inserts_one_row TEST6 fear/greed dates [('2026-09-01', 1), ('2026-09-02', 1), ('2026-09-03', 1)] new_rows=1
PASSED
tests/test_e2e.py::test_07_export_csv_matches_btc_rows_without_join_fanout TEST7 export rows=14 btc_rows=14 unique_open_time=14 fanout=0
PASSED
tests/test_e2e.py::test_08_initialize_yes_does_not_duplicate [03:39:49 UTC] SQL: SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ? | params=('BTCUSDT',)
[03:39:49 UTC] SQL: SELECT latest 15 BTCUSDT hourly_klines LEFT JOIN ETHUSDT close, quote volume, taker buy base | LIMIT 15
[03:39:49 UTC] SQL: PRAGMA foreign_keys = ON -> 1
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS confirmed symbols, hourly_klines, daily_fear_greed, and idx_klines_open_time.
[03:39:49 UTC] SQL: executemany INSERT INTO symbols (symbol, base_asset, quote_asset, market_type) VALUES (?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET ...
[03:39:49 UTC] COMMIT symbols: BTCUSDT and ETHUSDT dimension rows are stored.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/time params={} -> serverTime=1788249600000
[03:39:49 UTC] [INITIALIZE] Binance serverTime 2026-09-01 08:00:00 UTC is at or after 1 Sep 2026. Loading hourly candles from 2026-09-01 00:00:00 UTC (1788220800000). START_TIMESTAMP_MS=1756684800000 (2025-09-01 00:00:00 UTC) stays as the fallback when 1 Sep 2026 is still in the future.
[03:39:49 UTC] [INITIALIZE] Full historical pull from 2026-09-01 00:00:00 UTC through Binance server time 2026-09-01 08:00:00 UTC. This is the initial load, not an incremental sync.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'BTCUSDT', 'interval': '1h', 'startTime': 1788220800000, 'limit': 1000} -> 9 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=BTCUSDT rows=9
[03:39:49 UTC] COMMIT hourly_klines symbol=BTCUSDT inserted=0 updated=9
[03:39:49 UTC] Continuity OK BTCUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-09-01 08:00:00 UTC.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'ETHUSDT', 'interval': '1h', 'startTime': 1788220800000, 'limit': 1000} -> 9 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=ETHUSDT rows=9
[03:39:49 UTC] COMMIT hourly_klines symbol=ETHUSDT inserted=0 updated=9
[03:39:49 UTC] Continuity OK ETHUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-09-01 08:00:00 UTC.
[03:39:49 UTC] API GET https://api.alternative.me/fng/ params={'limit': 0} -> 1 rows
[03:39:49 UTC] Fear & Greed source=alternative.me days=1 from 2026-09-01 to 2026-09-01.
[03:39:49 UTC] SQL: executemany INSERT INTO daily_fear_greed (timestamp, date_str, value, value_classification) VALUES (?, ?, ?, ?) ON CONFLICT(timestamp) DO UPDATE SET ... | rows=1
[03:39:49 UTC] COMMIT daily_fear_greed inserted=0 updated=1
[03:39:49 UTC] [INITIALIZE] Complete. BTCUSDT API rows=9 new=0 updated=9. ETHUSDT API rows=9 new=0 updated=9. Fear & Greed source=alternative.me new=0 updated=1.
[03:39:49 UTC] SQL: SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ? | params=('BTCUSDT',)
[03:39:49 UTC] SQL: SELECT latest 15 BTCUSDT hourly_klines LEFT JOIN ETHUSDT close, quote volume, taker buy base | LIMIT 15
TEST8 re-init Yes rows=9 unchanged duplicates=0 integrity=PASS
PASSED
tests/test_e2e.py::test_09_page_two_failure_keeps_committed_page_and_reenables_buttons [03:39:49 UTC] No bitvault.db yet. Click Initialize Database to create the schema and load history.
[03:39:49 UTC] SQL: PRAGMA foreign_keys = ON -> 1
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS symbols ( symbol TEXT PRIMARY KEY, base_asset TEXT NOT NULL, quote_asset TEXT NOT NULL, market_type TEXT NOT NULL )
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS hourly_klines ( symbol TEXT NOT NULL, open_time INTEGER NOT NULL, open_datetime TEXT NOT NULL, open_price REAL NOT NULL, high_price REAL NOT NULL, low_price REAL NOT NULL, close_price REAL NOT NULL, volume REAL NOT NULL, close_time INTEGER NOT NULL, quote_asset_volume REAL NOT NULL, number_of_trades INTEGER NOT NULL, taker_buy_base_volume REAL NOT NULL, taker_buy_quote_volume REAL NOT NULL, PRIMARY KEY (symbol, open_time), FOREIGN KEY (symbol) REFERENCES symbols(symbol) )
[03:39:49 UTC] SQL: CREATE INDEX IF NOT EXISTS idx_klines_open_time ON hourly_klines (open_time)
[03:39:49 UTC] SQL: CREATE INDEX IF NOT EXISTS idx_klines_symbol ON hourly_klines (symbol)
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS daily_fear_greed ( timestamp INTEGER PRIMARY KEY, date_str TEXT NOT NULL, value INTEGER NOT NULL, value_classification TEXT NOT NULL )
[03:39:49 UTC] SQL: CREATE INDEX IF NOT EXISTS idx_fear_greed_date ON daily_fear_greed (date_str)
[03:39:49 UTC] SQL: executemany INSERT INTO symbols (symbol, base_asset, quote_asset, market_type) VALUES (?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET ...
[03:39:49 UTC] COMMIT symbols: BTCUSDT and ETHUSDT dimension rows are stored.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/time params={} -> serverTime=1793620800000
[03:39:49 UTC] [INITIALIZE] Binance serverTime 2026-11-02 12:00:00 UTC is at or after 1 Sep 2026. Loading hourly candles from 2026-09-01 00:00:00 UTC (1788220800000). START_TIMESTAMP_MS=1756684800000 (2025-09-01 00:00:00 UTC) stays as the fallback when 1 Sep 2026 is still in the future.
[03:39:49 UTC] [INITIALIZE] Full historical pull from 2026-09-01 00:00:00 UTC through Binance server time 2026-11-02 12:00:00 UTC. This is the initial load, not an incremental sync.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'BTCUSDT', 'interval': '1h', 'startTime': 1788220800000, 'limit': 1000} -> 1000 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=BTCUSDT rows=1000
[03:39:49 UTC] COMMIT hourly_klines symbol=BTCUSDT inserted=1000 updated=0
[03:39:49 UTC] WARNING: ConnectionError calling https://api.binance.com/api/v3/klines. Retry 1/3.
[03:39:49 UTC] WARNING: ConnectionError calling https://api.binance.com/api/v3/klines. Retry 2/3.
[03:39:49 UTC] ERROR: ConnectionError: network failure mid-pagination
[03:39:49 UTC] SQL: SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ? | params=('BTCUSDT',)
[03:39:49 UTC] SQL: SELECT latest 15 BTCUSDT hourly_klines LEFT JOIN ETHUSDT close, quote volume, taker buy base | LIMIT 15
TEST9 page2 failure committed_btc=1000 eth=0 integrity=ok buttons_enabled status='Last Initialize: 03:39:49 UTC (03:39:49 UTC) · Failed · 0.0 s'
PASSED
tests/test_e2e.py::test_10_action_label_is_local_and_stored_timestamps_are_utc [03:39:49 UTC] No bitvault.db yet. Click Initialize Database to create the schema and load history.
[03:39:49 UTC] Database is not initialized (hourly_klines does not exist). Running initialization.
[03:39:49 UTC] SQL: PRAGMA foreign_keys = ON -> 1
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS symbols ( symbol TEXT PRIMARY KEY, base_asset TEXT NOT NULL, quote_asset TEXT NOT NULL, market_type TEXT NOT NULL )
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS hourly_klines ( symbol TEXT NOT NULL, open_time INTEGER NOT NULL, open_datetime TEXT NOT NULL, open_price REAL NOT NULL, high_price REAL NOT NULL, low_price REAL NOT NULL, close_price REAL NOT NULL, volume REAL NOT NULL, close_time INTEGER NOT NULL, quote_asset_volume REAL NOT NULL, number_of_trades INTEGER NOT NULL, taker_buy_base_volume REAL NOT NULL, taker_buy_quote_volume REAL NOT NULL, PRIMARY KEY (symbol, open_time), FOREIGN KEY (symbol) REFERENCES symbols(symbol) )
[03:39:49 UTC] SQL: CREATE INDEX IF NOT EXISTS idx_klines_open_time ON hourly_klines (open_time)
[03:39:49 UTC] SQL: CREATE INDEX IF NOT EXISTS idx_klines_symbol ON hourly_klines (symbol)
[03:39:49 UTC] SQL: CREATE TABLE IF NOT EXISTS daily_fear_greed ( timestamp INTEGER PRIMARY KEY, date_str TEXT NOT NULL, value INTEGER NOT NULL, value_classification TEXT NOT NULL )
[03:39:49 UTC] SQL: CREATE INDEX IF NOT EXISTS idx_fear_greed_date ON daily_fear_greed (date_str)
[03:39:49 UTC] SQL: executemany INSERT INTO symbols (symbol, base_asset, quote_asset, market_type) VALUES (?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET ...
[03:39:49 UTC] COMMIT symbols: BTCUSDT and ETHUSDT dimension rows are stored.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/time params={} -> serverTime=1788228000000
[03:39:49 UTC] [INITIALIZE] Binance serverTime 2026-09-01 02:00:00 UTC is at or after 1 Sep 2026. Loading hourly candles from 2026-09-01 00:00:00 UTC (1788220800000). START_TIMESTAMP_MS=1756684800000 (2025-09-01 00:00:00 UTC) stays as the fallback when 1 Sep 2026 is still in the future.
[03:39:49 UTC] [INITIALIZE] Full historical pull from 2026-09-01 00:00:00 UTC through Binance server time 2026-09-01 02:00:00 UTC. This is the initial load, not an incremental sync.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'BTCUSDT', 'interval': '1h', 'startTime': 1788220800000, 'limit': 1000} -> 3 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=BTCUSDT rows=3
[03:39:49 UTC] COMMIT hourly_klines symbol=BTCUSDT inserted=3 updated=0
[03:39:49 UTC] Continuity OK BTCUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-09-01 02:00:00 UTC.
[03:39:49 UTC] API GET https://api.binance.com/api/v3/klines params={'symbol': 'ETHUSDT', 'interval': '1h', 'startTime': 1788220800000, 'limit': 1000} -> 3 rows
[03:39:49 UTC] SQL: executemany INSERT INTO hourly_klines (...) ON CONFLICT(symbol, open_time) DO UPDATE SET ... | symbol=ETHUSDT rows=3
[03:39:49 UTC] COMMIT hourly_klines symbol=ETHUSDT inserted=3 updated=0
[03:39:49 UTC] Continuity OK ETHUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-09-01 02:00:00 UTC.
[03:39:49 UTC] API GET https://api.alternative.me/fng/ params={'limit': 0} -> 1 rows
[03:39:49 UTC] Fear & Greed source=alternative.me days=1 from 2026-09-01 to 2026-09-01.
[03:39:49 UTC] SQL: executemany INSERT INTO daily_fear_greed (timestamp, date_str, value, value_classification) VALUES (?, ?, ?, ?) ON CONFLICT(timestamp) DO UPDATE SET ... | rows=1
[03:39:49 UTC] COMMIT daily_fear_greed inserted=1 updated=0
[03:39:49 UTC] [INITIALIZE] Complete. BTCUSDT API rows=3 new=3 updated=0. ETHUSDT API rows=3 new=3 updated=0. Fear & Greed source=alternative.me new=1 updated=0.
[03:39:49 UTC] SQL: SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ? | params=('BTCUSDT',)
[03:39:49 UTC] SQL: SELECT latest 15 BTCUSDT hourly_klines LEFT JOIN ETHUSDT close, quote volume, taker buy base | LIMIT 15
TEST10 action_clock='11:39:49 CST (03:39:49 UTC)' status='Last Sync: 11:39:49 CST (03:39:49 UTC) · +7 new / 0 updated · 0.0 s' stored_open_time=1788220800000 stored_open_datetime='2026-09-01 00:00:00' first_label='2026-09-01 00:00:00 UTC'
PASSED
tests/test_e2e.py::test_11_auto_sync_toggle_does_not_leak_timers [03:39:49 UTC] No bitvault.db yet. Click Initialize Database to create the schema and load history.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
[03:39:49 UTC] [AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.
[03:39:49 UTC] [AUTO-SYNC] Disabled. Timer cancelled.
TEST11 auto-sync toggled 25 times; pending after callbacks stayed 1 when off
PASSED

============================== 11 passed in 0.95s ==============================
```

What each case showed:

1. Fresh database, `incremental_sync` runs initialization. 1,050 contiguous BTCUSDT and ETHUSDT hours, two pages (`startTime` then `startTime + 1000h`), `verify_integrity` PASS, stored OHLCV matches the payload.
2. Five syncs. Deltas were 0, 0, 0, +1, +2 hours. Every kline `startTime` equalled `MAX(open_time)`. No duplicate `(symbol, open_time)`.
3. Manual sync held `BEGIN IMMEDIATE`. A second connection's `BEGIN IMMEDIATE` raised `database is locked`, so the lock is real. The Auto-Sync tick logged `Skipped: a job is already running.` and did not start a second thread. The app log did not contain `database is locked`.
4. Auto-Sync then manual Sync. Both kline `startTime`s were the current max (`1788242400000`). 7 BTC rows, 0 duplicates, integrity PASS.
5. The forming hour's close moved from 70003.0 to 70028.0 and became CLOSED. The next hour was inserted and was LIVE. Count +1.
6. Fear & Greed went from Sep 1–2 to Sep 1–3, one row per `date_str`.
7. After init plus two syncs, CSV row count equalled BTCUSDT hours (14), `open_time_utc` values were unique, OHLCV cells were numeric, and the export join grouped by `open_time` had no fan-out.
8. Initialize on an existing database, Yes on the dialog. Count stayed 9. Integrity PASS. The re-run's first `startTime` was the history start, and the primary-key upsert did not double the rows.
9. `ConnectionError` on BTC page 2, after three attempts. 1,000 committed BTC rows, 0 ETH rows, `PRAGMA integrity_check` = `ok`, no NULL OHLCV. Buttons left the disabled state. Status: `Last Initialize: ... Failed`.
10. With `TZ=Asia/Shanghai`, the action line was `11:39:49 CST (03:39:49 UTC)`. The first stored `open_time` was `1788220800000` and `open_datetime` was `2026-09-01 00:00:00`. The First Record label was `2026-09-01 00:00:00 UTC`.

## Part C — code review

Findings only. Fixes are listed here and were not applied on this branch.

### High

**C1. No fallback when Binance returns HTTP 451/403.** `bitvault_sync.py:47-51`, `bitvault_sync.py:367-385`, `bitvault_sync.py:388-401`, `bitvault_sync.py:894`.

Spot calls are hard-coded to `https://api.binance.com` (`/api/v3/time`, `/api/v3/klines`, `/api/v3/ticker/24hr`). Funding uses `https://fapi.binance.com`. From this region all four return HTTP 451. `https://data-api.binance.vision` returns 200 for the three spot paths and serves the 2026-09-01 BTCUSDT candle. The client never tries that host. `fetch_server_time_ms` treats the 451 as a generic outage, logs a warning, and continues with the local clock, so the first hard failure is the kline request. An unmodified Sync creates empty tables and then raises. Suggested fix: keep an ordered host list (`api.binance.com`, then `data-api.binance.vision`) and, on 451 or 403, repeat the same path on the next host. Use the local clock only after every time host has failed. Apply the same list to klines and the 24h ticker. Leave 451/403 out of the same-host retry set.

### Medium

**C2. Hours after the last stored candle are invisible to the continuity check.** `bitvault_sync.py:782-798`, `bitvault_sync.py:814-841`, `bitvault_sync.py:966-996`, `bitvault_sync.py:1628-1635`, `bitvault_sync.py:2669-2672`.

`missing_open_times` and `load_enrichment` walk only from `MIN(open_time)` to `MAX(open_time)`. A tail fetch that returns an empty page still falls through to `Continuity OK`. Reproduced with three stored hours, server time eight hours ahead, and a kline endpoint that returned `[]`: the warning about the tail was followed by `Continuity OK`, and `missing_hours` was 0, so the health card can read `0 Missing Hours / Verified` while those hours are absent. Suggested fix: audit through `floor_hour(server_time)`, and if the tail fetch adds nothing, count the missing hours and do not log `Continuity OK`.

**C3. Export LEFT JOIN fans out when two Fear & Greed rows share `date_str`.** `bitvault_sync.py:444-455`, `bitvault_sync.py:487-494`, `bitvault_sync.py:1364-1368`.

The primary key is `timestamp`. `date_str` is indexed and not unique. `SQL_EXPORT_HOURLY` joins `daily_fear_greed.date_str` to the candle's UTC date. Two rows with the same `date_str` and different timestamps turned 3 BTC hours into 6 joined rows. Today's Alternative.me history did not contain duplicate dates (68 days, 0 duplicate `date_str`), so the live export is clean. The schema still allows the duplicate. Suggested fix: enforce one row per `date_str` (unique index, or delete-then-insert by date in `upsert_fear_greed`) and join the export to a single row per date.

**C4. The activity log grows without a cap.** `bitvault_sync.py:2509-2515`, `bitvault_sync.py:2578-2594`.

`_append_log` only inserts into the `Text` widget. Auto-Sync every five minutes keeps appending. Suggested fix: after each insert, if the line count is above a bound (for example 2,000), delete from `1.0` through a few hundred lines later.

**C5. A nested Tk event loop can start a writer before `_busy` is set. Export runs on the Tk thread.** `bitvault_sync.py:2346-2358`, `bitvault_sync.py:2381-2411`, `bitvault_sync.py:2445-2456`.

`messagebox.askyesno` and `filedialog.asksaveasfilename` enter a nested loop while `_busy` is still false, so an Auto-Sync tick can start `incremental_sync` before Initialize or Export continues. Export then calls `export_hourly_csv` → `connect()` on the Tk thread and never sets `_busy`. The worker/UI split for Initialize, Sync, and Verify is otherwise sound: each job opens its own connection on the worker and closes it before queueing `done` (`bitvault_sync.py:2486-2506`, `2474-2484`). Suggested fix: set a guard before either dialog, and have `_auto_sync_tick` return while that guard is set. Run export through `_start_job` like Verify.

**C6. More than 20 gap ranges are collapsed into one refetch of the whole span.** `bitvault_sync.py:1008-1024`.

`ensure_continuous` replaces those ranges with `(missing[0], missing[-1])`. Hours that are already stored inside that span are requested again. On a database with a hole near the start and a hole near the end, that is close to a full history download, which is the failure mode Sync is supposed to avoid. The normal incremental path does not hit this; test 02 and the Vision follow-up sync issued only the tail `startTime`. Suggested fix: request each contiguous range with its own `endTime`, or raise the cap without covering hours that are present.

**C7. An empty kline page still lets Initialize finish as a success.** `bitvault_sync.py:897-898`, `bitvault_sync.py:1194-1199`.

`if not payload: break` ends that symbol. `initialize_database` still logs `[INITIALIZE] Complete` and the status line counts `new=0 updated=0` as rows loaded, not as a failure. Suggested fix: if a symbol ends with zero rows, log an error and surface Failed on the status line.

### Low

**C8. `connect()` ignores `DB_FILE`.** `bitvault_sync.py:60`, `bitvault_sync.py:551-553`. Both strings are `"bitvault.db"` today. Suggested fix: `sqlite3.connect(DB_FILE)`.

**C9. Closing the window does not wait for the worker.** `bitvault_sync.py:2295-2298`, `bitvault_sync.py:2472`. The thread is a daemon. Process exit can interrupt a commit; SQLite's journal should roll the page back, and a half-written page is still a rough shutdown. Suggested fix: keep the `Thread`, and `join` it with a short timeout in `_on_close` before `destroy()`.

**C10. Some skipped candles are quiet.** `bitvault_sync.py:907-908` drops out-of-window rows with no log. `bitvault_sync.py:911-916` logs a validation failure and leaves that hour unstored; `ensure_continuous` will say so if the hour stays inside `MIN..MAX`, which is the C2 window. Suggested fix: count out-of-window drops and log the count once per page. Keep the per-candle validation warning.

**C11. `read_init_state` maps every `sqlite3.Error` to "not initialized".** `bitvault_sync.py:630-631`. A locked or corrupt file can look empty and the Initialize prompt can offer a full download. Suggested fix: log the exception and keep a distinct error state on the badge.

**C12. Windows path and font.** `bitvault_sync.py:1570-1579`, `bitvault_sync.py:2798-2801`, `bitvault_sync.py:1497`. `main` changes to `os.path.dirname(os.path.abspath(__file__))` and opens `bitvault.db` beside the script. CSV is opened with `newline=""`, which is the right choice on Windows. No backslash-joined path was found. The Windows font list is only Segoe UI and Consolas; `choose_font` then falls back to `TkDefaultFont` and `TkFixedFont`. Suggested fix: add one or two fallbacks in the Windows tuples (`Arial`, `Tahoma`, `Courier New`) so a machine without Segoe UI still picks a known face before the Tk default.

**C13. A failed sync is easy to miss.** `bitvault_sync.py:2236`, `bitvault_sync.py:2474-2484`, `bitvault_sync.py:2568-2576`. The error is printed and queued, and the status line says Failed. The activity log starts collapsed, and there is no error dialog. Suggested fix: on `error` in `_finish_job`, open the log and show a short message box with the exception text.

### Checked, no defect found

- **SQLite connections are not shared across threads.** Initialize, Sync, and Verify each call `connect()` on the worker and `close()` in `finally` before `done` is queued. The dashboard opens a separate connection on the Tk thread after `_busy` is cleared. `check_same_thread` stays at the SQLite default.
- **Auto-Sync does not leak timers.** `_schedule_auto_sync` cancels `_auto_after_id` before arming the next `after` (`bitvault_sync.py:2427-2443`). Test 11 toggled the control 25 times. With Auto-Sync off, the pending `after` count stayed at 1 (the 80 ms log poll). With it on, the count was 2, and `_auto_after_id` was set. Turning it off returned the count to 1.
- **The worker does not touch Tk widgets.** `log` and `report` only enqueue. `_poll_queue` applies them on the Tk thread (`bitvault_sync.py:2509-2538`). Test 03 shows the busy flag stops a second writer, which is what keeps the "database is locked" error off the Sync path.

## What this branch does not change

`bitvault_sync.py` is unchanged. Findings C1–C13 are recommendations only. The temporary databases used for the live probe and the tests were created outside the repo (`/tmp` and pytest `tmp_path`) and were not committed.
