# Final compliance audit

Audited commit `e68f3919a693b94bfbd0d092ac8e9139c3f7d7e5` (`e68f391`, 7 Nov 2026 12:13 Asia/Shanghai) on branch `audit/final-compliance`. The three submission files were not modified.

| File | SHA-256 | Lines |
| --- | --- | --- |
| `bitvault_sync.py` | `7f90f6bf485fd7191e8e8e6113194884794ff3e945885ca7db234b1faa0bdd25` | 3057 |
| `README.md` | `2bdbc2c098b14a00a47502116225ac76e53b590790f68955059add50bc1232dd` | 345 |
| `requirements.txt` | `eee0ec23fa0d0d00a7a4b928a11e03349bd4cddb8511e0528f531e2a2b5f3bf4` | 2 |

The grader drop was a copy of only those three files in an empty directory (`/tmp/grader-submit`, no `.git`). Live calls ran on 7 Nov 2026 at 12:32 Asia/Shanghai (04:32 UTC). Binance `serverTime` during Initialize was `2026-11-07 04:32:24 UTC` (12:32:24 Asia/Shanghai). The newest stored candle opens at `2026-11-07 04:00:00 UTC` (12:00 Asia/Shanghai).

Method: import the unmodified module, wrap `requests.get`, and drive the real Tk buttons (`invoke`, which does nothing when a button is disabled) plus the real Auto-Sync `after` callback. SQL was run on the `bitvault.db` that those buttons created. Nothing in this audit was stubbed except message boxes, which were recorded instead of left blocking.

**No issue below is a requirement failure.** The happy path meets every line of the assignment. The deductions in Part D are places a strict grader can still take marks.

## Part A — Requirement by requirement

| Requirement | Verdict | Evidence |
| --- | --- | --- |
| SQLite is the database engine | PASS | `sqlite3.connect` at `bitvault_sync.py:663`. After Initialize, `sqlite_master` contains only `symbols`, `hourly_klines`, and `daily_fear_greed`. |
| Hourly BTC spot OHLCV from 1 Sep 2026 | PASS | `HISTORY_START_MS = 1788220800000` (`bitvault_sync.py:39`), which is `2026-09-01 00:00:00 UTC`. Kline calls use `interval=1h` (`bitvault_sync.py:1001-1006`) and `/api/v3/klines` (`bitvault_sync.py:53`). Stored BTCUSDT: 1,613 rows, `MIN(open_time)=1788220800000`, `MAX(open_time)=1794024000000`, 0 rows earlier than the history start, 0 rows not aligned to an hour. |
| Additional data from another source or endpoint | PASS | ETHUSDT on the same kline endpoint (1,613 rows) plus the daily Crypto Fear & Greed index from `https://api.alternative.me/fng/` (`bitvault_sync.py:56`, `1169`). 68 days, `2026-09-01` through `2026-11-07`, values matched the live API. Quote volume, trade count, and taker-buy volume are stored on the fact table (`bitvault_sync.py:529-532`). |
| GUI shows the five required controls | RISK | The five strings are real widgets (`bitvault_sync.py:2192`, `2200`, `2281`, `2284`, `2287`). At 1280×800 all five titles are fully on screen. The timestamp *values* lose the final `C` of `UTC`, and the footer is below the screen. See Part C.6. |
| Complete, accurate, current data; no gaps or duplicates | PASS | After Initialize and five syncs, and again after a 3-hour hole was repaired: duplicate `(symbol, open_time)` = 0, hour gaps = 0, BTC count = expected count = 1,613. All 1,612 closed BTC OHLC and base-volume values round-trip to Binance's 8-decimal strings. The latest row is the hour that was still forming. |
| Runs without a manual API key | PASS | No `API_KEY`, `os.environ`, `argparse`, or `.env` read. Public Binance and Alternative.me endpoints. A clean venv plus `pip install -r requirements.txt` and `python3 bitvault_sync.py` opened the window. |
| `.py` plus run instructions | PASS | `README.md:34-38` gives the install and run commands. Those commands work. The Tests section does not, because `tests/` is not part of the 3-file drop (Part C.1). |

### Marking lines

| Mark | Max | Verdict | Estimate | Why |
| --- | ---: | --- | ---: | --- |
| BTC price history from Binance | 25 | PASS | 25 | Spot `/api/v3/klines`, `BTCUSDT`, `1h`, open/high/low/close/volume, from `2026-09-01 00:00:00 UTC` through the current hour. Closed candles match the exchange exactly. |
| Additional data | 20 | PASS | 20 | A second symbol (ETHUSDT) and a second source (Alternative.me Fear & Greed, 68/68 days exact). Funding-rate and 24h ticker exist only as sentiment fallbacks and were not called. |
| Proper RDBMS storage | 20 | RISK | 18 | Three normalized tables, composite primary key, foreign key enforced on the app's connections. `REAL` cannot preserve every 8-decimal quote notional, and `open_datetime` repeats `open_time`. |
| Synchronization | 25 | RISK | 23 | Sync reads `MAX(open_time)` and requests only that hour forward. It refuses an empty database. One edge path (more than 20 separate holes) re-downloads the span between the first and last hole. |
| Functional UI | 10 | RISK | 8 | The five required controls work and show the right numbers. At 1280×800 the window is taller than the screen, timestamp values are clipped, and the Status column is 4 px visible. |

### Live BTC history

Initialize log (stdout of the unmodified program):

```text
[HOST] switched to data-api.binance.vision
[INITIALIZE] Binance serverTime 2026-11-07 04:32:24 UTC is at or after 1 Sep 2026.
  Loading hourly candles from 2026-09-01 00:00:00 UTC (1788220800000).
API GET https://data-api.binance.vision/api/v3/klines
  params={'symbol': 'BTCUSDT', 'interval': '1h', 'startTime': 1788220800000, 'limit': 1000} -> 1000 rows
API GET ... startTime=1791820800000 -> 613 rows
Continuity OK BTCUSDT: no missing hours from 2026-09-01 00:00:00 UTC to 2026-11-07 04:00:00 UTC.
[INITIALIZE] Complete. BTCUSDT API rows=1613 new=1613 updated=0.
  ETHUSDT API rows=1613 new=1613 updated=0.
  Fear & Greed source=alternative.me new=68 updated=0.
```

`api.binance.com` answered the first call with HTTP 451. The process failed over to `data-api.binance.vision` and stored the history from there. Direct vision check of the first candle: open `78581.30000000`, high `78900.01000000`, low `78562.00000000`, close `78652.00000000`, volume `522.70913000`, open time `2026-09-01 00:00:00 UTC`. The database row matches that string on every OHLC and base-volume field.

Closed-candle comparison against a fresh vision pull, forming hour excluded (1,612 unique hours):

| Field | Candles that do not round-trip to the API string |
| --- | ---: |
| open, high, low, close, volume | 0 |
| taker buy base volume | 0 |
| close_time, number_of_trades | 0 |
| quote asset volume | 136 |
| taker buy quote volume | 25 |
| missing from the database | 0 |

The 161 mismatches are one unit in the 8th decimal of a ~1e8 notional (`100019632.19127170` stored and rendered as `100019632.19127171`). Float64 cannot hold 17 significant digits. The assigned OHLC and base volume are exact.

### Additional data

| Series | Source | Stored | Check |
| --- | --- | ---: | --- |
| ETHUSDT 1h spot | `/api/v3/klines` | 1,613 | Same span as BTC. Sample `2026-10-04 12:00 UTC` close `2697.47000000` matches the database exactly, as does volume. |
| Fear & Greed | `api.alternative.me/fng/?limit=0` | 68 | Every API day on or after `2026-09-01` is present. 0 value or label mismatches. Latest row: `2026-11-07`, `25`, `Extreme Fear`. 0 duplicate dates. |
| Quote volume, trades, taker base/quote | same kline array, indexes 7–10 | on every candle | Present and non-null. Quote and taker-quote have the float nits above. |

No `fapi.binance.com` request was made. The funding-rate fallback (`bitvault_sync.py:54`, `1271`) did not run because Alternative.me responded.

### Proper RDBMS format

Schema as created (`bitvault_sync.py:509-566`), confirmed with `PRAGMA table_info` and `PRAGMA foreign_key_list`:

| Table | Key | Grain | Notes |
| --- | --- | --- | --- |
| `symbols` | `PRIMARY KEY (symbol)` | one row per instrument | `BTCUSDT` / `ETHUSDT`, both `market_type=SPOT` |
| `hourly_klines` | `PRIMARY KEY (symbol, open_time)` | one candle per symbol per hour | `FOREIGN KEY (symbol) REFERENCES symbols(symbol)` |
| `daily_fear_greed` | `PRIMARY KEY (timestamp)` plus `UNIQUE (date_str)` | one print per UTC day | not a column on the hourly table |

Indexes present: `idx_klines_open_time`, `idx_klines_symbol`, `idx_fear_greed_date`, `ux_fear_greed_date`.

Normalization holds. Base and quote asset live once on `symbols`, not on every candle. A daily sentiment print is not copied onto 24 hourly rows. Measures that describe one hour (OHLC, volume, trades, taker flow) live on `hourly_klines`.

`open_datetime TEXT` is the exception. It is `strftime` of `open_time` and is determined by `open_time`, so it is not in third normal form. A check of every stored row found 0 disagreements with `strftime('%Y-%m-%d %H:%M:%S', open_time/1000, 'unixepoch')`. Keeping it is defensible: SQLite has no display formatting in the key, the dashboard and CSV want `YYYY-MM-DD HH:MM:SS`, and the text cannot drift from the integer today because both are written in `KlineRecord.from_binance` (`bitvault_sync.py:235-239`). A stricter design would use a generated column or format at read time.

Integer milliseconds plus that text is the right key design. Binance already identifies a candle by open time in epoch milliseconds. An `INTEGER` primary-key column is exact, sorts correctly, and needs no timezone parser. SQLite has no native timestamp type. Storing the same instant again as UTC text is a cache, not a second clock.

Foreign keys are enforced on the connections the program opens:

```text
PRAGMA foreign_keys -> 1
INSERT hourly_klines symbol='DOGEUSDT' -> IntegrityError: FOREIGN KEY constraint failed
INSERT duplicate (BTCUSDT, existing open_time) -> IntegrityError: UNIQUE constraint failed: hourly_klines.symbol, hourly_klines.open_time
```

A second connection that does **not** run `PRAGMA foreign_keys = ON` accepted the `DOGEUSDT` insert (rolled back, so the audited file was not left dirty). That is SQLite's default, not a missed constraint. `connect()` sets the pragma on every connection (`bitvault_sync.py:662-667`). This is defensible. It is worth knowing that the `sqlite3` CLI will not enforce the foreign key unless the pragma is turned on there too.

`ON CONFLICT(symbol, open_time) DO UPDATE` (`bitvault_sync.py:577-596`) is what makes a re-fetched forming candle overwrite the row instead of inserting a second one. Fear & Greed upserts on `date_str` (`bitvault_sync.py:598-605`) after a unique index is created.

OHLC sanity: 0 rows with low above high, open or close outside the range, or a negative volume.

### Synchronization and the five GUI fields

`incremental_sync` returns before any kline request when `hourly_klines` is missing or BTCUSDT has no rows (`bitvault_sync.py:1347-1355`). The request that does run uses `startTime = MAX(open_time)`, not `MAX + 1 hour` and not `1788220800000` (`bitvault_sync.py:1372-1374` and `1001-1006`). That refreshes the forming hour and appends any hour that has opened since.

Dashboard values come from:

```sql
SELECT COUNT(*), MIN(open_time), MAX(open_time)
FROM hourly_klines WHERE symbol = 'BTCUSDT';
```

(`bitvault_sync.py:607-608`, painted at `2880-2893`). After the sync sequence the widgets read:

| Widget | Value | SQL |
| --- | --- | --- |
| Total Row Count | `1,613` (subtitle: BTC 1,613, ETH 1,613, Fear & Greed 68, all tables 3,294) | `COUNT(*)` = 1613 |
| First Record Timestamp | `2026-09-01 00:00:00 UTC` | `MIN(open_time)` = 1788220800000 |
| Last Record Timestamp | `2026-11-07 04:00:00 UTC` | `MAX(open_time)` = 1794024000000 |

The headline count is BTCUSDT, not 3,294. The card title matches the assignment, and the same card lists every table. A grader who wants the big number to be the sum of all tables can nitpick; the README defines the headline as the BTCUSDT count (`README.md:117`).

Last Record Timestamp is the open time of the newest stored candle, including the hour that is still forming. Its `close_time` is `1794027599999` (`2026-11-07 04:59:59.999 UTC`), which was still in the future at 04:32 UTC. It is not the previous closed hour. Across five syncs inside that hour the row count stayed 1,613 while the live candle's volume moved `266.54208 → 267.2426` and its trade count moved `16,613 → 16,732`.

Verify Integrity, run from the button after the hour-boundary repair, returned:

```text
Integrity: PASS
Duplicate hourly keys: 0 (expect 0)
BTCUSDT gaps: 0 (expect 0)
ETHUSDT gaps: 0 (expect 0)
BTCUSDT: actual 1,613, expected 1,613 (2026-09-01 00:00:00 -> 2026-11-07 04:00:00 UTC)
ETHUSDT: actual 1,613, expected 1,613 (2026-09-01 00:00:00 -> 2026-11-07 04:00:00 UTC)
Fear & Greed duplicate dates: 0 (expect 0)
```

## Part B — Prohibited behaviour

### B1. Sync re-downloads the full history

Absent on the required sequence. Every kline `startTime` captured from `requests.get`:

| Phase | Symbol | startTime (UTC) | Rows | Equals 2026-09-01 00:00? |
| --- | --- | --- | ---: | --- |
| Initialize | BTC, then page 2 | 2026-09-01 00:00, then 2026-10-12 16:00 | 1000 + 613 | Yes. This is the one full load. |
| Initialize | ETH, then page 2 | same two starts | 1000 + 613 | Yes. Full load only. |
| Sync 1 | BTC and ETH | 2026-11-07 04:00 | 1 each | No |
| Sync 2 | BTC and ETH | 2026-11-07 04:00 | 1 each | No |
| Sync 3 | BTC and ETH | 2026-11-07 04:00 | 1 each | No |
| Auto-Sync tick | BTC and ETH | 2026-11-07 04:00 | 1 each | No |
| Sync 4 | BTC and ETH | 2026-11-07 04:00 | 1 each | No |
| Hour-boundary sync | BTC and ETH | 2026-11-07 01:00 | 4 each | No |

The history constant `1788220800000` appears on kline calls only during Initialize. `START_TIMESTAMP_MS` (`1756684800000`, 1 Sep 2025) appears on none. Each of Sync 1–3, the Auto-Sync tick, and Sync 4 logged `API rows=1, new=0, updated=1` per symbol. The tick is the Tk `after` callback: the log line immediately before it is `[AUTO-SYNC]` (`bitvault_sync.py:2660`).

`ensure_continuous` ran after every sync and logged `Continuity OK` with no extra kline call. It does not request the history start when the table is already continuous.

Separate edge case, not part of that sequence: if more than 20 disjoint holes exist, the repair collapses them into one span (`bitvault_sync.py:1141-1142`, disclosed at `README.md:341`). On a copy of the database, 21 isolated hours from `2026-09-02 16:00` to `2026-10-31 00:00` (a 1,400-hour span) made Sync request 1,402 BTC rows and rewrite 1,381 hours that were already stored (`new=21 updated=1381`). The delta itself still started at `2026-11-07 04:00`, not at 1 Sep 2026, and the holes were filled (0 gaps afterwards). This is the only path that re-downloads history, and it is not the path the assignment's sync button uses on a healthy database.

### B2. Sync silently initializes an empty database

Absent.

| Situation | What happened |
| --- | --- |
| No file. `read_init_state()` | `initialized=False`. No file created. No HTTP. |
| GUI launch, then `Sync Database` `invoke()` while disabled | Return value empty, `_busy` stayed false, 0 HTTP calls, `bitvault.db` still absent. |
| `incremental_sync` after `connect()` on a missing file | Log: `[SYNC] Skipped: database not initialized. Click Initialize Database first.` 0 HTTP. `connect()` created a 0-byte file and no tables. |
| Tables exist, 0 kline rows | Same skip log. 0 kline HTTP. Symbol seed rows stay at 2 because `create_schema` runs before the empty check (`bitvault_sync.py:1351-1355`). No history download. |

The 0-byte file is a side effect of `sqlite3.connect` on the direct function call. The button the grader clicks does not take that path: it is disabled (`bitvault_sync.py:2482-2484`) and `invoke()` does not fire.

### B3. Missing hour or duplicate `(symbol, open_time)`

Absent after the sync sequence and after the hour-boundary repair.

The wall clock stayed inside `04:00 UTC` for the whole run, so a natural hour roll was not observed. The boundary path was forced by deleting the three newest hours of both symbols (open times `02:00`, `03:00`, and `04:00` on 7 Nov 2026) and clicking Sync. Sync's last-timestamp line was `2026-11-07 01:00:00 UTC`. Binance returned 4 rows. The log said `new=3 updated=1` for each symbol. Count returned to 1,613. Afterwards:

```text
dup (symbol, open_time) groups: []
gap rows (next open - open != 3600000): []
BTC 1613 rows, 2026-09-01 00:00:00 -> 2026-11-07 04:00:00
unaligned open_time: 0
rows before 2026-09-01: 0
```

Same-hour syncs (Sync 1, 2, 3, Auto-Sync tick, Sync 4) did not insert a row. They updated the forming candle in place.

### B4. Something other than SQLite is the source of truth

Absent. Module imports are only the standard library plus `requests` and `pydantic`. A search of `bitvault_sync.py` finds no `pickle`, `pandas`, `shelve`, `json.dump`, or `sqlite` alternative. The only `open()` is the CSV export (`bitvault_sync.py:1653`), which writes a file the user asked for and is not read back. Dashboard queries all go to `bitvault.db`.

### B5. Manual setup (keys, env, config, CLI args)

Absent for the program itself. `main()` takes no arguments (`bitvault_sync.py:3050-3053`). No environment variable is read. No config file is opened. No API key literal is embedded, because both data sources are keyless public HTTP. The clean-venv launch needed only `pip install -r requirements.txt` and a display.

What a minimal Ubuntu image still needs, and the README does not say: the `python3-tk` package. Before it was installed, `import tkinter` raised `ModuleNotFoundError`. `README.md:23` says Tkinter comes with a standard CPython install. That is true of python.org Windows builds with tcl/tk checked (`README.md:47`) and false of Debian's `python3` package. See Part C.

### B6. Non-spot, non-hourly, or a start later than 2026-09-01 00:00 UTC

Absent.

| Check | Result |
| --- | --- |
| Endpoint | `/api/v3/klines` only. No futures kline URL. |
| `symbols.market_type` | `SPOT` for BTCUSDT and ETHUSDT |
| `interval` on every kline call | `1h` |
| First open time | `2026-09-01 00:00:00 UTC` |
| Rows with `open_time < 1788220800000` | 0 |
| Rows with `open_time % 3600000 != 0` | 0 |
| Server clock before 1 Sep 2026 | No. The 2025 fallback constant was not used. |

### B7. Last Record Timestamp is not the latest stored candle

Absent. Widget text `2026-11-07 04:00:00 UTC` equals `format_utc(MAX(open_time))` for `BTCUSDT`. That row is the maximum `open_time` in the table. It is the forming hour (`close_time` still ahead of the server clock), which is what "up to the current timestamp" requires. It is not `close_time`, and it is not the previous closed candle.

## Part C — Grader-environment robustness

### C1. Three files only, README followed literally

Drop directory started as the three files and nothing else. Commands, in order:

```text
python3 --version
Python 3.12.3

pip install -r requirements.txt
exit 0
Requirement already satisfied: requests==2.34.2
Requirement already satisfied: pydantic==2.14.3

python3 bitvault_sync.py
[04:32:19 UTC] No bitvault.db yet. Click Initialize Database to create the schema and load history since 2026-09-01 UTC.
```

`xwininfo` showed the window `FF-BITVault-Sync — Quantitative Crypto Data Warehouse` at `1280x900+0+0` on a `1280x800` screen. After the process was killed, the directory still had no `bitvault.db`. The first click of Initialize Database (the button command) then created the schema and the 1,613 BTC rows above.

Steps that are ambiguous or fail on this drop:

| README step | Result |
| --- | --- |
| Quick Start option A, `git clone` (`README.md:9`) | Not applicable to a 3-file zip. Cloning the GitHub repo also fetches `tests/`, `requirements-dev.txt`, and `AUDIT_REPORT.md`, which the student was told not to submit. |
| `pip install -r requirements.txt` and `python3 bitvault_sync.py` (`README.md:10-11` and `37-38`) | Works. |
| Click Initialize Database once (`README.md:12`) | Works. Sync stays disabled until that finishes. |
| Tests, `pip install -r requirements-dev.txt` then `pytest` (`README.md:328-333`) | Fails: `Could not open requirements file: requirements-dev.txt`. `tests/` is not in the drop either. |

A grader who stops at "Install and run" is fine. A grader who continues into "Tests" is not, and the README does not say that section needs the git checkout rather than the three-file submission.

### C2. Python 3.10, 3.11, 3.12, 3.13

`uv` 0.13.7 CPython builds, each in its own venv with `requirements.txt` installed (`requests` 2.34.2, `pydantic` 2.14.3). `py_compile` on the submission file, then a headless smoke: import, `resolve_effective_start`, one `KlineRecord`, `create_schema`, construct `BitVaultApp` under Xvfb, destroy it, and one live `/api/v3/time`.

| Python | py_compile | Smoke | Live time call |
| --- | --- | --- | --- |
| 3.10.22 | PASS | PASS. Five labels present. Sync disabled. Window `1280x900+0+0`. | 451 on `api.binance.com`, then vision, `serverTime=1794025939139` |
| 3.11.18 | PASS | PASS, same labels and disabled Sync | vision `serverTime=1794025939140` |
| 3.12.16 | PASS | PASS | vision `serverTime=1794025939161` |
| 3.13.18 | PASS | PASS | vision `serverTime=1794025941105` |

The full history download was run on CPython 3.12.3 (the system interpreter, Tk 8.6). The uv builds use Tk 9.0 and still constructed the window.

No syntax here requires a version newer than 3.10. The file uses `X | Y` unions (`bitvault_sync.py:90` and throughout) and `list[...]` / `tuple[...]` annotations. Those parse on 3.10. `from __future__ import annotations` is present (`bitvault_sync.py:9`) but is not what makes the unions legal; 3.10 is. Underscore separators such as `3600_000` (`bitvault_sync.py:42`) are older than 3.10. There is no `match` statement, `except*`, or `type` alias statement.

### C3. Dependencies

AST import roots: `__future__`, `csv`, `dataclasses`, `datetime`, `os`, `pydantic`, `queue`, `re`, `requests`, `sqlite3`, `subprocess`, `sys`, `threading`, `time`, `tkinter`, `typing`.

Everything except `requests` and `pydantic` is the standard library (Tkinter is stdlib but packaged separately on Debian; see C5 / B5). `requirements.txt` is exactly:

```text
requests
pydantic
```

A clean install pulls `certifi`, `urllib3`, `charset-normalizer`, `idna`, `pydantic-core`, `annotated-types`, `typing-extensions`, and `typing-inspection`. None of those are imported by name. Listing them is not required. The README's mention of `certifi` (`README.md:43`) matches the transitive pin `certifi==2026.10.23`.

The names are unpinned. On 7 Nov 2026 a fresh install resolved pydantic 2.14.3, which provides `ConfigDict`, `field_validator`, and `model_validator` (`bitvault_sync.py:28`). Those are pydantic v2 APIs. `pip install pydantic` does not upgrade an environment that already has pydantic 1.x, because the requirement has no lower bound. A grader machine with leftover pydantic 1 would fail at import. Pin `pydantic>=2`.

### C4. `api.binance.com` blocked with 451, vision fallback, footer host

This environment gets a real 451. No mock was needed.

```text
curl -w '%{http_code}' https://api.binance.com/api/v3/time
451
{"code": 0, "msg": "Service unavailable from a restricted location..."}

curl -w '%{http_code}' https://data-api.binance.vision/api/v3/time
200
{"serverTime":1794025416293}
```

The program's own first call, captured from `requests.get`:

| Order | Status | URL |
| --- | ---: | --- |
| 1 | 451 | `https://api.binance.com/api/v3/time` |
| 2 | 200 | `https://data-api.binance.vision/api/v3/time` |
| 3–6 | 200 | `https://data-api.binance.vision/api/v3/klines` (BTC page, BTC page, ETH page, ETH page) |
| 7 | 200 | `https://api.alternative.me/fng/?limit=0` |

The log line is `[HOST] switched to data-api.binance.vision` (`bitvault_sync.py:452-453`). After that, `_session_host` stays on vision, so the kline calls never touch `api.binance.com` again. HTTP 451 is not retried on the same host (`bitvault_sync.py:419-424` and `457-461`).

Footer text after Initialize, from the label's `StringVar`:

```text
/tmp/grader-submit/bitvault.db · 0.60 MB · API host: data-api.binance.vision (fallback) · v1.0
```

Before any request the same label said `API host: api.binance.com` and the size was `0.00 MB`. `v1.0` is correct for a drop with no `.git` (`app_version()` at `bitvault_sync.py:104-120`). The host string is built by `footer_host_label()` (`bitvault_sync.py:96-101`) and refreshed at the end of the job (`bitvault_sync.py:2761` and `2922-2923`).

The string is right. At 1280×800 the label is not on screen: its top is y=865 and the screen is 800 px tall (Part C.6).

### C5. Windows static review

No Windows machine was booted. Review of path, font, encoding, and newlines:

| Topic | Finding | Class |
| --- | --- | --- |
| Paths | `main` does `os.chdir(os.path.dirname(os.path.abspath(__file__)))` (`bitvault_sync.py:3051`) and opens `bitvault.db` as a relative name (`bitvault_sync.py:70`). No hardcoded `/`. Launching from another directory still writes next to the script, as the README says. | Fine |
| Encoding | The only `open()` passes `encoding="utf-8"` and `newline=""` (`bitvault_sync.py:1653`). The `csv` module then writes `\r\n` on Windows. Source files are LF-only (0 CR bytes). Python accepts LF source. | Fine |
| Console Unicode | Log lines printed during the run are ASCII. The em dash and `·` are Tk strings (title, footer, status), which Unicode Tk handles. A cp1252 console will not be asked to encode those. | Fine |
| Fonts | `win32` tries only Segoe UI and Consolas (`bitvault_sync.py:1733-1734`). If those faces are missing, Tk's default UI and fixed fonts are used. README limitation C12 (`README.md:345`) says Arial, Tahoma, and Courier New are not tried first. | COSMETIC |
| Launcher | README tells Windows to use `py -m pip` and `py bitvault_sync.py` (`README.md:49-51`) and to leave tcl/tk checked. That matches python.org installs. | Fine |

### C6. GUI at 1280×800 under Xvfb

`Xvfb :99 -screen 0 1280x800x24`. `winfo_screenwidth/height` returned `1280` by `800`. The app then did what `_place_window` says (`bitvault_sync.py:1947-1955`): width `min(1480, max(1280, 1200)) = 1280`, height `min(1100, max(900, 720)) = 900`. `minsize` is `1280×860` (`bitvault_sync.py:1923`). The window is 100 px taller than the screen, rooted at `(0, 0)`. There is no window manager to scroll it.

The five required titles, measured from the widget tree:

| Control | x, y, w, h | Fully inside 1280×800 |
| --- | --- | --- |
| Initialize Database | 20, 111, 214×42 | Yes |
| Sync Database | 242, 111, 177×42 | Yes |
| Total Row Count | 35, 214, 272×21 | Yes |
| First Record Timestamp | 345, 214, 272×21 | Yes |
| Last Record Timestamp | 655, 214, 272×21 | Yes |

They do not require scrolling. Sync is greyed out until Initialize has stored BTC rows; after that it is enabled. The status line reads `Start here: click Initialize Database to create tables and load history since 2026-09-01 UTC.` The badge reads `● Not initialized`, which is shorter than the README's `● Not initialized — click Initialize Database first` (`README.md:72` versus `bitvault_sync.py:2564`). After the load the badge is `● Initialized · 1,613 rows`, not the longer README sentence (`README.md:73` versus `bitvault_sync.py:2567`).

What does not fit:

- Timestamp values are 14 pt bold inside a 272 px label. On the screenshot they read `2026-09-01 00:00:00 UT` and `2026-11-07 04:00:00 UT`. The date and clock time are there. The final `C` of `UTC`, and the subtitle `hourly_klines.open_time`, are cut.
- Footer (database path, size, API host, version) is a label at y=865, height 19, bottom 884. It is entirely below y=800. The host text is correct and invisible on this screen.
- Market columns are fixed width and `stretch=False` (`bitvault_sync.py:1793-1805` and `2929-2935`). There is no horizontal scrollbar (`bitvault_sync.py:2345-2348` sets only the vertical one). Sum of column widths = 1,298. Tree width = 1,224.

| Column | x0–x1 | On the 1,224 px tree |
| --- | --- | --- |
| Open Time (UTC) through ETH (USDT) | 0–1220 | Inside |
| Status | 1220–1298 (width 78, minwidth 64) | 4 px inside, 74 px cut off |

The Status heading and the `LIVE` / `CLOSED` cells are not readable. The screenshot of the filled grid stops at `ETH (USDT)`. Widening Open Time to a 195 px minimum (`bitvault_sync.py:2914-2920`) is what pushes Status past the edge. The radio labels on that same row are also cut (`Market Microstructure (BTC & ETH Joine…`).

The in-window activity log starts collapsed (`bitvault_sync.py:2395`). The terminal still printed every API line, so a grader running from a console is not blocked. The log inside the window is below the metric cards and is partly in the region past y=800 once opened.

## Part D — Rubric estimate

| Line | Max | Estimate |
| --- | ---: | ---: |
| BTC price history from Binance | 25 | 25 |
| Additional data, at least one other source | 20 | 20 |
| Stored in a proper RDBMS | 20 | 18 |
| Synchronization | 25 | 23 |
| Functional UI | 10 | 8 |
| **Total** | **100** | **94** |

A generous grader on a wide monitor who only clicks Initialize and Sync twice can reasonably give 98–100. A strict grader who plants 21 holes, diffs quote-volume strings, and marks on a 1280×800 laptop can land near 88. 94 is the mark that fits the code that actually ran.

### Top 3 things a strict grader can deduct

1. **The window does not fit 1280×800.** `minsize(1280, 860)` and a requested height of 900 put the footer at y=865. Fixed columns with no horizontal scroll leave Status 4 px visible. First and Last values clip to `…00 UT`. That is about 2 points on the 10-point UI line. The five required titles themselves are on screen and the buttons work.
2. **Sync can re-download a long span when the hole list is fragmented.** More than 20 separate gaps are replaced by one request from the first hole to the last (`bitvault_sync.py:1141-1142`). The live copy of that path rewrote 1,381 already-stored hours to fill 21 holes. The instructor said fetching everything again is the wrong sync. The normal button does not do that: five syncs each returned 1 row. About 2 points on the 25-point sync line, not a zero.
3. **`REAL` is not an exact decimal, and `open_datetime` repeats `open_time`.** All 1,612 closed OHLC and base-volume values match Binance to 8 decimals. 136 quote volumes and 25 taker-quote volumes are off by `1e-8` when printed, because those notionals have more significant digits than float64. The text timestamp is a pure function of the integer key (0 mismatches) but it is still a second copy. About 2 points on the 20-point schema line.

## Issue register

| Issue | Class | Where |
| --- | --- | --- |
| None of the assignment requirements fail on the happy path. | — | Parts A and B |
| 1280×800 clips Status (4 px of 78), the `UTC` suffix on both timestamp values, and the whole footer (y=865). Window height is forced to 900 and `minsize` is 860. | SHOULD-FIX | `bitvault_sync.py:1923`, `1947-1955`, `1793-1805`, `2345-2348` |
| More than 20 disjoint holes make Sync re-request the span between the first and last hole. Observed: 1,402 API rows, 1,381 updates, for 21 missing hours. | SHOULD-FIX | `bitvault_sync.py:1141-1142`, `README.md:341` |
| Quote and taker-quote notionals stored as `REAL` do not round-trip to 8 decimal places (136 and 25 of 1,612 closed candles). OHLC and base volume do. | SHOULD-FIX | `bitvault_sync.py:529-532` |
| `open_datetime` is determined by `open_time`. Harmless today (0 mismatches) and not third normal form. | SHOULD-FIX | `bitvault_sync.py:522`, `235-239` |
| `pydantic` is unpinned. The code needs v2. A machine that already has v1 will not be upgraded. | SHOULD-FIX | `requirements.txt:2`, `bitvault_sync.py:28` |
| README says Tkinter ships with CPython. On Ubuntu it did not until `python3-tk` was installed (`ModuleNotFoundError` before that). | SHOULD-FIX | `README.md:23` |
| README Tests section installs `requirements-dev.txt` and runs `tests/`, neither of which is in the 3-file drop. Quick Start also leads with `git clone`, which fetches more than those three files. | SHOULD-FIX | `README.md:9`, `328-333` |
| Foreign keys are off unless the connection runs the pragma. The app always does. The `sqlite3` CLI will not. | COSMETIC | `bitvault_sync.py:662-667` |
| Calling `incremental_sync` yourself on a missing file creates a 0-byte `bitvault.db` and downloads nothing. The disabled button does not call it. | COSMETIC | `bitvault_sync.py:662-663`, `1347-1349` |
| Status bar sums BTC, ETH, and Fear & Greed, so a same-hour sync shows `+0 new / 3 updated` while each symbol's log line says `updated=1`. The log is the one the README tells the grader to read, and that log is correct. | COSMETIC | `bitvault_sync.py:1837-1850`, `README.md:324` |
| Badge text is shorter than the README (`● Not initialized` versus the longer sentence). | COSMETIC | `bitvault_sync.py:2564-2567`, `README.md:72-73` |
| Total Row Count's big number is BTCUSDT (1,613), not all tables (3,294). The breakdown is on the same card. | COSMETIC | `bitvault_sync.py:2881-2888`, `README.md:117` |
| Windows font list is Segoe UI and Consolas only. README already lists this as C12. | COSMETIC | `bitvault_sync.py:1733-1734` |
| In-window activity log starts collapsed. The console still prints every API line. | COSMETIC | `bitvault_sync.py:2395` |

## Commands

Hashes and the 451 that this network actually receives:

```text
sha256sum bitvault_sync.py README.md requirements.txt
git rev-parse HEAD
# e68f3919a693b94bfbd0d092ac8e9139c3f7d7e5

curl -w 'api.binance.com %{http_code}\n' https://api.binance.com/api/v3/time
# 451, body code 0, restricted location

curl -w 'data-api.binance.vision %{http_code}\n' https://data-api.binance.vision/api/v3/time
# 200 {"serverTime":1794025416293}
```

Clean drop:

```text
python3 -m venv /tmp/grader-venv
pip install -r requirements.txt          # exit 0, requests 2.34.2, pydantic 2.14.3
python3 bitvault_sync.py                 # window opens, no bitvault.db
pip install -r requirements-dev.txt      # ERROR: no such file
env -u DISPLAY python3 -c 'import bitvault_sync; bitvault_sync.BitVaultApp()'
# import ok; TclError: no display name and no $DISPLAY environment variable
```

Version matrix (each line ended `SMOKE PASS`):

```text
uv python install 3.10 3.11 3.12 3.13
xvfb-run -s '-screen 0 1280x800x24' <venv>/bin/python smoke.py
# 3.10.22, 3.11.18, 3.12.16, 3.13.18: py_compile PASS, five labels present,
# Sync disabled, /api/v3/time failed over to data-api.binance.vision
```

SQL on the database the buttons wrote, after Initialize, five syncs, and the 3-hour repair:

```text
SELECT COUNT(*), MIN(open_time), MAX(open_time)
FROM hourly_klines WHERE symbol='BTCUSDT';
-- 1613 | 1788220800000 | 1794024000000

SELECT symbol, open_time, COUNT(*)
FROM hourly_klines GROUP BY symbol, open_time HAVING COUNT(*) > 1;
-- (no rows)

SELECT symbol, open_time, next_open FROM (
  SELECT symbol, open_time,
         LEAD(open_time) OVER (PARTITION BY symbol ORDER BY open_time) AS next_open
  FROM hourly_klines
) WHERE next_open IS NOT NULL AND next_open - open_time != 3600000;
-- (no rows)

SELECT COUNT(*) FROM hourly_klines WHERE open_time < 1788220800000;
-- 0

SELECT COUNT(*), MIN(date_str), MAX(date_str) FROM daily_fear_greed;
-- 68 | 2026-09-01 | 2026-11-07

PRAGMA foreign_keys;          -- 1 on an app-style connection
-- INSERT of symbol DOGEUSDT -> FOREIGN KEY constraint failed
```
