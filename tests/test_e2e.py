"""Edge-case tests for FF-BITVault-Sync.

The suite calls bitvault_sync directly against a temporary SQLite file. HTTP is
stubbed. Spot calls fail over from api.binance.com to data-api.binance.vision
on HTTP 451/403 or a connection error. GUI cases need a display; run with xvfb
when the machine has none.

    xvfb-run -a -s "-screen 0 1600x1200x24" python3 -m pytest tests/test_e2e.py -vv -s
"""

from __future__ import annotations

import csv
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bitvault_sync as bv


HOUR = bv.HOUR_MS
HISTORY = bv.HISTORY_START_MS


class _Response:
    def __init__(self, body: object, status: int = 200) -> None:
        self.status_code = status
        self._body = body
        self.text = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def json(self) -> object:
        return self._body


class Market:
    """In-process stand-in for Binance spot klines and Alternative.me."""

    def __init__(self, now_ms: int) -> None:
        self.now_ms = now_ms
        self.revision = 0
        self.calls: list[dict] = []
        self._btc_kline_gets = 0
        self.fail_btc_from_get: int | None = None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(bv.requests, "get", self.get)

    def get(self, url: str, params: dict | None = None, timeout: float | None = None, **_kwargs: object) -> _Response:
        query = dict(params or {})
        self.calls.append({"url": url, "params": query})
        if "klines" in url and query.get("symbol") == bv.PRIMARY_SYMBOL:
            self._btc_kline_gets += 1
            if self.fail_btc_from_get is not None and self._btc_kline_gets >= self.fail_btc_from_get:
                raise requests.ConnectionError("network failure mid-pagination")
        if url == bv.BINANCE_TIME_URL or url.endswith("/api/v3/time"):
            return _Response({"serverTime": self.now_ms})
        if "klines" in url:
            return _Response(self._klines(query))
        if "alternative.me" in url or url.rstrip("/").endswith("/fng"):
            return _Response(self._fear())
        if "fundingRate" in url:
            return _Response([])
        if "ticker/24hr" in url:
            return _Response({"priceChangePercent": "1.5", "closeTime": self.now_ms})
        raise AssertionError(f"unexpected URL {url}")

    def _klines(self, params: dict) -> list:
        symbol = str(params["symbol"])
        start = int(params["startTime"])
        limit = int(params.get("limit") or bv.KLINE_LIMIT)
        end_param = params.get("endTime")
        end_param = int(end_param) if end_param is not None else None
        last_hour = bv.floor_hour(self.now_ms)
        cursor = start
        rows: list = []
        while cursor <= last_hour and len(rows) < limit:
            if end_param is not None and cursor > end_param:
                break
            if cursor >= HISTORY and cursor % HOUR == 0:
                rows.append(self._row(symbol, cursor))
            elif cursor % HOUR != 0:
                cursor = bv.floor_hour(cursor) + HOUR
                continue
            cursor += HOUR
        return rows

    def _row(self, symbol: str, open_time: int) -> list:
        step = (open_time - HISTORY) // HOUR
        base = 70000.0 if symbol == bv.PRIMARY_SYMBOL else 2500.0
        close = base + self.revision * 25 + (step % 5)
        open_price = close - 3
        high = close + 8
        low = close - 10
        volume = 10.5 + (step % 3)
        taker = round(volume * 0.4, 2)
        return [
            int(open_time),
            f"{open_price:.2f}",
            f"{high:.2f}",
            f"{low:.2f}",
            f"{close:.2f}",
            f"{volume:.2f}",
            int(open_time + HOUR - 1),
            f"{volume * close:.2f}",
            100 + (step % 7),
            f"{taker:.2f}",
            f"{taker * close:.2f}",
            "0",
        ]

    def _fear(self) -> dict:
        start_day = bv.floor_day(HISTORY)
        end_day = bv.floor_day(self.now_ms)
        data = []
        day = start_day
        while day <= end_day:
            data.append(
                {
                    "value": str(20 + ((day // bv.DAY_MS) % 40)),
                    "value_classification": "Fear",
                    "timestamp": str(day // 1000),
                }
            )
            day += bv.DAY_MS
        data.reverse()
        return {"data": data}


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every connection at a temp file and stay out of the repo directory."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "bitvault.db"
    monkeypatch.setattr(bv, "DB_FILE", str(path))

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    monkeypatch.setattr(bv, "connect", connect)
    monkeypatch.setattr(bv, "_session_host", bv.BINANCE_HOSTS[0])
    monkeypatch.setattr(bv, "LAST_SERVER_TIME_MS", None)
    return path


@pytest.fixture(autouse=True)
def workspace_left_clean() -> None:
    yield
    root = Path(__file__).resolve().parents[1]
    assert not (root / "bitvault.db").exists()
    assert list(root.glob("*.csv")) == []
    assert list(root.glob("ff_bitvault_hourly_*.csv")) == []


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    original = threading.Thread

    def factory(*args: object, **kwargs: object) -> threading.Thread:
        thread = original(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(bv.threading, "Thread", factory)
    return threads


@pytest.fixture
def make_app():
    roots: list[bv.BitVaultApp] = []

    def factory() -> bv.BitVaultApp:
        root = bv.BitVaultApp()
        roots.append(root)
        return root

    yield factory
    for root in roots:
        try:
            root._closing = True
            root._cancel_auto_sync()
            root._heading_fill = None
            root.destroy()
        except Exception:
            pass
    roots.clear()
    import gc
    gc.collect()


def _counts(conn: sqlite3.Connection, symbol: str) -> tuple[int, int | None, int | None]:
    count, first, last = conn.execute(
        "SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ?",
        (symbol,),
    ).fetchone()
    return int(count), first, last


def _duplicate_keys(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT symbol, open_time
                FROM hourly_klines
                GROUP BY symbol, open_time
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
    )


def _assert_continuous(conn: sqlite3.Connection, symbol: str, start: int, last: int) -> None:
    times = [
        int(row[0])
        for row in conn.execute(
            "SELECT open_time FROM hourly_klines WHERE symbol = ? ORDER BY open_time",
            (symbol,),
        )
    ]
    expected = list(range(start, last + 1, HOUR))
    assert times == expected


def _kline_starts(market: Market, symbol: str) -> list[int]:
    starts = []
    for call in market.calls:
        if "klines" not in call["url"]:
            continue
        if call["params"].get("symbol") != symbol:
            continue
        starts.append(int(call["params"]["startTime"]))
    return starts


def _expected_hours(now_ms: int) -> int:
    return (bv.floor_hour(now_ms) - HISTORY) // HOUR + 1


def _drain(app: bv.BitVaultApp, threads: list[threading.Thread], timeout: float = 20) -> None:
    deadline = time.time() + timeout
    for thread in list(threads):
        thread.join(max(0.1, deadline - time.time()))
    assert all(not thread.is_alive() for thread in threads), "worker still running"
    app._poll_queue()
    assert app._busy is False


def _widget_texts(widget: object) -> list[str]:
    texts: list[str] = []
    try:
        value = widget.cget("text")
    except Exception:
        value = ""
    if value:
        texts.append(str(value))
    for child in widget.winfo_children():
        texts.extend(_widget_texts(child))
    return texts


def _after_count(app: bv.BitVaultApp) -> int:
    info = app.tk.call("after", "info")
    if not info:
        return 0
    if isinstance(info, (list, tuple)):
        return len(info)
    return len(str(info).split())


# ---------------------------------------------------------------------------
# 1. Fresh DB → Sync auto-initializes
# ---------------------------------------------------------------------------


def test_01_fresh_sync_auto_initializes_and_is_continuous(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sync on an empty database runs initialization and stores every hour."""
    now = HISTORY + 1049 * HOUR
    market = Market(now)
    market.install(monkeypatch)
    notes: list[str] = []
    conn = bv.connect()
    try:
        bv.incremental_sync(conn, notes.append)
        for symbol in (bv.PRIMARY_SYMBOL, bv.BENCHMARK_SYMBOL):
            count, first, last = _counts(conn, symbol)
            assert count == 1050
            assert first == HISTORY
            assert last == bv.floor_hour(now)
            _assert_continuous(conn, symbol, HISTORY, int(last))
            assert _duplicate_keys(conn) == 0
        raw = market._row(bv.PRIMARY_SYMBOL, HISTORY)
        stored = conn.execute(
            """
            SELECT open_price, high_price, low_price, close_price, volume
            FROM hourly_klines WHERE symbol = ? AND open_time = ?
            """,
            (bv.PRIMARY_SYMBOL, HISTORY),
        ).fetchone()
        assert stored == tuple(float(raw[index]) for index in (1, 2, 3, 4, 5))
        report = bv.verify_integrity(conn, notes.append)
    finally:
        conn.close()

    assert any("not initialized" in note for note in notes)
    assert any(note.startswith("[INITIALIZE] Complete") for note in notes)
    assert report.startswith("Integrity: PASS")
    btc_starts = _kline_starts(market, bv.PRIMARY_SYMBOL)
    eth_starts = _kline_starts(market, bv.BENCHMARK_SYMBOL)
    assert btc_starts[0] == HISTORY
    assert btc_starts[1] == HISTORY + 1000 * HOUR
    assert eth_starts[0] == HISTORY
    for call in market.calls:
        if "klines" in call["url"]:
            assert call["url"] == bv.BINANCE_KLINES_URL
            assert call["params"]["interval"] == "1h"
    print(
        "TEST1 auto-init pages "
        f"BTC startTimes={btc_starts} ETH startTimes={eth_starts} "
        f"rows=1050 integrity=PASS"
    )


# ---------------------------------------------------------------------------
# 2. Initialize, then Sync five times
# ---------------------------------------------------------------------------


def test_02_five_syncs_do_not_redownload_or_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each sync's first kline startTime is MAX(open_time); count grows only by new hours."""
    now = HISTORY + 30 * HOUR
    market = Market(now)
    market.install(monkeypatch)
    conn = bv.connect()
    try:
        bv.initialize_database(conn, lambda _message: None)
        base, _, last = _counts(conn, bv.PRIMARY_SYMBOL)
        assert base == 31
        assert last == now
        steps = (0, 0, 0, 1, 2)
        print("TEST2 startTime capture (every kline request during each sync)")
        for index, step in enumerate(steps, start=1):
            market.now_ms += step * HOUR
            before = {
                symbol: _counts(conn, symbol)[2]
                for symbol in (bv.PRIMARY_SYMBOL, bv.BENCHMARK_SYMBOL)
            }
            before_count = _counts(conn, bv.PRIMARY_SYMBOL)[0]
            market.calls.clear()
            bv.incremental_sync(conn, lambda _message: None)
            for symbol, previous_max in before.items():
                starts = _kline_starts(market, symbol)
                assert starts, symbol
                assert starts[0] == previous_max
                assert min(starts) == previous_max
                assert HISTORY not in starts
            after_count, _, after_last = _counts(conn, bv.PRIMARY_SYMBOL)
            assert after_count - before_count == step
            assert after_last == bv.floor_hour(market.now_ms)
            _assert_continuous(conn, bv.PRIMARY_SYMBOL, HISTORY, int(after_last))
            _assert_continuous(conn, bv.BENCHMARK_SYMBOL, HISTORY, int(after_last))
            assert _duplicate_keys(conn) == 0
            fear_dups = conn.execute(
                "SELECT date_str FROM daily_fear_greed GROUP BY date_str HAVING COUNT(*) > 1"
            ).fetchall()
            assert fear_dups == []
            described = [
                f"{call['params'].get('symbol')}:{call['params'].get('startTime')}"
                for call in market.calls
                if "klines" in call["url"]
            ]
            print(
                f"  sync {index} elapsed_hours={step} "
                f"before_max={before[bv.PRIMARY_SYMBOL]} "
                f"kline_requests={described} btc_delta={after_count - before_count}"
            )
        assert _counts(conn, bv.PRIMARY_SYMBOL)[0] == base + sum(steps)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Auto-Sync tick while a manual Sync holds the database
# ---------------------------------------------------------------------------


def test_03_auto_sync_tick_skips_while_manual_sync_holds_lock(
    temp_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Thread],
    make_app,
) -> None:
    """A tick during a running sync must not start a second writer."""
    hold = threading.Event()
    entered = threading.Event()

    def blocking(conn: sqlite3.Connection, log, progress=bv.noop_progress) -> None:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS lock_probe (id INTEGER PRIMARY KEY)")
        entered.set()
        log("manual sync holding write lock")
        assert hold.wait(8)
        conn.commit()
        log("[INCREMENTAL SYNC] Synced BTCUSDT new=0 updated=0.")

    monkeypatch.setattr(bv, "incremental_sync", blocking)
    app = make_app()
    try:
        app.on_sync()
        assert entered.wait(5), "manual sync did not acquire the write lock"
        other = sqlite3.connect(str(temp_db), timeout=0.2)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()

        assert len(spawned) == 1
        app.auto_sync_var.set(True)
        app._auto_sync_tick()
        app.on_sync()
        app._poll_queue()
        text = app.log_text.get("1.0", "end")
        assert "[AUTO-SYNC] Skipped: a job is already running." in text
        assert "A database job is already running." in text
        assert "database is locked" not in text
        assert len(spawned) == 1
        assert spawned[0].is_alive()
        print("TEST3 second job skipped; log has no 'database is locked'; threads=1")
    finally:
        hold.set()
        _drain(app, spawned)


# ---------------------------------------------------------------------------
# 4. Manual Sync immediately after Auto-Sync
# ---------------------------------------------------------------------------


def test_04_manual_sync_after_auto_sync_keeps_counts(
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Thread],
    make_app,
) -> None:
    now = HISTORY + 6 * HOUR
    market = Market(now)
    market.install(monkeypatch)
    conn = bv.connect()
    try:
        bv.initialize_database(conn, lambda _message: None)
    finally:
        conn.close()

    app = make_app()
    app.auto_sync_var.set(True)
    market.calls.clear()
    spawned.clear()
    app._auto_sync_tick()
    _drain(app, spawned)
    auto_starts = _kline_starts(market, bv.PRIMARY_SYMBOL)

    market.calls.clear()
    spawned.clear()
    app.on_sync()
    _drain(app, spawned)
    manual_starts = _kline_starts(market, bv.PRIMARY_SYMBOL)

    conn = bv.connect()
    try:
        btc, _, last = _counts(conn, bv.PRIMARY_SYMBOL)
        eth, _, _ = _counts(conn, bv.BENCHMARK_SYMBOL)
        assert btc == eth == _expected_hours(now)
        assert last == now
        assert _duplicate_keys(conn) == 0
        report = bv.verify_integrity(conn, lambda _message: None)
    finally:
        conn.close()

    assert auto_starts[0] == now
    assert manual_starts[0] == now
    assert report.startswith("Integrity: PASS")
    assert "database is locked" not in app.log_text.get("1.0", "end")
    print(
        "TEST4 after auto then manual "
        f"auto_start={auto_starts} manual_start={manual_starts} "
        f"btc_rows={btc} duplicates=0"
    )


# ---------------------------------------------------------------------------
# 5. Hour boundary: LIVE candle closes and the next hour is inserted
# ---------------------------------------------------------------------------


def test_05_hour_boundary_updates_closed_candle_and_inserts_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_open = HISTORY + 3 * HOUR
    now = live_open + 30 * 60 * 1000
    market = Market(now)
    market.install(monkeypatch)
    conn = bv.connect()
    try:
        bv.initialize_database(conn, lambda _message: None)
        before = conn.execute(
            "SELECT close_price, close_time FROM hourly_klines WHERE symbol = ? AND open_time = ?",
            (bv.PRIMARY_SYMBOL, live_open),
        ).fetchone()
        assert bv.candle_status(int(before[1]), now) == "LIVE"
        previous = conn.execute(
            "SELECT close_time FROM hourly_klines WHERE symbol = ? AND open_time = ?",
            (bv.PRIMARY_SYMBOL, live_open - HOUR),
        ).fetchone()
        assert bv.candle_status(int(previous[0]), now) == "CLOSED"
        count_before, _, _ = _counts(conn, bv.PRIMARY_SYMBOL)

        market.revision = 1
        market.now_ms = live_open + HOUR + 10 * 60 * 1000
        market.calls.clear()
        bv.incremental_sync(conn, lambda _message: None)

        updated = conn.execute(
            "SELECT close_price, close_time FROM hourly_klines WHERE symbol = ? AND open_time = ?",
            (bv.PRIMARY_SYMBOL, live_open),
        ).fetchone()
        inserted = conn.execute(
            "SELECT close_price, close_time FROM hourly_klines WHERE symbol = ? AND open_time = ?",
            (bv.PRIMARY_SYMBOL, live_open + HOUR),
        ).fetchone()
        count_after, _, last = _counts(conn, bv.PRIMARY_SYMBOL)
        assert updated is not None and inserted is not None
        assert float(updated[0]) != float(before[0])
        assert float(updated[0]) == float(market._row(bv.PRIMARY_SYMBOL, live_open)[4])
        assert float(inserted[0]) == float(market._row(bv.PRIMARY_SYMBOL, live_open + HOUR)[4])
        assert bv.candle_status(int(updated[1]), market.now_ms) == "CLOSED"
        assert bv.candle_status(int(inserted[1]), market.now_ms) == "LIVE"
        assert count_after == count_before + 1
        assert last == live_open + HOUR
        assert _duplicate_keys(conn) == 0
        assert _kline_starts(market, bv.PRIMARY_SYMBOL)[0] == live_open
        rows = conn.execute(
            "SELECT open_time, close_time FROM hourly_klines WHERE symbol = ? ORDER BY open_time",
            (bv.PRIMARY_SYMBOL,),
        ).fetchall()
        for open_time, close_time in rows:
            expected = "LIVE" if int(open_time) == live_open + HOUR else "CLOSED"
            assert bv.candle_status(int(close_time), market.now_ms) == expected
    finally:
        conn.close()
    print(
        "TEST5 hour boundary "
        f"updated_open={live_open} close {before[0]} -> {updated[0]} "
        f"inserted={live_open + HOUR} status CLOSED/LIVE delta=+1"
    )


# ---------------------------------------------------------------------------
# 6. Fear & Greed day boundary
# ---------------------------------------------------------------------------


def test_06_fear_greed_day_boundary_inserts_one_row(monkeypatch: pytest.MonkeyPatch) -> None:
    now = HISTORY + bv.DAY_MS + 22 * HOUR
    market = Market(now)
    market.install(monkeypatch)
    conn = bv.connect()
    try:
        bv.initialize_database(conn, lambda _message: None)
        before = conn.execute("SELECT COUNT(*), MAX(date_str) FROM daily_fear_greed").fetchone()
        assert int(before[0]) == 2
        assert before[1] == "2026-09-02"

        market.now_ms = HISTORY + 2 * bv.DAY_MS + HOUR
        bv.incremental_sync(conn, lambda _message: None)
        after = conn.execute(
            "SELECT date_str, COUNT(*) FROM daily_fear_greed GROUP BY date_str ORDER BY date_str"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM daily_fear_greed").fetchone()[0]
    finally:
        conn.close()

    assert int(total) == int(before[0]) + 1
    assert after == [("2026-09-01", 1), ("2026-09-02", 1), ("2026-09-03", 1)]
    print(f"TEST6 fear/greed dates {after} new_rows=1")


# ---------------------------------------------------------------------------
# 7. Export CSV after multiple syncs
# ---------------------------------------------------------------------------


def test_07_export_csv_matches_btc_rows_without_join_fanout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = HISTORY + 10 * HOUR
    market = Market(now)
    market.install(monkeypatch)
    conn = bv.connect()
    try:
        bv.initialize_database(conn, lambda _message: None)
        market.now_ms += 2 * HOUR
        bv.incremental_sync(conn, lambda _message: None)
        market.now_ms += HOUR
        bv.incremental_sync(conn, lambda _message: None)
        btc, _, _ = _counts(conn, bv.PRIMARY_SYMBOL)
        joined = conn.execute(
            bv.SQL_EXPORT_HOURLY,
            (bv.BENCHMARK_SYMBOL, bv.PRIMARY_SYMBOL),
        ).fetchall()
        fanout = conn.execute(
            f"""
            SELECT open_time, COUNT(*) AS n
            FROM ({bv.SQL_EXPORT_HOURLY})
            GROUP BY open_time
            HAVING n > 1
            """,
            (bv.BENCHMARK_SYMBOL, bv.PRIMARY_SYMBOL),
        ).fetchall()
    finally:
        conn.close()

    path = tmp_path / "export_after_syncs.csv"
    written = bv.export_hourly_csv(str(path), lambda _message: None, now_ms=market.now_ms)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert written == btc == len(rows) == len(joined)
    assert fanout == []
    assert len({row["open_time_utc"] for row in rows}) == len(rows)
    for row in rows:
        for column in ("btc_open", "btc_high", "btc_low", "btc_close", "btc_volume"):
            assert row[column].strip() != ""
            assert row[column].lower() != "nan"
            assert float(row[column]) == float(row[column])
        assert row["eth_close"].strip() != ""
        assert row["fear_greed_value"].strip() != ""
    print(
        f"TEST7 export rows={len(rows)} btc_rows={btc} "
        f"unique_open_time={len({row['open_time_utc'] for row in rows})} fanout=0"
    )


# ---------------------------------------------------------------------------
# 8. Initialize again with Yes
# ---------------------------------------------------------------------------


def test_08_initialize_yes_does_not_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Thread],
    make_app,
) -> None:
    now = HISTORY + 8 * HOUR
    market = Market(now)
    market.install(monkeypatch)
    conn = bv.connect()
    try:
        bv.initialize_database(conn, lambda _message: None)
        before, _, _ = _counts(conn, bv.PRIMARY_SYMBOL)
    finally:
        conn.close()

    asked: dict[str, str] = {}

    def confirm(_title: str, prompt: str, parent: object = None) -> bool:
        asked["prompt"] = prompt
        return True

    monkeypatch.setattr(bv.messagebox, "askyesno", confirm)
    app = make_app()
    market.calls.clear()
    app.on_initialize()
    _drain(app, spawned)

    conn = bv.connect()
    try:
        after, first, last = _counts(conn, bv.PRIMARY_SYMBOL)
        eth, _, _ = _counts(conn, bv.BENCHMARK_SYMBOL)
        assert after == before
        assert eth == before
        assert first == HISTORY
        assert last == now
        assert _duplicate_keys(conn) == 0
        report = bv.verify_integrity(conn, lambda _message: None)
    finally:
        conn.close()

    assert "already initialized" in asked["prompt"]
    assert _kline_starts(market, bv.PRIMARY_SYMBOL)[0] == HISTORY
    assert report.startswith("Integrity: PASS")
    assert not app.btn_init.instate(["disabled"])
    print(f"TEST8 re-init Yes rows={after} unchanged duplicates=0 integrity=PASS")


# ---------------------------------------------------------------------------
# 9. Network failure on page 2
# ---------------------------------------------------------------------------


def test_09_page_two_failure_keeps_committed_page_and_reenables_buttons(
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Thread],
    make_app,
) -> None:
    now = HISTORY + 1500 * HOUR
    market = Market(now)
    market.fail_btc_from_get = 2
    market.install(monkeypatch)
    monkeypatch.setattr(bv.time, "sleep", lambda _seconds: None)

    app = make_app()
    app.on_initialize()
    _drain(app, spawned)

    text = app.log_text.get("1.0", "end")
    assert "ERROR:" in text
    assert "ConnectionError" in text
    assert "network failure mid-pagination" in text
    assert "database is locked" not in text
    for button in (app.btn_init, app.btn_sync, app.btn_verify, app.btn_export):
        assert not button.instate(["disabled"])
    assert app.cget("cursor") == ""
    assert "Failed" in app.status_var.get()

    conn = bv.connect()
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        btc, first, last = _counts(conn, bv.PRIMARY_SYMBOL)
        eth, _, _ = _counts(conn, bv.BENCHMARK_SYMBOL)
        nulls = conn.execute(
            """
            SELECT COUNT(*) FROM hourly_klines
            WHERE open_price IS NULL OR high_price IS NULL OR low_price IS NULL
               OR close_price IS NULL OR volume IS NULL OR open_datetime IS NULL
            """
        ).fetchone()[0]
        symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    finally:
        conn.close()

    assert integrity == "ok"
    assert symbols == 2
    assert btc == bv.KLINE_LIMIT
    assert eth == 0
    assert first == HISTORY
    assert last == HISTORY + (bv.KLINE_LIMIT - 1) * HOUR
    assert nulls == 0
    failing = [
        call["params"].get("startTime")
        for call in market.calls
        if "klines" in call["url"] and call["params"].get("symbol") == bv.PRIMARY_SYMBOL
    ]
    assert failing[0] == HISTORY
    assert failing[1] == HISTORY + bv.KLINE_LIMIT * HOUR
    assert _kline_starts(market, bv.BENCHMARK_SYMBOL) == []
    print(
        "TEST9 page2 failure "
        f"committed_btc={btc} eth={eth} integrity={integrity} "
        f"buttons_enabled status={app.status_var.get()!r}"
    )


# ---------------------------------------------------------------------------
# 10. Timezone: local label, UTC storage
# ---------------------------------------------------------------------------


def test_10_action_label_is_local_and_stored_timestamps_are_utc(
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Thread],
    make_app,
) -> None:
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    try:
        clock = bv.action_clock()
        local = datetime.now().astimezone()
        assert local.utcoffset() == timedelta(hours=8)
        match_ok = _clock_matches_shanghai(clock)
        assert match_ok, clock

        now = HISTORY + 2 * HOUR
        market = Market(now)
        market.install(monkeypatch)
        app = make_app()
        labels = _widget_texts(app)
        for required in (
            "Initialize Database",
            "Sync Database",
            "Total Row Count",
            "First Record Timestamp",
            "Last Record Timestamp",
        ):
            assert any(required in label for label in labels), required

        app.on_sync()
        _drain(app, spawned)
        status = app.status_var.get()
        assert status.startswith("Last Sync:")
        assert _clock_matches_shanghai(status), status

        conn = bv.connect()
        try:
            open_time, open_datetime = conn.execute(
                """
                SELECT open_time, open_datetime
                FROM hourly_klines WHERE symbol = ?
                ORDER BY open_time LIMIT 1
                """,
                (bv.PRIMARY_SYMBOL,),
            ).fetchone()
            count, _, _ = _counts(conn, bv.PRIMARY_SYMBOL)
        finally:
            conn.close()

        assert int(open_time) == HISTORY
        assert open_datetime == "2026-09-01 00:00:00"
        assert bv.format_utc(int(open_time)) == "2026-09-01 00:00:00"
        stamped = datetime.fromtimestamp(int(open_time) / 1000, tz=timezone.utc)
        assert stamped == datetime(2026, 9, 1, tzinfo=timezone.utc)
        assert app.first_value.cget("text") == "2026-09-01 00:00:00 UTC"
        assert app.count_value.cget("text") == f"{count:,}"
        print(
            f"TEST10 action_clock={clock!r} status={status!r} "
            f"stored_open_time={open_time} stored_open_datetime={open_datetime!r} "
            f"first_label={app.first_value.cget('text')!r}"
        )
    finally:
        os.environ["TZ"] = "UTC"
        time.tzset()


def _clock_matches_shanghai(text: str) -> bool:
    import re

    match = re.search(
        r"(\d{2}):(\d{2}):(\d{2}) (.+?) \((\d{2}):(\d{2}):(\d{2}) UTC\)",
        text,
    )
    if match is None:
        return False
    hour, minute, second, name, utc_hour, utc_minute, utc_second = match.groups()
    if name in {"UTC", "GMT"}:
        return False
    local_s = int(hour) * 3600 + int(minute) * 60 + int(second)
    utc_s = int(utc_hour) * 3600 + int(utc_minute) * 60 + int(utc_second)
    delta = (local_s - utc_s) % 86400
    signed = (delta - 8 * 3600 + 43200) % 86400 - 43200
    return abs(signed) <= 2


# ---------------------------------------------------------------------------
# Part C evidence: Auto-Sync toggle does not accumulate Tk timers
# ---------------------------------------------------------------------------


def test_11_auto_sync_toggle_does_not_leak_timers(make_app) -> None:
    app = make_app()
    baseline = _after_count(app)
    assert app._auto_after_id is None
    for _ in range(25):
        app.auto_sync_var.set(True)
        app._on_auto_sync_toggle()
        assert app._auto_after_id is not None
        assert _after_count(app) == baseline + 1
        app.auto_sync_var.set(False)
        app._on_auto_sync_toggle()
        assert app._auto_after_id is None
        assert _after_count(app) == baseline
    print(f"TEST11 auto-sync toggled 25 times; pending after callbacks stayed {baseline} when off")


# ---------------------------------------------------------------------------
# Audit fixes: C1 host failover, C2 tail gap, C3 one Fear & Greed row per date
# ---------------------------------------------------------------------------


def test_12_http_451_on_primary_uses_vision_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """C1: one 451 from api.binance.com switches the session to Vision."""
    now = HISTORY + 2 * HOUR
    market = Market(now)
    primary_hits: list[str] = []

    def get(url: str, params: dict | None = None, timeout: float | None = None, **kwargs: object) -> _Response:
        if "api.binance.com" in url and "data-api.binance.vision" not in url:
            primary_hits.append(url)
            return _Response({"code": 0, "msg": "restricted"}, status=451)
        return market.get(url, params=params, timeout=timeout)

    monkeypatch.setattr(bv.requests, "get", get)
    notes: list[str] = []
    server_ms = bv.fetch_server_time_ms(notes.append)
    assert server_ms == now
    assert any(note == "[HOST] switched to data-api.binance.vision" for note in notes)
    assert sum(1 for url in primary_hits if url.endswith("/api/v3/time")) == 1
    notes.clear()
    market.calls.clear()
    payload = bv.request_json(bv.BINANCE_KLINES_URL, {"symbol": bv.PRIMARY_SYMBOL, "interval": "1h", "startTime": HISTORY, "limit": 2}, notes.append)
    assert isinstance(payload, list) and payload
    assert market.calls[0]["url"].startswith("https://data-api.binance.vision/api/v3/klines")
    assert not any(url.endswith("/api/v3/klines") for url in primary_hits)
    assert not any(note == "[HOST] switched to data-api.binance.vision" for note in notes)
    print(f"TEST12 primary 451s={len(primary_hits)} vision kline={market.calls[0]['url']}")


def test_13_tail_gap_is_reported_and_not_marked_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """C2: hours after the last stored candle through server time are missing."""
    now = HISTORY + 3 * HOUR
    market = Market(now)
    market.install(monkeypatch)
    conn = bv.connect()
    try:
        bv.initialize_database(conn, lambda _message: None)
        market.now_ms = now + 8 * HOUR

        def empty_tail(url: str, params: dict | None = None, timeout: float | None = None, **kwargs: object) -> _Response:
            if "klines" in url:
                market.calls.append({"url": url, "params": dict(params or {})})
                return _Response([])
            return market.get(url, params=params, timeout=timeout)

        monkeypatch.setattr(bv.requests, "get", empty_tail)
        notes: list[str] = []
        bv.incremental_sync(conn, notes.append)
        assert not any(note.startswith("Continuity OK") for note in notes)
        assert any("missing" in note.lower() for note in notes)
        enrichment = bv.load_enrichment(conn)
        assert enrichment.missing_hours and enrichment.missing_hours > 0
        assert "Verified" not in bv.continuity_label(enrichment.missing_hours)
        report = bv.verify_integrity(conn, notes.append)
    finally:
        conn.close()
    assert report.startswith("Integrity: FAIL")
    assert "BTCUSDT gaps" in report
    print(f"TEST13 missing_hours={enrichment.missing_hours} report={report.splitlines()[0]}")


def test_14_duplicate_fear_date_cannot_fan_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """C3: a second Fear & Greed row for the same date updates in place."""
    now = HISTORY + 2 * HOUR
    market = Market(now)
    market.install(monkeypatch)
    conn = bv.connect()
    try:
        bv.initialize_database(conn, lambda _message: None)
        bv.upsert_fear_greed(
            conn,
            [
                bv.FearGreedRecord(
                    timestamp=HISTORY + 12 * HOUR,
                    date_str="2026-09-01",
                    value=99,
                    value_classification="Greed",
                )
            ],
            lambda _message: None,
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM daily_fear_greed WHERE date_str = '2026-09-01'"
        ).fetchone()[0]
        stored = conn.execute(
            "SELECT value FROM daily_fear_greed WHERE date_str = '2026-09-01'"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO daily_fear_greed (timestamp, date_str, value, value_classification) VALUES (?, ?, ?, ?)",
                (HISTORY + 5 * HOUR, "2026-09-01", 1, "Fear"),
            )
        joined = conn.execute(
            bv.SQL_EXPORT_HOURLY,
            (bv.BENCHMARK_SYMBOL, bv.PRIMARY_SYMBOL),
        ).fetchall()
        btc, _, _ = _counts(conn, bv.PRIMARY_SYMBOL)
    finally:
        conn.close()
    assert int(count) == 1
    assert int(stored[0]) == 99
    assert len(joined) == btc
    print(f"TEST14 fear_rows_for_date=1 export_rows={len(joined)} btc_rows={btc}")
