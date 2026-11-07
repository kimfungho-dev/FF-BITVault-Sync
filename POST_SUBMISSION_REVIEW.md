# Post-submission review

Reviewed commit `8d34b43c3d5587ac962f55409ccd3ed756b84c6a` (`8d34b43`, 7 Nov 2026 12:52 Asia/Hong_Kong) on branch `review/post-submission`. `bitvault_sync.py`, `README.md`, and `requirements.txt` were not modified. Nothing was pushed to `main`.

This review re-checks the final compliance audit of `e68f391` (PR #2, `FINAL_AUDIT.md`) and the assignment as run from a three-file folder.

| File | SHA-256 | Lines |
| --- | --- | --- |
| `bitvault_sync.py` | `b5010befdc25dca9f8293fffb48487b1590a61015306f3e2d653c3342363863f` | 3072 |
| `README.md` | `24192c2366cd86384cde6493a50277a6801aca4e29846c0eaadd3b19d68f2c3f` | 340 |
| `requirements.txt` | `c76e76f8cff6c7571a30a1b7f2f37f946a1249d8b4ed22090e9c106116383534` | 2 |

The grader drop was only those three files in `/tmp/grader-drop` (no `.git`, no `tests/`). Live calls ran on 7 Nov 2026 at 16:57 Asia/Hong_Kong (08:57 UTC). Binance `serverTime` during Initialize was `2026-11-07 08:57:00 UTC` (16:57 Asia/Hong_Kong). The newest stored candle opens at `2026-11-07 08:00:00 UTC` (16:00 Asia/Hong_Kong).

Method: follow the README commands in that folder, then import the unmodified module, wrap `requests.get`, and drive the real Tk buttons plus the real Auto-Sync `after` callback. SQL was run on the `bitvault.db` those buttons created. Message boxes were recorded instead of left blocking. Screen was Xvfb `1280x800x24`.

## Verdict

Commit `8d34b43` fixes every item PR #2 scored. Estimated mark **98/100**. There is no HIGH issue. A strict grader can still take the two schema points already in the table below, and can argue for one further UI point because Status and a few secondary labels need the horizontal scrollbar or are a few pixels short.

| Line | Max | At `e68f391` | Now | Why |
| --- | ---: | ---: | ---: | --- |
| BTC price history from Binance | 25 | 25 | 25 | Spot `/api/v3/klines`, `BTCUSDT`, `1h`, from `2026-09-01 00:00:00 UTC` through the forming hour. Closed OHLC and base volume match Binance to 8 decimals. |
| Additional data | 20 | 20 | 20 | ETHUSDT on the same span, plus Alternative.me Fear & Greed, 68/68 days exact. |
| Proper RDBMS | 20 | 18 | 18 | Three normalized tables, composite primary key, foreign keys on the app connection. `REAL` quote notionals and `open_datetime` are unchanged. |
| Synchronization | 25 | 23 | 25 | Sync reads `MAX(open_time)`. The 21-hole repair now requests each missing hour, not the span between the first and last hole. |
| Functional UI | 10 | 8 | 10 | At 1280×800 the window is 1240×720, the five required controls are on screen, both timestamps show `UTC`, and the footer is on screen. Status is reached with the horizontal scrollbar. |
| **Total** | **100** | **94** | **98** | |

## 1. What PR #2 flagged

| Flag at `e68f391` | At `8d34b43` | Evidence |
| --- | --- | --- |
| 1280×800 window is 900 px tall. Footer at y=865. Timestamp values lose the final `C` of `UTC`. Status is 4 px wide and has no horizontal scrollbar. | Fixed for the three scored defects. Status is reachable by scrolling, and is not in the initial viewport. | Section 1.1 |
| More than 20 separate holes make Sync re-request the whole span. A planted case rewrote 1,381 stored hours to fill 21 holes. | Fixed. 21 isolated hours produced 21 one-hour requests per symbol. Stored hours outside those holes were not rewritten. | Section 1.2 |
| Total Row Count headline is the BTCUSDT count (1,613), not every table. | Fixed. Headline is `symbols` + `hourly_klines` + `daily_fear_greed`. | Section 1.3 |
| `pydantic` is unpinned. A machine that already has v1 stays on v1. | Fixed. `pydantic>=2,<3` upgrades 1.10.27 to 2.14.3. | Section 1.4 |
| README leads with `git clone` and a Tests section that needs `tests/` and `requirements-dev.txt`, which are not in the drop. Tkinter-on-Linux is not mentioned. | Fixed. Run instructions target the three-file folder. Tests are under "For developers (GitHub repo only)". Linux Tkinter is documented. | Section 2 |

### 1.1 Window at 1280×800

`winfo_screenwidth/height` returned 1280 by 800. `_place_window` now requests `screen - 40` by `screen - 80`, capped at 1480×1100. `minsize` is 1100×700 (`bitvault_sync.py:1925`, `1949-1957`).

X `xwininfo` on the process started with `python3 bitvault_sync.py`:

```text
"FF-BITVault-Sync — Quantitative Crypto Data Warehouse"  1240x720+20+40
```

The window runs from y=40 to y=760. The screen ends at y=800. The same measurement on `e68f391`, loaded against this database, is still `1280x900+0+0` with the footer at y=865 (bottom 884).

After Initialize, widget geometry:

| Control | x, y, w, h | Inside the 1280×800 screen |
| --- | --- | --- |
| Initialize Database | 40, 151, 214×42 | Yes |
| Sync Database | 262, 151, 177×42 | Yes |
| Total Row Count | 55, 254, 262×21 | Yes |
| First Record Timestamp | 355, 254, 262×21 | Yes |
| Last Record Timestamp | 655, 254, 262×21 | Yes |
| Footer | 40, 725, 1200×19 (bottom 744) | Yes |

Timestamp values, 11 pt bold, wraplength 262:

| Card | Text | Text width | Label size |
| --- | --- | ---: | --- |
| First | `2026-09-01 00:00:00 UTC` | 221 px | 262×23 |
| Last | `2026-11-07 08:00:00 UTC` | 221 px | 262×23 |

Both strings end in `UTC` and sit on one line inside the label. At `e68f391` the same string was 14 pt bold, 285 px wide, in a 272 px label with wraplength 300, which is the clip PR #2 photographed.

Footer text after Initialize, from the label:

```text
/tmp/grader-drop/bitvault.db · 0.60 MB · API host: data-api.binance.vision (fallback) · v1.0
```

`v1.0` is what `app_version()` returns when the folder has no `.git`.

Market columns sum to 1,298 px. The tree viewport is 1,184 px. A horizontal scrollbar is gridded under the tree (`bitvault_sync.py:2350-2354`) and is on screen (y=658, height 14, bottom 672).

| Column | x0–x1 | In the initial viewport |
| --- | --- | --- |
| Open Time (UTC) through Trades | 0–1112 | Fully inside |
| ETH (USDT) | 1112–1220 | 72 px of 108 px |
| Status | 1220–1298 | Fully to the right of the viewport |

`tree.xview_moveto(1)` puts the Status cell at x=1104, width 78, inside the 1,184 px viewport. The current hour reads `LIVE`. Older hours read `CLOSED`. Status is reachable. It is not visible until the user scrolls.

Two secondary labels are still short of their text. They are not the five required controls.

- Each view radio is about 10 px narrower than its caption, and the indicator takes more of that width. On screen the captions end early: `Market Microstructure (BTC & ETH Join`, `Macro Sentiment (daily_fear_greed ta`, `Warehouse Schema & Assets (symbols table + DB st`.
- `Continuity: 0 Missing Hours / Verified` measures 282 px in a 270 px label whose wraplength is still 300, so the line does not wrap and the end of `Verified` is outside the label. At `e68f391` the same string was 282 px in a 280 px label, so this line was already outside the label. The narrower window makes the overflow about 12 px instead of about 2 px.

### 1.2 Twenty-one holes

On a copy of the initialized database, 21 isolated hours were deleted from both symbols, from `2026-09-02 00:00:00 UTC` through `2026-11-05 08:00:00 UTC`. The tail hour `2026-11-07 08:00:00 UTC` was left in place. `incremental_sync` (the function the Sync button calls) then ran.

| What was requested | Result |
| --- | --- |
| Kline calls | 44 |
| Open-ended tail calls | 2 (BTC and ETH), `startTime=2026-11-07 08:00:00 UTC`, 1 row each |
| Repair calls | 42 (21 per symbol) |
| Each repair call | `startTime` = that missing hour, `endTime` = that hour's last millisecond (`…:59:59 UTC`), 1 row |
| `startTime == 2026-09-01 00:00:00 UTC` | 0 |
| Log | `BTCUSDT new=21 updated=1 (API rows=22)` and the same for ETHUSDT |
| Hours that were never deleted | 0 close/volume changes |
| Gaps after the repair | 0 |
| Row count after the repair | 1,617 per symbol, back to the pre-delete count |

The collapse `if len(ranges) > 20: ranges = [(missing[0], missing[-1])]` is gone (`bitvault_sync.py:1144-1158`). The README step that used to describe that collapse now says each contiguous run is its own request (`README.md:303`).

### 1.3 Total Row Count

After Initialize and the sync sequence the card read:

```text
3,304
BTCUSDT klines: 1,617
ETHUSDT klines: 1,617
Fear & Greed: 68
symbols: 2
```

`1,617 + 1,617 + 68 + 2 = 3,304`. The same sum from `COUNT(*)` on `symbols`, `hourly_klines`, and `daily_fear_greed` is 3,304. First Record Timestamp is `2026-09-01 00:00:00 UTC`. Last Record Timestamp is `2026-11-07 08:00:00 UTC`. Both still come from `MIN`/`MAX(open_time)` for `BTCUSDT`.

The header badge stays `● Initialized · 1,617 rows`. The README says that `<N>` is the BTCUSDT hourly count (`README.md:63`). The status line after Initialize says `3,302 rows loaded`, which is the sum of `new=` on the completion line (1,617 + 1,617 + 68). The two `symbols` seed rows are not in that sum. The card breakdown shows them.

### 1.4 `pydantic>=2`

`requirements.txt` is:

```text
requests>=2.28
pydantic>=2,<3
```

A venv that already had pydantic 1.10.27:

| Requirement file | Result |
| --- | --- |
| `e68f391` contents (`requests` / `pydantic`, no bound) | Stayed on 1.10.27. `Requirement already satisfied`. |
| `8d34b43` `requirements.txt` | Uninstalled 1.10.27, installed 2.14.3. `import bitvault_sync` succeeded. |

The literal `pip install -r requirements.txt` in the three-file folder installed requests 2.34.2 and pydantic 2.14.3.

## 2. README, followed literally

Drop listing before any command: `bitvault_sync.py`, `README.md`, `requirements.txt`.

### Run in 3 steps

From `/tmp/grader-drop`, the fenced commands:

```text
pip install -r requirements.txt
```

Exit 0. pip wrote: `Defaulting to user installation because normal site-packages is not writeable`. `python3` (3.12.3) then imported requests 2.34.2 and pydantic 2.14.3. `pip` on this machine is `/usr/bin/pip` with shebang `python3`, so it is the same interpreter.

```text
python3 bitvault_sync.py
```

Under Xvfb 1280×800 the window opened. Stdout:

```text
[08:56:14 UTC] No bitvault.db yet. Click Initialize Database to create the schema and load history.
```

The process was killed without a click. The folder still had no `bitvault.db`.

The next paragraph says to click **Initialize Database** once, then **Sync Database**. That click, driven on the same three files, created the schema and the 1,617 BTC rows in section 3. Sync stayed disabled until that finished. A click on Sync before Initialize invoked nothing, made 0 HTTP calls, and did not create `bitvault.db`.

Ambiguous spots in this section:

| Step | What a reader has to infer |
| --- | --- |
| The heading says "3 steps". The fenced block has two commands. | The third action is the click in the following paragraph. It is not numbered. Following the paragraph works. |
| The fenced block does not `cd`. | The sentence above it says to start in the folder that contains the three files. Copying only the fence from another directory would fail. |
| The command is `pip`, not `python3 -m pip`. | Here they are the same interpreter, and pip fell back to the user site. A `pip` that belongs to another interpreter would install packages `python3` cannot see. The VS Code section describes that failure for the Run button. The 3-step section does not. |

Nothing in the 3-step path failed on this machine.

### Run in VS Code

| Step | Result |
| --- | --- |
| 1. File → Open Folder | Menu action. The `code` command is not installed in this environment, so the menu was not clicked. The folder to open is unambiguous: the one that contains `bitvault_sync.py`. |
| 2. Python: Select Interpreter, Python 3.10 or newer | Command Palette name matches the Python extension's command. The README does not say that extension has to be installed. Without it, the command and **Run → Run Python File** are not in the menus. |
| 3. Terminal → New Terminal, `pip install -r requirements.txt` | Same command as section 2, already run, exit 0. |
| 4. Open `bitvault_sync.py`, Run → Run Python File | Same limitation as step 2. The equivalent `python3 bitvault_sync.py` opened the window. |

The paragraph after the steps is accurate: a Run button on a different interpreter raises `ModuleNotFoundError` for `requests` or `pydantic`, and a missing Tkinter raises no window. On this image, `import tkinter` failed until `python3-tk` was installed. The README now says to run `sudo apt install python3-tk` in that case (`README.md:15`).

The developer section (`README.md:327-338`) says `tests/` and `requirements-dev.txt` are not in the three-file submission and shows `git clone` only there. That is the right split. PR #2's failure mode (a grader running pytest inside the drop) is closed.

## 3. Prohibited behaviour

Every kline `startTime` captured from `requests.get` on the button sequence:

| Phase | Symbol | startTime (UTC) | Rows | History start `2026-09-01 00:00`? |
| --- | --- | --- | ---: | --- |
| Initialize | BTC, then page 2 | 2026-09-01 00:00, then 2026-10-12 16:00 | 1000 + 617 | Yes. This is the one full load. |
| Initialize | ETH, then page 2 | same two starts | 1000 + 617 | Yes. Full load only. |
| Sync 1 | BTC and ETH | 2026-11-07 08:00 | 1 each | No |
| Sync 2 | BTC and ETH | 2026-11-07 08:00 | 1 each | No |
| Sync 3 | BTC and ETH | 2026-11-07 08:00 | 1 each | No |
| Auto-Sync enable (immediate job) | BTC and ETH | 2026-11-07 08:00 | 1 each | No |
| Auto-Sync timer callback | BTC and ETH | 2026-11-07 08:00 | 1 each | No |
| Sync 4 | BTC and ETH | 2026-11-07 08:00 | 1 each | No |

`1788220800000` appears on kline calls only during Initialize. `START_TIMESTAMP_MS` (`1756684800000`, 1 Sep 2025) appears on none. Each of Sync 1–3, both Auto-Sync runs, and Sync 4 logged `API rows=1, new=0, updated=1` per symbol. `ensure_continuous` logged `Continuity OK` and made no extra kline call. The BTCUSDT count stayed 1,617 while the forming hour's volume moved `204.35158 → 204.43321`, its trade count `22,923 → 22,952`, and its close `76,177.93 → 76,177.94`.

| Check | Result |
| --- | --- |
| Sync re-downloads history on the required sequence | No. History start is Initialize only. |
| Sync on an empty database | Button disabled. `invoke()` made 0 HTTP calls and did not create `bitvault.db`. |
| `incremental_sync()` called directly with no file | Logs `[SYNC] Skipped: database not initialized…`, makes 0 kline calls, and `sqlite3.connect` leaves a 0-byte file. The button does not take this path. |
| Duplicate `(symbol, open_time)` | 0 |
| Hour gaps | 0 |
| Rows before `2026-09-01 00:00:00 UTC` | 0 |
| Rows not aligned to an hour | 0 |
| OHLC sanity (low above high, open/close outside the range, negative volume) | 0 |
| Source of truth | SQLite. Imports are the standard library plus `requests` and `pydantic`. No `pandas`, `pickle`, or `shelve`. |
| API key, env var, argparse, dotenv | None. `main()` takes no arguments. |
| Endpoint and market | `/api/v3/klines`, `interval=1h`, `symbols.market_type=SPOT` for BTCUSDT and ETHUSDT. No futures kline URL during the run. |
| Last Record Timestamp | Widget text equals `format_utc(MAX(open_time))` for BTCUSDT, including the forming hour. |

Verify Integrity, from the button, returned `Integrity: PASS` with 0 duplicate keys, 0 gaps, and actual = expected = 1,617 for both symbols from `2026-09-01 00:00:00` through `2026-11-07 08:00:00 UTC`.

Closed-candle comparison against a fresh `data-api.binance.vision` pull, forming hour excluded (1,616 hours):

| Field | BTC candles that differ | ETH candles that differ |
| --- | ---: | ---: |
| open, high, low, close, volume | 0 | 0 |
| taker buy base volume | 0 | 0 |
| close_time, number_of_trades | 0 | 0 |
| quote asset volume | 136 | 40 |
| taker buy quote volume | 25 | 8 |
| missing from the database | 0 | 0 |

The BTC quote mismatches are one unit in the 8th decimal (`100019632.19127170` stored as `100019632.19127171`). That is the float64 behaviour the README now states under Known limitations. Fear & Greed: 68 API days on or after `2026-09-01`, 68 stored, 0 value or label mismatches. Latest print on the card: `25 (Extreme Fear)`.

`api.binance.com` returned HTTP 451 on the first call of Initialize (`{"code": 0, "msg": "Service unavailable from a restricted location…"}`). The log line is `[HOST] switched to data-api.binance.vision`. Later kline and time calls stayed on vision. A direct `curl` in this environment still gets 451 from `api.binance.com` and 200 from vision.

## 4. Python 3.10–3.13

Each uv CPython in its own venv, `requirements.txt` installed, then `py_compile` and a headless smoke under Xvfb 1280×800: import, `resolve_effective_start`, one `KlineRecord`, `create_schema`, construct `BitVaultApp`, destroy it, and one live `/api/v3/time`.

| Python | py_compile | Smoke | Window | Live time |
| --- | --- | --- | --- | --- |
| 3.10.22 | PASS | PASS. Five labels present. Sync disabled. | `1240x720+20+40` | 451 on `api.binance.com`, then vision, `serverTime=1794041848064` |
| 3.11.18 | PASS | PASS, same labels and disabled Sync | `1240x720+20+40` | 451, then vision, `serverTime=1794041849067` |
| 3.12.16 | PASS | PASS | `1240x720+20+40` | 451, then vision, `serverTime=1794041850055` |
| 3.13.18 | PASS | PASS | `1240x720+20+40` | 451, then vision, `serverTime=1794041851062` |

The full history download and the button sequence ran on system CPython 3.12.3 with Tk 8.6. The uv builds use Tk 9.0.4 and still constructed the window. No syntax in the file requires a version newer than 3.10.

The git checkout's own suite (`tests/test_e2e.py`, not part of the drop) passed 16 tests in 1.45 s under Xvfb, including `test_16_twenty_one_holes_request_only_missing_hours`.

## 5. Regression against `e68f391`

The diff of the three submission files is the Total Row Count sum, the window fit, per-range gap repair, the pydantic pin, and the README rewrite. Behaviours that passed at `e68f391` and were re-run here:

| Behaviour | At `8d34b43` |
| --- | --- |
| Initialize from `2026-09-01 00:00:00 UTC`, hourly, spot, no API key | Holds. 1,617 hours, 0 gaps, 0 duplicates. |
| Sync and Auto-Sync `startTime` is the last stored hour | Holds. Six incremental runs, 1 row each. |
| Empty database does not sync | Holds. |
| 451 failover and the footer host label | Holds, and the footer is now on a 1280×800 screen. |
| Closed OHLC and base volume match Binance | Holds. 0 mismatches of 1,616. |
| Foreign key rejects an unknown symbol | Holds. `FOREIGN KEY constraint failed`, then rolled back. |
| Fear & Greed values match Alternative.me | Holds. 68/68. |

The previous test file, pointed at this code, fails one assertion: `test_10` expects the headline count to be the BTCUSDT count. In that fixture the widget now reads `9` (3 BTC + 3 ETH + 1 Fear & Greed + 2 symbols) where the old assertion expected `3`. That is the intended headline change. The updated test in this commit expects the sum. The other old assertions passed. Teardown errors from that out-of-tree run were `git ls-files` in a directory that is not a repository, not product failures.

The continuity subtitle is the one label that has less room than it did. It was already wider than its label at `e68f391` (282 px in 280 px). It is now 282 px in 270 px. No required control that was fully visible at `e68f391` is clipped now. The window is shorter and narrower on purpose, and the required controls, the UTC suffix, and the footer moved onto the screen.

## 6. Strict-grader deductions

Already reflected in the 98:

1. **Quote and taker-quote notionals are `REAL`.** 136 BTC quote volumes and 25 BTC taker-quote volumes, out of 1,616 closed hours, differ from Binance's 8-decimal string by `1e-8`. ETH: 40 and 8. Open, high, low, close, and base volume match. The README now says this. It is still a storage choice a schema mark can penalise. About 2 points on the 20-point line, shared with the next item.
2. **`open_datetime` repeats `open_time`.** 0 disagreements with `strftime('%Y-%m-%d %H:%M:%S', open_time/1000, 'unixepoch')`. It is determined by `open_time`. Kept in the same 2 points, not a second deduction.

A strict grader can still argue for one more point, which this estimate does not take:

3. **At 1280×800, Status and the right side of ETH (USDT) sit past the tree viewport until the user drags the horizontal scrollbar.** The view radios lose the ends of their captions. `Verified` on the enrichment card is about 12 px past its label. The five required controls, both `UTC` suffixes, and the footer are fully on screen, so this estimate leaves the UI line at 10. A grader who wants Status readable with no scrolling can mark the UI line 9 and the paper 97.

Floor if both the schema points and that UI point are taken: 97. The happy path does not fail a requirement.

## 7. Assignment 2 readiness

Assignment 2, as specified for this review, needs hourly open and close (Bull Hour means close ≥ open), hourly volume and the UTC day (a daily-average volume category), a month index from 1 to 12, a date range, and one extra feature such as Fear & Greed, ETH, or taker-buy percent.

The SQLite schema can supply each of those. None of them need a new table. Bull Hour, the UTC calendar fields, and the volume category are derivable at read time. This review does not add them to the database or the exporter.

| Need | Where it is | Checked on this database |
| --- | --- | --- |
| Hourly open and close | `hourly_klines.open_price`, `close_price` for `BTCUSDT` | 1,617 hours. `close_price >= open_price` is true for 809 of them. |
| Hourly volume | `hourly_klines.volume` | Exact against Binance on all 1,616 closed hours. |
| UTC day | `open_time` (epoch ms) or `open_datetime` (`YYYY-MM-DD HH:MM:SS` UTC). `substr(open_datetime, 1, 10)` matches the Fear & Greed `date_str`. | 1 Sep 2026 has 24 hours, average volume 588.7766. 7 Nov 2026 has 9 hours (00:00 through 08:00 UTC) because that day is still in progress. |
| Month index 1–12 | `CAST(substr(open_datetime, 6, 2) AS INTEGER)`, or the UTC month of `open_time` | Distinct values now are 9, 10, and 11. January–August are absent because history starts 1 Sep 2026, not because the column cannot hold 1–12. |
| Date range | `MIN(open_time)`, `MAX(open_time)`, integer milliseconds, hour-aligned | `2026-09-01 00:00:00 UTC` through `2026-11-07 08:00:00 UTC`. A `WHERE open_time BETWEEN ? AND ?` filter is exact. |
| Extra feature | Fear & Greed (`daily_fear_greed`, one row per UTC day), ETH close (same `open_time`), taker-buy base (`taker_buy_base_volume / volume`) | Sample hour `2026-09-01 00:00:00`: bull hour 1, volume 522.7091, month 9, ETH close 2471.61, taker-buy share 64.32%, Fear & Greed 69 Greed. The join for that hour is one row. |

`open_datetime` is safe to use as the UTC display key: 0 rows disagree with the integer. Prefer `open_time` for the range filter and for ordering. Prefer base `volume` over `quote_asset_volume` when the category must match Binance's decimal string.

The current CSV export (`README.md:93`) already joins BTC, ETH, and Fear & Greed per hour. It does not yet emit the calendar fields, the bull-hour flag, or the daily-average category. Those belong in the ETL, computed from the columns above.

### Recommended ETL columns

One row per BTCUSDT hour. Do not write these derived columns back into SQLite for Assignment 2 unless a later spec requires it.

| Column | Type | Rule |
| --- | --- | --- |
| `open_time_utc` | text | `YYYY-MM-DD HH:MM:SS` from `open_time`, UTC |
| `date_utc` | text | `YYYY-MM-DD`, the UTC date of that hour |
| `hour_utc` | integer | 0–23 |
| `month_index` | integer | 1–12, UTC month |
| `btc_open` | decimal | `open_price` |
| `btc_high` | decimal | `high_price` |
| `btc_low` | decimal | `low_price` |
| `btc_close` | decimal | `close_price` |
| `bull_hour` | integer | `1` when `btc_close >= btc_open`, else `0` |
| `btc_volume` | decimal | base `volume` |
| `daily_avg_volume` | decimal | average of `btc_volume` for that `date_utc`, using `CLOSED` hours only |
| `volume_category` | text | `Above average` when `btc_volume >= daily_avg_volume`, else `Below average` |
| `btc_taker_buy_pct` | decimal | `100 * taker_buy_base_volume / volume`, empty when volume is 0 |
| `eth_close` | decimal | ETHUSDT `close_price` on the same `open_time` |
| `btc_eth_ratio` | decimal | `btc_close / eth_close` when ETH close is present and not 0 |
| `fear_greed_value` | integer | `daily_fear_greed.value` on `date_utc` |
| `fear_greed_class` | text | `value_classification` for that date |
| `candle_status` | text | `LIVE` when `close_time` is still at or after the export clock, else `CLOSED` |

The category labels are a recommendation. The brief names the category and does not name the buckets. `Above average` / `Below average` is the split the stored hourly volume and the UTC day can support without a second data source.

Two caveats for that ETL:

- The hour that is still forming (`LIVE`) should stay out of `daily_avg_volume` and out of a backtest. Its volume is a partial hour and changes on the next Sync.
- The current UTC day has fewer than 24 closed hours. Its average is a partial-day average until that day is complete. Carry `candle_status` so a later job can recompute the category for that date.

## Issue register

No HIGH issue. The assignment requirements that PR #2 passed still pass, and the five scored defects from that audit are fixed.

| Class | Issue | Where |
| --- | --- | --- |
| MEDIUM | Quote and taker-quote notionals stored as `REAL` differ from Binance's 8-decimal string by `1e-8` on 136 and 25 of 1,616 closed BTC hours (ETH 40 and 8). OHLC and base volume match. Disclosed in the README. This is the remaining schema deduction. | `bitvault_sync.py` `quote_asset_volume`, `taker_buy_quote_volume` |
| LOW | `open_datetime` is a second copy of `open_time`. 0 mismatches. Disclosed. | `hourly_klines.open_datetime` |
| LOW | At 1280×800, Status is fully to the right of the tree until the horizontal scrollbar is used. About 36 px of ETH (USDT) are in that same overflow. | `MARKET_COLUMNS`, tree viewport 1,184 vs columns 1,298 |
| LOW | The three view radios lose the ends of their captions at this width. | toolbar radios under the cards |
| LOW | `Continuity: 0 Missing Hours / Verified` is 282 px in a 270 px label and does not wrap (`wraplength` 300). About 12 px of the word sits outside the label. At `e68f391` the overflow was about 2 px. | enrichment card subtitle |
| LOW | "Run in 3 steps" puts two commands in the fence and the click in the next paragraph. `pip` is not `python3 -m pip`. VS Code steps 2 and 4 assume the Python extension, which is not named. All of these were followable or, for the menus, blocked only because `code` is not installed here. | `README.md` "Run in 3 steps", "Run in VS Code" |
| LOW | The status line's `3,302 rows loaded` omits the two `symbols` seed rows that the Total Row Count card includes. The card breakdown shows the 2. | completion summary vs `DashboardMetrics.all_tables` |
| LOW | Calling `incremental_sync` directly on a missing file creates a 0-byte `bitvault.db` and downloads nothing. The disabled button does not call it. | `connect()`, `incremental_sync` |
| LOW | Foreign keys are enforced on the app connection (`PRAGMA foreign_keys = ON` returned 1; a `DOGEUSDT` insert failed). The `sqlite3` CLI will not enforce them until the pragma is turned on. | `connect()` |
| LOW | C9–C12 are unchanged and still listed in the README: closing the window does not wait for the daemon worker; out-of-window candles are dropped without a count; any SQLite error in `read_init_state` looks uninitialized; the Windows font list is Segoe UI and Consolas, then Tk defaults. | README "Known limitations" |

## Commands

```text
sha256sum bitvault_sync.py README.md requirements.txt
git rev-parse HEAD
# 8d34b43c3d5587ac962f55409ccd3ed756b84c6a

# three-file drop
pip install -r requirements.txt          # exit 0, requests 2.34.2, pydantic 2.14.3
python3 bitvault_sync.py                 # window 1240x720+20+40, no bitvault.db until Initialize

curl -w 'api.binance.com %{http_code}\n' https://api.binance.com/api/v3/time
# 451, restricted location

curl -w 'data-api.binance.vision %{http_code}\n' https://data-api.binance.vision/api/v3/time
# 200

# version matrix, each line SMOKE PASS, 451 then vision
# 3.10.22, 3.11.18, 3.12.16, 3.13.18

# git checkout only
python3 -m pytest tests/test_e2e.py -q
# 16 passed
```

SQL on the database the buttons wrote, after Initialize and the sync sequence:

```text
SELECT COUNT(*), MIN(open_time), MAX(open_time)
FROM hourly_klines WHERE symbol='BTCUSDT';
-- 1617 | 1788220800000 | 1794038400000

SELECT (SELECT COUNT(*) FROM symbols)
     + (SELECT COUNT(*) FROM hourly_klines)
     + (SELECT COUNT(*) FROM daily_fear_greed);
-- 3304

SELECT COUNT(*) FROM (
  SELECT symbol, open_time FROM hourly_klines
  GROUP BY symbol, open_time HAVING COUNT(*) > 1
);
-- 0

-- hour gaps (next open - open != 3600000): 0
-- rows with open_time < 1788220800000: 0
-- Fear & Greed: 68 | 2026-09-01 | 2026-11-07
```
