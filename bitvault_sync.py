#!/usr/bin/env python3
"""FF-BITVault-Sync — quantitative crypto data warehouse terminal.

Hourly BTCUSDT and ETHUSDT spot candles plus the daily Crypto Fear & Greed
index, stored in a normalized SQLite database. "Sync Database" fetches only
the hours after the last stored candle. It does not download the history again.
"""

from __future__ import annotations

import csv
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import requests
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator


# ---------------------------------------------------------------------------
# History window
# ---------------------------------------------------------------------------

# 2025-09-01 00:00:00 UTC. Used only when the exchange clock is still before 1 Sep 2026.
START_TIMESTAMP_MS = 1756684800000

# 2026-09-01 00:00:00 UTC. History start once Binance server time has reached that instant.
HISTORY_START_MS = 1788220800000

LOOKBACK_DAYS = 67
HOUR_MS = 3600_000
DAY_MS = 24 * HOUR_MS
KLINE_LIMIT = 1000
REQUEST_TIMEOUT_SECONDS = 15
AUTO_SYNC_INTERVAL_MS = 5 * 60 * 1000

BINANCE_HOSTS = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)
BINANCE_TIME_URL = "https://api.binance.com/api/v3/time"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
FEAR_GREED_URL = "https://api.alternative.me/fng/"
SPOT_PATHS = ("/api/v3/time", "/api/v3/klines", "/api/v3/ticker/24hr")
# Session memory: the last spot host that answered. 451/403 and connection
# failures move the next call to the other host.
_session_host = BINANCE_HOSTS[0]
LAST_SERVER_TIME_MS: int | None = None

PRIMARY_SYMBOL = "BTCUSDT"
BENCHMARK_SYMBOL = "ETHUSDT"
TRACKED_SYMBOLS = (
    (PRIMARY_SYMBOL, "BTC", "USDT", "SPOT"),
    (BENCHMARK_SYMBOL, "ETH", "USDT", "SPOT"),
)

DB_FILE = "bitvault.db"

LogFn = Callable[[str], None]
ProgressFn = Callable[[float, str], None]


def noop_progress(_percent: float, _text: str) -> None:
    return None


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def format_utc(timestamp_ms: int) -> str:
    """Return YYYY-MM-DD HH:MM:SS in UTC, without a timezone suffix."""
    moment = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def format_utc_label(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "—"
    return f"{format_utc(timestamp_ms)} UTC"


def footer_host_label() -> str:
    """Hostname of the spot host in use. Vision is marked as the fallback."""
    name = _session_host.replace("https://", "").replace("http://", "").strip("/")
    if name == "data-api.binance.vision":
        return "data-api.binance.vision (fallback)"
    return "api.binance.com"


def app_version() -> str:
    """Short git commit of this file, or v1.0 when git cannot answer."""
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        completed = subprocess.run(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "v1.0"
    short = completed.stdout.strip()
    if completed.returncode != 0 or not short or any(char.isspace() for char in short):
        return "v1.0"
    return short


def footer_status() -> str:
    """Absolute database path, size, current spot host, and version."""
    path = os.path.abspath(DB_FILE)
    try:
        size_mb = os.path.getsize(path) / (1024 * 1024)
    except OSError:
        size_mb = 0.0
    return f"{path} · {size_mb:.2f} MB · API host: {footer_host_label()} · {app_version()}"


def floor_hour(timestamp_ms: int) -> int:
    return (timestamp_ms // HOUR_MS) * HOUR_MS


def floor_day(timestamp_ms: int) -> int:
    moment = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    midnight = datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)
    return int(midnight.timestamp() * 1000)


def resolve_effective_start(server_time_ms: int) -> tuple[int, str]:
    """Pick a start that is inside the exchange's real history.

    Prefer 1 Sep 2026 when Binance has reached that instant. If the exchange
    clock is still earlier, use START_TIMESTAMP_MS (1 Sep 2025) when that is
    already in the past, otherwise a 67-day lookback aligned to the hour.
    """
    server_label = format_utc_label(server_time_ms)
    if server_time_ms >= HISTORY_START_MS:
        return HISTORY_START_MS, (
            f"Binance serverTime {server_label} is at or after 1 Sep 2026. "
            f"Loading hourly candles from {format_utc_label(HISTORY_START_MS)} "
            f"({HISTORY_START_MS}). "
            f"START_TIMESTAMP_MS={START_TIMESTAMP_MS} "
            f"({format_utc_label(START_TIMESTAMP_MS)}) stays as the fallback "
            "when 1 Sep 2026 is still in the future."
        )
    if server_time_ms > START_TIMESTAMP_MS:
        return START_TIMESTAMP_MS, (
            f"Binance serverTime {server_label} is before 1 Sep 2026. "
            f"Falling back to START_TIMESTAMP_MS={START_TIMESTAMP_MS} "
            f"({format_utc_label(START_TIMESTAMP_MS)}) so the fact table still loads."
        )
    lookback = floor_hour(server_time_ms - LOOKBACK_DAYS * DAY_MS)
    return lookback, (
        f"Binance serverTime {server_label} is before 1 Sep 2025. "
        f"Falling back to a {LOOKBACK_DAYS}-day lookback at {format_utc_label(lookback)} "
        "so the fact table still loads with real hourly candles."
    )


# ---------------------------------------------------------------------------
# Pydantic models — validate API payloads before any INSERT
# ---------------------------------------------------------------------------

def _as_int(value: object) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("expected an integer")
    if isinstance(value, int):
        return value
    return int(float(str(value)))


class KlineRecord(BaseModel):
    """One Binance spot kline. The raw payload is a 12-field array, not an object."""

    model_config = ConfigDict(extra="ignore")

    symbol: str
    open_time: int
    open_datetime: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    close_time: int
    quote_asset_volume: float
    number_of_trades: int
    taker_buy_base_volume: float
    taker_buy_quote_volume: float

    @field_validator("open_time", "close_time", "number_of_trades", mode="before")
    @classmethod
    def parse_ints(cls, value: object) -> int:
        return _as_int(value)

    @model_validator(mode="after")
    def check_candle(self) -> "KlineRecord":
        tolerance = 1e-8
        if self.low_price - tolerance > self.high_price:
            raise ValueError("low_price is above high_price")
        if self.open_price + tolerance < self.low_price or self.open_price - tolerance > self.high_price:
            raise ValueError("open_price is outside the low/high range")
        if self.close_price + tolerance < self.low_price or self.close_price - tolerance > self.high_price:
            raise ValueError("close_price is outside the low/high range")
        if self.volume < 0 or self.quote_asset_volume < 0:
            raise ValueError("volume cannot be negative")
        if self.taker_buy_base_volume < 0 or self.taker_buy_quote_volume < 0:
            raise ValueError("taker volume cannot be negative")
        if self.number_of_trades < 0:
            raise ValueError("number_of_trades cannot be negative")
        if self.close_time < self.open_time:
            raise ValueError("close_time is earlier than open_time")
        if not self.symbol:
            raise ValueError("symbol is empty")
        return self

    @classmethod
    def from_binance(cls, symbol: str, row: list) -> "KlineRecord":
        if not isinstance(row, list) or len(row) < 11:
            raise ValueError("Binance kline row must contain at least 11 fields")
        open_time = _as_int(row[0])
        return cls(
            symbol=symbol,
            open_time=open_time,
            open_datetime=format_utc(open_time),
            open_price=row[1],
            high_price=row[2],
            low_price=row[3],
            close_price=row[4],
            volume=row[5],
            close_time=row[6],
            quote_asset_volume=row[7],
            number_of_trades=row[8],
            taker_buy_base_volume=row[9],
            taker_buy_quote_volume=row[10],
        )

    def as_tuple(self) -> tuple:
        return (
            self.symbol,
            self.open_time,
            self.open_datetime,
            self.open_price,
            self.high_price,
            self.low_price,
            self.close_price,
            self.volume,
            self.close_time,
            self.quote_asset_volume,
            self.number_of_trades,
            self.taker_buy_base_volume,
            self.taker_buy_quote_volume,
        )


class FundingRateRecord(BaseModel):
    """One Binance USD-M funding print. Used only if Fear & Greed is unreachable."""

    model_config = ConfigDict(extra="ignore")

    symbol: str
    funding_time: int
    funding_rate: float
    mark_price: float | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_binance_payload(cls, data: object) -> object:
        if isinstance(data, dict) and "fundingTime" in data:
            mark_price = data.get("markPrice")
            if mark_price in ("", None):
                mark_price = None
            return {
                "symbol": data.get("symbol") or PRIMARY_SYMBOL,
                "funding_time": data["fundingTime"],
                "funding_rate": data["fundingRate"],
                "mark_price": mark_price,
            }
        return data

    @field_validator("funding_time", mode="before")
    @classmethod
    def parse_funding_time(cls, value: object) -> int:
        return _as_int(value)

    @model_validator(mode="after")
    def check_funding(self) -> "FundingRateRecord":
        if self.funding_time <= 0:
            raise ValueError("funding_time must be positive")
        if not self.symbol:
            raise ValueError("symbol is empty")
        return self


class FearGreedRecord(BaseModel):
    """One daily Crypto Fear & Greed print from Alternative.me.

    The public payload stores `timestamp` as Unix seconds (a string) and
    `value` as a string. Both are coerced before the row is inserted.
    """

    model_config = ConfigDict(extra="ignore")

    timestamp: int
    date_str: str
    value: int
    value_classification: str

    @model_validator(mode="before")
    @classmethod
    def accept_alternative_me(cls, data: object) -> object:
        if not isinstance(data, dict) or "date_str" in data:
            return data
        if "timestamp" not in data or "value" not in data:
            return data
        raw_timestamp = _as_int(data["timestamp"])
        timestamp_ms = raw_timestamp * 1000 if raw_timestamp < 10**12 else raw_timestamp
        return {
            "timestamp": timestamp_ms,
            "date_str": format_utc(timestamp_ms)[:10],
            "value": data["value"],
            "value_classification": data.get("value_classification", ""),
        }

    @field_validator("timestamp", "value", mode="before")
    @classmethod
    def parse_ints(cls, value: object) -> int:
        return _as_int(value)

    @model_validator(mode="after")
    def check_record(self) -> "FearGreedRecord":
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if len(self.date_str) != 10:
            raise ValueError("date_str must be YYYY-MM-DD")
        if not self.value_classification.strip():
            raise ValueError("value_classification is empty")
        return self

    def as_tuple(self) -> tuple:
        return (self.timestamp, self.date_str, self.value, self.value_classification)


def funding_records_to_fear_greed(records: list[FundingRateRecord]) -> list[FearGreedRecord]:
    """Collapse 8-hour funding prints into one daily fallback sentiment row."""
    latest_by_day: dict[str, FundingRateRecord] = {}
    for record in records:
        day = format_utc(record.funding_time)[:10]
        current = latest_by_day.get(day)
        if current is None or record.funding_time >= current.funding_time:
            latest_by_day[day] = record

    daily: list[FearGreedRecord] = []
    for day in sorted(latest_by_day):
        record = latest_by_day[day]
        if record.funding_rate > 0:
            mood = "Greed"
        elif record.funding_rate < 0:
            mood = "Fear"
        else:
            mood = "Neutral"
        daily.append(
            FearGreedRecord(
                timestamp=floor_day(record.funding_time),
                date_str=day,
                value=int(round(record.funding_rate * 1_000_000)),
                value_classification=f"Funding fallback ({record.symbol}): {mood}",
            )
        )
    return daily


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _request_json(url: str, params: dict, log: LogFn) -> object:
    """GET a JSON document. raise_for_status() runs immediately after the GET."""
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise ValueError(f"Response from {url} was not JSON") from exc

    if isinstance(body, list):
        summary = f"{len(body)} rows"
    elif isinstance(body, dict) and "serverTime" in body:
        summary = f"serverTime={body['serverTime']}"
    elif isinstance(body, dict) and isinstance(body.get("data"), list):
        summary = f"{len(body['data'])} rows"
    else:
        summary = "ok"
    log(f"API GET {url} params={params} -> {summary}")
    return body


def _spot_path(url: str) -> str | None:
    for path in SPOT_PATHS:
        if url.endswith(path):
            return path
    return None


def _request_with_same_host_retries(url: str, params: dict, log: LogFn) -> object:
    """Retry rate limits and connection errors on one host.

    HTTP 451 and 403 are not in this set. The spot host loop handles those
    by moving the same path to the next host.
    """
    retry_statuses = {418, 429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            return _request_json(url, params, log)
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else None
            if status not in retry_statuses or attempt == 3:
                raise
            log(f"WARNING: HTTP {status} from {url}. Retry {attempt}/3.")
            time.sleep(attempt)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt == 3:
                raise
            log(f"WARNING: {type(exc).__name__} calling {url}. Retry {attempt}/3.")
            time.sleep(attempt)
    raise RuntimeError(f"request failed: {last_error}")


def _request_spot(path: str, params: dict, log: LogFn) -> object:
    """Try the session host, then the other public host, for one spot path."""
    global _session_host
    ordered = [_session_host] + [host for host in BINANCE_HOSTS if host != _session_host]
    last_error: Exception | None = None
    for index, host in enumerate(ordered):
        if index > 0 and host == "https://data-api.binance.vision":
            log("[HOST] switched to data-api.binance.vision")
        url = f"{host}{path}"
        try:
            body = _request_with_same_host_retries(url, params, log)
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else None
            if status in {403, 451} and index < len(ordered) - 1:
                continue
            raise
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if index < len(ordered) - 1:
                continue
            raise
        _session_host = host
        return body
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"request failed for {path}")


def request_json(url: str, params: dict, log: LogFn) -> object:
    """Call `_request_json`, retrying rate limits and transient network errors.

    Spot `/api/v3/time`, `/api/v3/klines`, and `/api/v3/ticker/24hr` walk
    `BINANCE_HOSTS` when the current host returns 451/403 or cannot be reached.
    """
    path = _spot_path(url)
    if path is None:
        return _request_with_same_host_retries(url, params, log)
    return _request_spot(path, params, log)


def fetch_server_time_ms(log: LogFn) -> int:
    global LAST_SERVER_TIME_MS
    params: dict = {}
    try:
        payload = request_json(BINANCE_TIME_URL, params, log)
        if not isinstance(payload, dict) or "serverTime" not in payload:
            raise ValueError(f"unexpected time payload: {payload!r}")
        server_ms = _as_int(payload["serverTime"])
    except (requests.RequestException, ValueError, TypeError) as exc:
        server_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        log(
            f"WARNING: Binance server time is unavailable ({exc}). "
            f"Using the local UTC clock {format_utc_label(server_ms)}."
        )
    LAST_SERVER_TIME_MS = server_ms
    return server_ms


# ---------------------------------------------------------------------------
# SQLite schema, upserts, and the queries the dashboard reads
# ---------------------------------------------------------------------------

SQL_CREATE_SYMBOLS = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    base_asset TEXT NOT NULL,
    quote_asset TEXT NOT NULL,
    market_type TEXT NOT NULL
)
"""

SQL_CREATE_KLINES = """
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
)
"""

SQL_INDEX_KLINES_OPEN_TIME = (
    "CREATE INDEX IF NOT EXISTS idx_klines_open_time ON hourly_klines (open_time)"
)
SQL_INDEX_KLINES_SYMBOL = (
    "CREATE INDEX IF NOT EXISTS idx_klines_symbol ON hourly_klines (symbol)"
)

SQL_CREATE_FEAR_GREED = """
CREATE TABLE IF NOT EXISTS daily_fear_greed (
    timestamp INTEGER PRIMARY KEY,
    date_str TEXT NOT NULL,
    value INTEGER NOT NULL,
    value_classification TEXT NOT NULL
)
"""

SQL_INDEX_FEAR_GREED_DATE = (
    "CREATE INDEX IF NOT EXISTS idx_fear_greed_date ON daily_fear_greed (date_str)"
)
SQL_DEDUPE_FEAR_DATES = """
DELETE FROM daily_fear_greed
WHERE timestamp NOT IN (
    SELECT MAX(timestamp) FROM daily_fear_greed GROUP BY date_str
)
"""
SQL_UNIQUE_FEAR_DATE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_fear_greed_date "
    "ON daily_fear_greed(date_str)"
)

SQL_UPSERT_SYMBOL = """
INSERT INTO symbols (symbol, base_asset, quote_asset, market_type)
VALUES (?, ?, ?, ?)
ON CONFLICT(symbol) DO UPDATE SET
    base_asset = excluded.base_asset,
    quote_asset = excluded.quote_asset,
    market_type = excluded.market_type
"""

SQL_UPSERT_KLINE = """
INSERT INTO hourly_klines (
    symbol, open_time, open_datetime,
    open_price, high_price, low_price, close_price, volume,
    close_time, quote_asset_volume, number_of_trades,
    taker_buy_base_volume, taker_buy_quote_volume
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(symbol, open_time) DO UPDATE SET
    open_datetime = excluded.open_datetime,
    open_price = excluded.open_price,
    high_price = excluded.high_price,
    low_price = excluded.low_price,
    close_price = excluded.close_price,
    volume = excluded.volume,
    close_time = excluded.close_time,
    quote_asset_volume = excluded.quote_asset_volume,
    number_of_trades = excluded.number_of_trades,
    taker_buy_base_volume = excluded.taker_buy_base_volume,
    taker_buy_quote_volume = excluded.taker_buy_quote_volume
"""

SQL_UPSERT_FEAR_GREED = """
INSERT INTO daily_fear_greed (timestamp, date_str, value, value_classification)
VALUES (?, ?, ?, ?)
ON CONFLICT(date_str) DO UPDATE SET
    timestamp = excluded.timestamp,
    value = excluded.value,
    value_classification = excluded.value_classification
"""

SQL_BTC_METRICS = (
    "SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ?"
)

SQL_MARKET = """
SELECT
    b.open_time,
    b.open_price,
    b.high_price,
    b.low_price,
    b.close_price,
    b.volume,
    b.quote_asset_volume,
    b.taker_buy_base_volume,
    b.number_of_trades,
    e.close_price,
    b.close_time
FROM hourly_klines AS b
LEFT JOIN hourly_klines AS e
    ON e.symbol = ? AND e.open_time = b.open_time
WHERE b.symbol = ?
ORDER BY b.open_time DESC
LIMIT 15
"""

SQL_SENTIMENT = """
SELECT date_str, timestamp, value, value_classification
FROM daily_fear_greed
ORDER BY timestamp DESC
"""

SQL_SYMBOLS = """
SELECT symbol, base_asset, quote_asset, market_type
FROM symbols
ORDER BY symbol
"""

SQL_LATEST_FEAR = """
SELECT value, value_classification
FROM daily_fear_greed
ORDER BY timestamp DESC
LIMIT 1
"""

SQL_LATEST_RATIO = """
SELECT b.close_price, e.close_price
FROM hourly_klines AS b
INNER JOIN hourly_klines AS e
    ON e.symbol = ? AND e.open_time = b.open_time
WHERE b.symbol = ?
ORDER BY b.open_time DESC
LIMIT 1
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 5000")
    return conn


def create_schema(conn: sqlite3.Connection, log: LogFn) -> None:
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON")
    enabled = c.execute("PRAGMA foreign_keys").fetchone()[0]
    log(f"SQL: PRAGMA foreign_keys = ON -> {enabled}")
    statements = (
        SQL_CREATE_SYMBOLS,
        SQL_CREATE_KLINES,
        SQL_INDEX_KLINES_OPEN_TIME,
        SQL_INDEX_KLINES_SYMBOL,
        SQL_CREATE_FEAR_GREED,
        SQL_INDEX_FEAR_GREED_DATE,
        SQL_DEDUPE_FEAR_DATES,
        SQL_UNIQUE_FEAR_DATE,
    )
    # table_exists is defined just below. A repeat sync should not reprint the DDL.
    fresh = not table_exists(conn, "hourly_klines")
    for statement in statements:
        if fresh:
            log(f"SQL: {' '.join(statement.split())}")
        c.execute(statement)
    if not fresh:
        log(
            "SQL: CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS "
            "confirmed symbols, hourly_klines, daily_fear_greed, and idx_klines_open_time."
        )
    log(
        "SQL: executemany INSERT INTO symbols "
        "(symbol, base_asset, quote_asset, market_type) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET ..."
    )
    c.executemany(SQL_UPSERT_SYMBOL, TRACKED_SYMBOLS)
    conn.commit()
    log("COMMIT symbols: BTCUSDT and ETHUSDT dimension rows are stored.")


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    )
    return c.fetchone() is not None


@dataclass(frozen=True)
class InitState:
    initialized: bool
    btc_count: int = 0
    last_open_ms: int | None = None


def read_init_state() -> InitState:
    """Return whether BTCUSDT hourly history is already stored.

    Does not create tables and does not create bitvault.db when the file is absent.
    """
    if not os.path.exists(DB_FILE):
        return InitState(False, 0, None)
    conn = connect()
    try:
        if not table_exists(conn, "hourly_klines"):
            return InitState(False, 0, None)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*), MAX(open_time) FROM hourly_klines WHERE symbol = ?",
            (PRIMARY_SYMBOL,),
        )
        count, last_open = c.fetchone()
        count = int(count or 0)
        if count <= 0 or last_open is None:
            return InitState(False, 0, None)
        return InitState(True, count, int(last_open))
    except sqlite3.Error:
        return InitState(False, 0, None)
    finally:
        conn.close()


@dataclass
class SyncCounts:
    api_rows: int = 0
    inserted: int = 0
    updated: int = 0


def upsert_klines(conn: sqlite3.Connection, records: list[KlineRecord], log: LogFn) -> SyncCounts:
    if not records:
        return SyncCounts()
    symbols = {record.symbol for record in records}
    if len(symbols) != 1:
        raise ValueError("hourly kline upsert expects one symbol per batch")
    symbol = records[0].symbol
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM hourly_klines WHERE symbol = ?", (symbol,))
    before = int(c.fetchone()[0])
    rows = [record.as_tuple() for record in records]
    log(
        "SQL: executemany INSERT INTO hourly_klines (...) "
        "ON CONFLICT(symbol, open_time) DO UPDATE SET ... "
        f"| symbol={symbol} rows={len(rows)}"
    )
    c.executemany(SQL_UPSERT_KLINE, rows)
    conn.commit()
    c.execute("SELECT COUNT(*) FROM hourly_klines WHERE symbol = ?", (symbol,))
    after = int(c.fetchone()[0])
    inserted = max(0, after - before)
    updated = max(0, len(rows) - inserted)
    log(f"COMMIT hourly_klines symbol={symbol} inserted={inserted} updated={updated}")
    return SyncCounts(api_rows=len(rows), inserted=inserted, updated=updated)


def upsert_fear_greed(
    conn: sqlite3.Connection,
    records: list[FearGreedRecord],
    log: LogFn,
) -> SyncCounts:
    if not records:
        log("SQL: no daily_fear_greed rows to write.")
        return SyncCounts()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM daily_fear_greed")
    before = int(c.fetchone()[0])
    rows = [record.as_tuple() for record in records]
    log(
        "SQL: executemany INSERT INTO daily_fear_greed "
        "(timestamp, date_str, value, value_classification) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(date_str) DO UPDATE SET ... "
        f"| rows={len(rows)}"
    )
    c.executemany(SQL_UPSERT_FEAR_GREED, rows)
    conn.commit()
    c.execute("SELECT COUNT(*) FROM daily_fear_greed")
    after = int(c.fetchone()[0])
    inserted = max(0, after - before)
    updated = max(0, len(rows) - inserted)
    log(f"COMMIT daily_fear_greed inserted={inserted} updated={updated}")
    return SyncCounts(api_rows=len(rows), inserted=inserted, updated=updated)


@dataclass
class DashboardMetrics:
    btc_count: int = 0
    btc_first: int | None = None
    btc_last: int | None = None
    eth_count: int = 0
    fear_greed_count: int = 0

    @property
    def all_tables(self) -> int:
        return self.btc_count + self.eth_count + self.fear_greed_count


def load_metrics(conn: sqlite3.Connection, log: LogFn | None = None) -> DashboardMetrics:
    c = conn.cursor()
    if log:
        log(f"SQL: {SQL_BTC_METRICS} | params=('{PRIMARY_SYMBOL}',)")
    c.execute(SQL_BTC_METRICS, (PRIMARY_SYMBOL,))
    btc_count, btc_first, btc_last = c.fetchone()
    c.execute("SELECT COUNT(*) FROM hourly_klines WHERE symbol = ?", (BENCHMARK_SYMBOL,))
    eth_count = int(c.fetchone()[0])
    c.execute("SELECT COUNT(*) FROM daily_fear_greed")
    fear_greed_count = int(c.fetchone()[0])
    return DashboardMetrics(
        btc_count=int(btc_count or 0),
        btc_first=btc_first,
        btc_last=btc_last,
        eth_count=eth_count,
        fear_greed_count=fear_greed_count,
    )


def load_market_rows(conn: sqlite3.Connection, log: LogFn | None = None) -> list[tuple]:
    c = conn.cursor()
    if log:
        log(
            "SQL: SELECT latest 15 BTCUSDT hourly_klines "
            "LEFT JOIN ETHUSDT close, quote volume, taker buy base | LIMIT 15"
        )
    c.execute(SQL_MARKET, (BENCHMARK_SYMBOL, PRIMARY_SYMBOL))
    return list(c.fetchall())


def load_sentiment_rows(conn: sqlite3.Connection) -> list[tuple]:
    c = conn.cursor()
    c.execute(SQL_SENTIMENT)
    return list(c.fetchall())


def load_symbol_rows(conn: sqlite3.Connection) -> list[tuple]:
    c = conn.cursor()
    c.execute(SQL_SYMBOLS)
    return list(c.fetchall())


def load_index_names(conn: sqlite3.Connection) -> list[str]:
    c = conn.cursor()
    c.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    )
    return [str(row[0]) for row in c.fetchall()]


@dataclass
class Enrichment:
    fear_value: int | None = None
    fear_class: str | None = None
    btc_eth_ratio: float | None = None
    missing_hours: int | None = None


def load_enrichment(conn: sqlite3.Connection) -> Enrichment:
    c = conn.cursor()
    c.execute(SQL_LATEST_FEAR)
    fear = c.fetchone()
    c.execute(SQL_LATEST_RATIO, (BENCHMARK_SYMBOL, PRIMARY_SYMBOL))
    ratio_row = c.fetchone()
    ratio = None
    if ratio_row and ratio_row[0] is not None and ratio_row[1]:
        ratio = float(ratio_row[0]) / float(ratio_row[1])
    missing = 0
    have_klines = False
    for symbol in (PRIMARY_SYMBOL, BENCHMARK_SYMBOL):
        c.execute(
            "SELECT MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ?",
            (symbol,),
        )
        first, last = c.fetchone()
        if first is None or last is None:
            continue
        have_klines = True
        horizon = floor_hour(LAST_SERVER_TIME_MS) if LAST_SERVER_TIME_MS else floor_hour(utc_now_ms())
        end_ms = max(int(last), horizon)
        missing += len(missing_open_times(conn, symbol, int(first), end_ms))
    return Enrichment(
        fear_value=None if fear is None else int(fear[0]),
        fear_class=None if fear is None else str(fear[1]),
        btc_eth_ratio=ratio,
        missing_hours=missing if have_klines else None,
    )


def max_open_time(conn: sqlite3.Connection, symbol: str, log: LogFn | None = None) -> int | None:
    sql = "SELECT MAX(open_time) FROM hourly_klines WHERE symbol = ?"
    if log:
        log(f"SQL: SELECT MAX(open_time) FROM hourly_klines WHERE symbol = '{symbol}'")
    c = conn.cursor()
    c.execute(sql, (symbol,))
    row = c.fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def missing_open_times(
    conn: sqlite3.Connection,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> list[int]:
    start_ms = floor_hour(start_ms)
    end_ms = floor_hour(end_ms)
    if end_ms < start_ms:
        return []
    c = conn.cursor()
    c.execute(
        """
        SELECT open_time
        FROM hourly_klines
        WHERE symbol = ? AND open_time BETWEEN ? AND ?
        ORDER BY open_time
        """,
        (symbol, start_ms, end_ms),
    )
    present = {int(row[0]) for row in c.fetchall()}
    missing: list[int] = []
    cursor = start_ms
    while cursor <= end_ms:
        if cursor not in present:
            missing.append(cursor)
        cursor += HOUR_MS
    return missing


def group_contiguous(open_times: list[int]) -> list[tuple[int, int]]:
    if not open_times:
        return []
    ranges: list[tuple[int, int]] = []
    start = previous = open_times[0]
    for open_time in open_times[1:]:
        if open_time == previous + HOUR_MS:
            previous = open_time
            continue
        ranges.append((start, previous))
        start = previous = open_time
    ranges.append((start, previous))
    return ranges


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_and_store_klines(
    conn: sqlite3.Connection,
    symbol: str,
    start_ms: int,
    horizon_ms: int,
    log: LogFn,
    progress: ProgressFn,
    progress_from: float,
    progress_to: float,
    end_ms: int | None = None,
) -> SyncCounts:
    """Page through `/api/v3/klines` until every hour in the window is stored.

    Each call returns at most 1000 candles. The next request starts one hour
    after the last open time, so hours are neither skipped nor repeated.
    """
    total = SyncCounts()
    cursor = start_ms
    page = 1
    span = max(horizon_ms - start_ms, 1)
    while True:
        if page > 500:
            raise RuntimeError(f"{symbol} pagination exceeded 500 pages at startTime={cursor}.")
        params: dict = {
            "symbol": symbol,
            "interval": "1h",
            "startTime": cursor,
            "limit": KLINE_LIMIT,
        }
        if end_ms is not None:
            params["endTime"] = end_ms + 3600_000 - 1
        payload = request_json(BINANCE_KLINES_URL, params, log)
        if not isinstance(payload, list):
            raise ValueError(f"Unexpected kline payload for {symbol}: {payload!r}"[:400])
        if not payload:
            break

        last_open = _as_int(payload[-1][0])
        valid: list[KlineRecord] = []
        for row in payload:
            if not isinstance(row, list) or not row:
                log(f"WARNING: skipped malformed {symbol} kline row.")
                continue
            open_time = _as_int(row[0])
            if open_time < start_ms or (end_ms is not None and open_time > end_ms):
                continue
            try:
                valid.append(KlineRecord.from_binance(symbol, row))
            except (ValidationError, ValueError, TypeError) as exc:
                if isinstance(exc, ValidationError) and exc.errors():
                    detail = exc.errors()[0].get("msg", "validation failed")
                else:
                    detail = str(exc)
                log(f"WARNING: skipped {symbol} candle {open_time}: {detail}")

        stored = upsert_klines(conn, valid, log)
        total.api_rows += len(payload)
        total.inserted += stored.inserted
        total.updated += stored.updated

        reached_end = len(payload) < KLINE_LIMIT or (end_ms is not None and last_open >= end_ms)
        fraction = 1.0 if reached_end else min(1.0, max(0.0, (last_open - start_ms) / span))
        progress(
            progress_from + (progress_to - progress_from) * fraction,
            f"{symbol}: fetched {total.api_rows} hourly rows",
        )
        if reached_end:
            break
        next_open = last_open + 3600_000
        if next_open <= cursor:
            log(f"WARNING: {symbol} pagination cursor did not advance past {cursor}. Stopping.")
            break
        cursor = next_open
        page += 1
    return total


def _require_stored_klines(conn: sqlite3.Connection, log: LogFn) -> None:
    """Fail the job when a tracked symbol stored nothing."""
    c = conn.cursor()
    empty: list[str] = []
    for symbol in (PRIMARY_SYMBOL, BENCHMARK_SYMBOL):
        c.execute("SELECT COUNT(*) FROM hourly_klines WHERE symbol = ?", (symbol,))
        if int(c.fetchone()[0] or 0) == 0:
            empty.append(symbol)
            log(f"ERROR: {symbol} ended with 0 hourly rows stored.")
    if empty:
        joined = ", ".join(empty)
        raise RuntimeError(f"{joined} ended with 0 hourly rows stored.")


def _absorb(total: SyncCounts, extra: SyncCounts) -> None:
    total.api_rows += extra.api_rows
    total.inserted += extra.inserted
    total.updated += extra.updated


def ensure_continuous(
    conn: sqlite3.Connection,
    symbol: str,
    expected_start: int,
    server_time_ms: int,
    log: LogFn,
) -> SyncCounts:
    """Backfill any missing hour inside the stored window. No full re-download."""
    repaired = SyncCounts()
    c = conn.cursor()
    c.execute(
        "SELECT MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ?",
        (symbol,),
    )
    first, last = c.fetchone()
    if first is None or last is None:
        log(f"WARNING: {symbol} has no hourly candles to audit.")
        return repaired
    first = int(first)
    last = int(last)
    latest_hour = floor_hour(server_time_ms)
    if last < latest_hour:
        log(
            f"WARNING: {symbol} tail stops at {format_utc_label(last)} while the "
            f"Binance hour is {format_utc_label(latest_hour)}. Fetching only that tail."
        )
        _absorb(
            repaired,
            fetch_and_store_klines(
                conn,
                symbol,
                last,
                server_time_ms,
                log,
                noop_progress,
                0,
                0,
            ),
        )
        c.execute("SELECT MAX(open_time) FROM hourly_klines WHERE symbol = ?", (symbol,))
        refreshed = c.fetchone()[0]
        if refreshed is not None:
            last = int(refreshed)

    audit_from = expected_start if first > expected_start else first
    # Audit through the exchange hour, not only the last stored candle. A tail
    # the API did not return must stay missing and must not log Continuity OK.
    audit_end = max(last, latest_hour)
    missing = missing_open_times(conn, symbol, audit_from, audit_end)
    if not missing:
        log(
            f"Continuity OK {symbol}: no missing hours from "
            f"{format_utc_label(audit_from)} to {format_utc_label(audit_end)}."
        )
        return repaired

    candle_word = "candle" if len(missing) == 1 else "candles"
    if missing[0] == missing[-1]:
        span = f"at {format_utc_label(missing[0])}"
    else:
        span = f"between {format_utc_label(missing[0])} and {format_utc_label(missing[-1])}"
    log(
        f"WARNING: {symbol} is missing {len(missing)} hourly {candle_word} {span}. "
        "Backfilling only those hours."
    )
    ranges = group_contiguous(missing)
    if len(ranges) > 20:
        ranges = [(missing[0], missing[-1])]
    for range_start, range_end in ranges:
        _absorb(
            repaired,
            fetch_and_store_klines(
                conn,
                symbol,
                range_start,
                range_end,
                log,
                noop_progress,
                0,
                0,
                end_ms=range_end,
            ),
        )
    remaining = missing_open_times(conn, symbol, audit_from, audit_end)
    if remaining:
        log(
            f"WARNING: {symbol} still missing {len(remaining)} hours after backfill. "
            "The exchange returned no candle for those hours."
        )
    else:
        log(f"Continuity restored for {symbol}.")
    return repaired


def fetch_fear_greed(earliest_ms: int, log: LogFn, limit: int) -> list[FearGreedRecord]:
    params = {"limit": limit}
    payload = request_json(FEAR_GREED_URL, params, log)
    if not isinstance(payload, dict):
        raise ValueError("Fear & Greed response was not a JSON object.")
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("error"):
        raise ValueError(str(metadata["error"]))
    items = payload.get("data")
    if not isinstance(items, list):
        raise ValueError("Fear & Greed response did not contain a data list.")
    if not items and limit == 0:
        log("WARNING: Fear & Greed limit=0 returned no rows. Retrying with limit=5000.")
        return fetch_fear_greed(earliest_ms, log, 5000)

    records: list[FearGreedRecord] = []
    for item in items:
        try:
            record = FearGreedRecord.model_validate(item)
        except ValidationError as exc:
            detail = exc.errors()[0].get("msg", "validation failed") if exc.errors() else "validation failed"
            log(f"WARNING: skipped Fear & Greed row: {detail}")
            continue
        if record.timestamp >= earliest_ms:
            records.append(record)
    records.sort(key=lambda record: record.timestamp)
    return records


def fetch_funding_as_sentiment(earliest_ms: int, log: LogFn) -> list[FearGreedRecord]:
    cursor = earliest_ms
    funding: list[FundingRateRecord] = []
    page = 1
    while True:
        if page > 500:
            raise RuntimeError("Funding-rate pagination exceeded 500 pages.")
        params = {"symbol": PRIMARY_SYMBOL, "startTime": cursor, "limit": KLINE_LIMIT}
        payload = request_json(BINANCE_FUNDING_URL, params, log)
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            try:
                record = FundingRateRecord.model_validate(item)
            except ValidationError as exc:
                detail = exc.errors()[0].get("msg", "validation failed") if exc.errors() else "validation failed"
                log(f"WARNING: skipped funding row: {detail}")
                continue
            if record.funding_time >= earliest_ms:
                funding.append(record)
        last_time = _as_int(payload[-1]["fundingTime"])
        if len(payload) < KLINE_LIMIT:
            break
        next_time = last_time + 1
        if next_time <= cursor:
            break
        cursor = next_time
        page += 1
    daily = funding_records_to_fear_greed(funding)
    log(f"Funding fallback produced {len(daily)} daily rows from {len(funding)} prints.")
    return daily


def fetch_ticker_as_sentiment(log: LogFn) -> list[FearGreedRecord]:
    params = {"symbol": PRIMARY_SYMBOL}
    payload = request_json(BINANCE_TICKER_URL, params, log)
    if not isinstance(payload, dict):
        raise ValueError("24hr ticker response was not a JSON object.")
    change = float(payload["priceChangePercent"])
    close_time = _as_int(payload.get("closeTime") or int(datetime.now(timezone.utc).timestamp() * 1000))
    if change > 0:
        mood = "Greed"
    elif change < 0:
        mood = "Fear"
    else:
        mood = "Neutral"
    record = FearGreedRecord(
        timestamp=floor_day(close_time),
        date_str=format_utc(close_time)[:10],
        value=int(round(change)),
        value_classification=f"Ticker 24h fallback ({PRIMARY_SYMBOL}): {mood}",
    )
    log(f"24hr ticker fallback stored one daily row for {record.date_str} (change {change}%).")
    return [record]


def load_sentiment(
    earliest_ms: int,
    log: LogFn,
    limit: int,
) -> tuple[list[FearGreedRecord], str]:
    try:
        records = fetch_fear_greed(earliest_ms, log, limit)
        if records:
            log(
                f"Fear & Greed source=alternative.me days={len(records)} "
                f"from {records[0].date_str} to {records[-1].date_str}."
            )
            return records, "alternative.me"
        log("WARNING: Fear & Greed returned no rows inside the history window.")
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        log(f"WARNING: Fear & Greed API is unreachable ({exc}).")

    log("Falling back to Binance USD-M funding rate history.")
    try:
        records = fetch_funding_as_sentiment(earliest_ms, log)
        if records:
            return records, "binance-funding-rate"
        log("WARNING: funding-rate history returned no rows inside the window.")
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        log(f"WARNING: funding-rate fallback failed ({exc}).")

    log("Falling back to the Binance 24hr ticker.")
    try:
        return fetch_ticker_as_sentiment(log), "binance-24hr-ticker"
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        log(f"ERROR: every sentiment source failed ({exc}). Hourly candles are unaffected.")
        return [], "none"


# ---------------------------------------------------------------------------
# Initialize (full history) and Sync (delta only)
# ---------------------------------------------------------------------------

def initialize_database(
    conn: sqlite3.Connection,
    log: LogFn,
    progress: ProgressFn = noop_progress,
) -> None:
    """Create the schema, then page through the full hourly history."""
    progress(4, "Creating tables and indexes...")
    create_schema(conn, log)
    progress(8, "Reading Binance server time...")
    server_time_ms = fetch_server_time_ms(log)
    start_ms, reason = resolve_effective_start(server_time_ms)
    log(f"[INITIALIZE] {reason}")
    log(
        "[INITIALIZE] Full historical pull from "
        f"{format_utc_label(start_ms)} through Binance server time "
        f"{format_utc_label(server_time_ms)}. This is the initial load, not an incremental sync."
    )

    progress(12, f"Fetching {PRIMARY_SYMBOL} history...")
    btc = fetch_and_store_klines(
        conn, PRIMARY_SYMBOL, start_ms, server_time_ms, log, progress, 12, 46
    )
    _absorb(btc, ensure_continuous(conn, PRIMARY_SYMBOL, start_ms, server_time_ms, log))

    progress(50, f"Fetching {BENCHMARK_SYMBOL} history...")
    eth = fetch_and_store_klines(
        conn, BENCHMARK_SYMBOL, start_ms, server_time_ms, log, progress, 50, 84
    )
    _absorb(eth, ensure_continuous(conn, BENCHMARK_SYMBOL, start_ms, server_time_ms, log))

    progress(88, "Fetching the Crypto Fear & Greed index...")
    sentiment, source = load_sentiment(start_ms, log, limit=0)
    fear = upsert_fear_greed(conn, sentiment, log)
    _require_stored_klines(conn, log)
    progress(100, "Initialize complete.")
    log(
        "[INITIALIZE] Complete. "
        f"BTCUSDT API rows={btc.api_rows} new={btc.inserted} updated={btc.updated}. "
        f"ETHUSDT API rows={eth.api_rows} new={eth.inserted} updated={eth.updated}. "
        f"Fear & Greed source={source} new={fear.inserted} updated={fear.updated}."
    )


def incremental_sync(
    conn: sqlite3.Connection,
    log: LogFn,
    progress: ProgressFn = noop_progress,
) -> None:
    """Fetch only the candles from MAX(open_time) through the current hour.

    The last stored hour is requested again so the still-open candle is updated.
    Older hours are not downloaded again. An empty warehouse is not initialized
    from here: that full download belongs only to Initialize Database.
    """
    progress(4, "Checking whether the database has been initialized...")
    if not table_exists(conn, "hourly_klines"):
        log("[SYNC] Skipped: database not initialized. Click Initialize Database first.")
        return

    create_schema(conn, log)
    last_open = max_open_time(conn, PRIMARY_SYMBOL, log)
    if last_open is None:
        log("[SYNC] Skipped: database not initialized. Click Initialize Database first.")
        return

    progress(10, "Reading Binance server time...")
    server_time_ms = fetch_server_time_ms(log)
    start_ms, reason = resolve_effective_start(server_time_ms)
    last_text = format_utc_label(last_open)
    log(
        "[INCREMENTAL SYNC] Last DB Timestamp: "
        f"{last_text} -> Fetching ONLY delta records from {last_text} to now..."
    )
    log(
        f"[INCREMENTAL SYNC] BTCUSDT startTime={last_open}. "
        "The request begins at the last stored hour, so only that candle and "
        "any newly elapsed hours are returned."
    )

    progress(18, f"Syncing {PRIMARY_SYMBOL} delta...")
    btc = fetch_and_store_klines(
        conn, PRIMARY_SYMBOL, last_open, server_time_ms, log, progress, 18, 48
    )
    log(
        "[INCREMENTAL SYNC] BTCUSDT delta complete: "
        f"API rows={btc.api_rows}, new={btc.inserted}, updated={btc.updated}."
    )

    eth_last = max_open_time(conn, BENCHMARK_SYMBOL, log)
    if eth_last is None:
        log(
            f"[INCREMENTAL SYNC] {BENCHMARK_SYMBOL} has no rows. "
            "Loading that symbol from the history start. BTCUSDT stays incremental."
        )
        eth_start = start_ms
        log(reason)
    else:
        eth_text = format_utc_label(eth_last)
        eth_start = eth_last
        log(
            "[INCREMENTAL SYNC] ETHUSDT last DB timestamp: "
            f"{eth_text} -> Fetching ONLY delta records from {eth_text} to now..."
        )
    progress(52, f"Syncing {BENCHMARK_SYMBOL} delta...")
    eth = fetch_and_store_klines(
        conn, BENCHMARK_SYMBOL, eth_start, server_time_ms, log, progress, 52, 78
    )
    log(
        "[INCREMENTAL SYNC] ETHUSDT delta complete: "
        f"API rows={eth.api_rows}, new={eth.inserted}, updated={eth.updated}."
    )

    progress(82, "Syncing Fear & Greed...")
    fear_floor = start_ms
    c = conn.cursor()
    c.execute("SELECT MAX(timestamp) FROM daily_fear_greed")
    fear_last = c.fetchone()[0]
    if fear_last is None:
        fear_limit = 0
        log("[INCREMENTAL SYNC] daily_fear_greed is empty. Loading the daily history once.")
    else:
        fear_floor = int(fear_last)
        elapsed_days = int((server_time_ms - fear_floor) / DAY_MS) + 2
        fear_limit = max(2, elapsed_days)
        log(
            "[INCREMENTAL SYNC] Fear & Greed last date "
            f"{format_utc(fear_floor)[:10]} -> fetching only that day and newer "
            f"(limit={fear_limit})."
        )
    sentiment, source = load_sentiment(fear_floor, log, fear_limit)
    fear = upsert_fear_greed(conn, sentiment, log)

    progress(92, "Checking for missing hours...")
    _absorb(btc, ensure_continuous(conn, PRIMARY_SYMBOL, start_ms, server_time_ms, log))
    _absorb(eth, ensure_continuous(conn, BENCHMARK_SYMBOL, start_ms, server_time_ms, log))

    _require_stored_klines(conn, log)
    progress(100, "Incremental sync complete.")
    log(
        "[INCREMENTAL SYNC] Synced "
        f"BTCUSDT new={btc.inserted} updated={btc.updated} (API rows={btc.api_rows}); "
        f"ETHUSDT new={eth.inserted} updated={eth.updated} (API rows={eth.api_rows}); "
        f"Fear & Greed source={source} new={fear.inserted} updated={fear.updated}."
    )


# ---------------------------------------------------------------------------
# Integrity checks and CSV export (read-only; no schema changes)
# ---------------------------------------------------------------------------

SQL_DUP_KLINES = """
SELECT symbol, open_time, COUNT(*)
FROM hourly_klines
GROUP BY symbol, open_time
HAVING COUNT(*) > 1
"""

SQL_GAP_KLINES = """
SELECT symbol, open_time, next_open
FROM (
    SELECT
        symbol,
        open_time,
        LEAD(open_time) OVER (PARTITION BY symbol ORDER BY open_time) AS next_open
    FROM hourly_klines
)
WHERE next_open IS NOT NULL
  AND next_open - open_time != 3600000
"""

SQL_HOURLY_SPAN = """
SELECT symbol, MIN(open_time), MAX(open_time), COUNT(*)
FROM hourly_klines
GROUP BY symbol
ORDER BY symbol
"""

SQL_DUP_FEAR_DATES = """
SELECT date_str, COUNT(*)
FROM daily_fear_greed
GROUP BY date_str
HAVING COUNT(*) > 1
"""

SQL_EXPORT_HOURLY = """
SELECT
    b.open_time,
    b.open_price,
    b.high_price,
    b.low_price,
    b.close_price,
    b.volume,
    b.quote_asset_volume,
    b.number_of_trades,
    b.taker_buy_base_volume,
    b.close_time,
    e.close_price,
    g.value,
    g.value_classification
FROM hourly_klines AS b
LEFT JOIN hourly_klines AS e
    ON e.symbol = ? AND e.open_time = b.open_time
LEFT JOIN (
    SELECT date_str, value, value_classification
    FROM daily_fear_greed AS picked
    WHERE timestamp = (
        SELECT MAX(latest.timestamp)
        FROM daily_fear_greed AS latest
        WHERE latest.date_str = picked.date_str
    )
) AS g
    ON g.date_str = substr(b.open_datetime, 1, 10)
WHERE b.symbol = ?
ORDER BY b.open_time
"""

EXPORT_CSV_COLUMNS = (
    "open_time_utc",
    "btc_open",
    "btc_high",
    "btc_low",
    "btc_close",
    "btc_volume",
    "btc_quote_volume",
    "btc_trades",
    "btc_taker_buy_pct",
    "eth_close",
    "btc_eth_ratio",
    "fear_greed_value",
    "fear_greed_class",
    "candle_status",
)


def _sql_one_line(statement: str) -> str:
    return " ".join(statement.split())


def _csv_number(value: object) -> str:
    if value is None:
        return ""
    text = f"{float(value):.8f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-"} else "0"


def verify_integrity(conn: sqlite3.Connection, log: LogFn) -> str:
    """Run the read-only warehouse checks and return the messagebox text.

    Every statement is logged exactly as it is executed.
    """
    c = conn.cursor()
    lines: list[str] = []
    ok = True

    dup_sql = _sql_one_line(SQL_DUP_KLINES)
    log(f"SQL: {dup_sql}")
    c.execute(dup_sql)
    duplicates = c.fetchall()
    lines.append(f"Duplicate hourly keys: {len(duplicates)} (expect 0)")
    if duplicates:
        ok = False
        for symbol, open_time, count in duplicates[:10]:
            log(f"[VERIFY] duplicate symbol={symbol} open_time={open_time} count={count}")

    gap_sql = _sql_one_line(SQL_GAP_KLINES)
    log(f"SQL: {gap_sql}")
    c.execute(gap_sql)
    gaps = c.fetchall()
    gap_counts = {PRIMARY_SYMBOL: 0, BENCHMARK_SYMBOL: 0}
    for symbol, open_time, next_open in gaps:
        gap_counts[str(symbol)] = gap_counts.get(str(symbol), 0) + 1
        log(
            f"[VERIFY] gap symbol={symbol} open_time={open_time} "
            f"next_open={next_open} delta={int(next_open) - int(open_time)}"
        )
    horizon = floor_hour(fetch_server_time_ms(log))
    for symbol in (PRIMARY_SYMBOL, BENCHMARK_SYMBOL):
        c.execute(
            "SELECT MIN(open_time), MAX(open_time) FROM hourly_klines WHERE symbol = ?",
            (symbol,),
        )
        first_open, last_open = c.fetchone()
        if first_open is None or last_open is None:
            continue
        tail = [
            open_time
            for open_time in missing_open_times(conn, symbol, int(first_open), horizon)
            if open_time > int(last_open)
        ]
        if tail:
            gap_counts[symbol] = gap_counts.get(symbol, 0) + len(tail)
            log(
                f"[VERIFY] tail symbol={symbol} missing {len(tail)} hours "
                f"after {format_utc_label(int(last_open))} through {format_utc_label(horizon)}."
            )
    if any(gap_counts.values()):
        ok = False
    for symbol in (PRIMARY_SYMBOL, BENCHMARK_SYMBOL):
        lines.append(
            f"{symbol} gaps (next open_time - open_time != 3600000): "
            f"{gap_counts.get(symbol, 0)} (expect 0)"
        )

    span_sql = _sql_one_line(SQL_HOURLY_SPAN)
    log(f"SQL: {span_sql}")
    c.execute(span_sql)
    spans = c.fetchall()
    seen_symbols: set[str] = set()
    if not spans:
        ok = False
        lines.append("Expected vs actual hourly rows: hourly_klines is empty")
    for symbol, first, last, actual in spans:
        seen_symbols.add(str(symbol))
        actual_n = int(actual or 0)
        if first is None or last is None or actual_n == 0:
            ok = False
            lines.append(f"{symbol}: actual 0, expected 0")
            continue
        end_ms = max(int(last), horizon)
        expected = (end_ms - int(first)) // HOUR_MS + 1
        if expected != actual_n:
            ok = False
        lines.append(
            f"{symbol}: actual {actual_n:,}, expected {expected:,} "
            f"({format_utc(int(first))} -> {format_utc(end_ms)} UTC)"
        )
    for symbol in (PRIMARY_SYMBOL, BENCHMARK_SYMBOL):
        if symbol not in seen_symbols:
            ok = False
            lines.append(f"{symbol}: actual 0, expected 0 (no rows)")

    fear_sql = _sql_one_line(SQL_DUP_FEAR_DATES)
    log(f"SQL: {fear_sql}")
    c.execute(fear_sql)
    fear_dups = c.fetchall()
    lines.append(f"Fear & Greed duplicate dates: {len(fear_dups)} (expect 0)")
    if fear_dups:
        ok = False
        for date_str, count in fear_dups[:10]:
            log(f"[VERIFY] duplicate fear date={date_str} count={count}")

    verdict = "PASS" if ok else "FAIL"
    lines.insert(0, f"Integrity: {verdict}")
    report = "\n".join(lines)
    log("[VERIFY] " + report.replace("\n", " | "))
    return report


def export_hourly_csv(path: str, log: LogFn, now_ms: int | None = None) -> int:
    """Write the joined BTC/ETH/Fear & Greed analysis table. Returns the data-row count."""
    if now_ms is None:
        now_ms = utc_now_ms()
    statement = _sql_one_line(SQL_EXPORT_HOURLY)
    log(f"SQL: {statement} | params=('{BENCHMARK_SYMBOL}', '{PRIMARY_SYMBOL}')")
    conn = connect()
    try:
        c = conn.cursor()
        c.execute(statement, (BENCHMARK_SYMBOL, PRIMARY_SYMBOL))
        rows = c.fetchall()
    finally:
        conn.close()
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(EXPORT_CSV_COLUMNS)
        for row in rows:
            (
                open_time,
                btc_open,
                btc_high,
                btc_low,
                btc_close,
                btc_volume,
                btc_quote,
                btc_trades,
                taker_base,
                close_time,
                eth_close,
                fear_value,
                fear_class,
            ) = row
            taker_pct = ""
            if btc_volume not in (None, 0) and taker_base is not None:
                taker_pct = _csv_number(float(taker_base) / float(btc_volume) * 100)
            ratio = ""
            if eth_close not in (None, 0) and btc_close is not None:
                ratio = _csv_number(float(btc_close) / float(eth_close))
            writer.writerow(
                [
                    format_utc(int(open_time)),
                    _csv_number(btc_open),
                    _csv_number(btc_high),
                    _csv_number(btc_low),
                    _csv_number(btc_close),
                    _csv_number(btc_volume),
                    _csv_number(btc_quote),
                    "" if btc_trades is None else str(int(btc_trades)),
                    taker_pct,
                    _csv_number(eth_close),
                    ratio,
                    "" if fear_value is None else str(int(fear_value)),
                    "" if fear_class is None else str(fear_class),
                    candle_status(int(close_time), now_ms),
                ]
            )
    log(f"[EXPORT] Wrote {len(rows):,} rows to {path}")
    return len(rows)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

BG = "#0d1117"
CARD = "#161b22"
CARD_EDGE = "#30363d"
FG = "#e6edf3"
MUTED = "#8b949e"
GOLD = "#f0b90b"
TEAL = "#2dd4bf"
BLUE = "#79c0ff"
RED = "#ff7b72"
AMBER = "#e3b341"
GREEN = "#7ee787"
LOG_BG = "#090c10"


def choose_font(root: tk.Misc, options: tuple[str, ...], default: str) -> str:
    available = set(tkfont.families(root))
    for name in options:
        if name in available:
            return name
    return default


def platform_font_choices() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """UI font, then monospace font, for the current operating system."""
    if sys.platform == "darwin":
        return (
            ("Helvetica Neue", "Helvetica", "Segoe UI", "Arial"),
            ("Menlo", "Consolas", "Cascadia Mono", "Courier New"),
        )
    if sys.platform == "win32":
        return (("Segoe UI",), ("Consolas",))
    return (("DejaVu Sans",), ("DejaVu Sans Mono",))


def format_usdt(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.2f}"


def format_btc_volume(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.2f}"


def format_quote_millions(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${float(value) / 1_000_000:,.2f}M"


def format_change(open_price: float | None, close_price: float | None) -> tuple[str, str]:
    if open_price is None or close_price is None or float(open_price) == 0:
        return "—", "flat"
    percent = (float(close_price) - float(open_price)) / float(open_price) * 100
    if percent > 0:
        return f"+{percent:.2f}%", "up"
    if percent < 0:
        return f"{percent:.2f}%", "down"
    return "0.00%", "flat"


def format_taker_share(taker_base: float | None, volume: float | None) -> str:
    if taker_base is None or volume is None or float(volume) == 0:
        return "—"
    return f"{float(taker_base) / float(volume) * 100:.1f}%"


def utc_now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def candle_status(close_time_ms: int, now_ms: int | None = None) -> str:
    """LIVE while the candle's close_time is still at or after the current UTC instant."""
    if now_ms is None:
        now_ms = utc_now_ms()
    return "LIVE" if int(close_time_ms) >= int(now_ms) else "CLOSED"


def continuity_label(missing_hours: int | None) -> str:
    if missing_hours is None:
        return "—"
    if missing_hours == 0:
        return "0 Missing Hours / Verified"
    noun = "Hour" if missing_hours == 1 else "Hours"
    return f"{missing_hours:,} Missing {noun} / Gap"


MARKET_COLUMNS = (
    ("open_time", "Open Time (UTC)", 196, "w", False),
    ("open", "Open (USDT)", 108, "e", False),
    ("high", "High (USDT)", 108, "e", False),
    ("low", "Low (USDT)", 108, "e", False),
    ("close", "Close (USDT)", 108, "e", False),
    ("change", "1h Chg %", 84, "e", False),
    ("volume", "Vol (BTC)", 88, "e", False),
    ("quote_volume", "Quote Vol (USDT)", 124, "e", False),
    ("taker", "Taker Buy %", 100, "e", False),
    ("trades", "Trades", 88, "e", False),
    ("eth_close", "ETH (USDT)", 108, "e", False),
    ("status", "Status", 78, "center", False),
)

SENTIMENT_COLUMNS = (
    ("date", "Date (UTC)", 140, "w", False),
    ("timestamp", "Timestamp", 190, "e", False),
    ("value", "F&G Index (0-100)", 160, "e", False),
    ("regime", "Market Regime / Classification", 360, "w", True),
)

SCHEMA_COLUMNS = (
    ("object", "Object", 240, "w", True),
    ("kind", "Kind", 150, "w", False),
    ("detail", "Detail", 460, "w", True),
    ("rows", "Rows", 110, "e", False),
)

VIEW_LABELS = (
    ("market", "Market Microstructure (BTC & ETH Joined)"),
    ("sentiment", "Macro Sentiment (daily_fear_greed table)"),
    ("schema", "Warehouse Schema & Assets (symbols table + DB stats)"),
)


def action_clock() -> str:
    """Local time with its timezone label, then the same instant in UTC."""
    local = datetime.now().astimezone()
    utc = datetime.now(timezone.utc)
    zone = local.tzname() or "local"
    return f"{local.strftime('%H:%M:%S')} {zone} ({utc.strftime('%H:%M:%S')} UTC)"


def written_counts(notes: list[str]) -> tuple[int, int] | None:
    """Sum new/updated counts from the existing initialize or sync summary line."""
    line = ""
    for note in notes:
        if note.startswith("[INCREMENTAL SYNC] Synced") or note.startswith("[INITIALIZE] Complete"):
            line = note
    if not line:
        return None
    pairs = re.findall(r"new=(\d+) updated=(\d+)", line)
    if not pairs:
        return None
    new = sum(int(item[0]) for item in pairs)
    updated = sum(int(item[1]) for item in pairs)
    return new, updated


def integrity_headline(report: str) -> str:
    """PASS, or FAIL with the number of checks that were not clean."""
    if report.startswith("Integrity: PASS"):
        return "PASS"
    issues = 0
    for line in report.splitlines():
        if line.startswith("Integrity:"):
            continue
        expect = re.search(r":\s*([\d,]+)\s*\(expect 0\)", line)
        if expect:
            if int(expect.group(1).replace(",", "")) > 0:
                issues += 1
            continue
        span = re.search(r"actual\s+([\d,]+),\s+expected\s+([\d,]+)", line)
        if span:
            actual = int(span.group(1).replace(",", ""))
            expected = int(span.group(2).replace(",", ""))
            if actual != expected:
                issues += 1
            continue
        if "empty" in line or "no rows" in line:
            issues += 1
    return f"FAIL ({max(issues, 1)} issues)"


class HoverTip:
    """Small hover label. Tk has no built-in tooltip."""

    def __init__(self, widget: tk.Widget, text: str, font: tuple) -> None:
        self.widget = widget
        self.text = text
        self.font = font
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def show(self, _event: object = None) -> None:
        if self.tip is not None:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.configure(bg="#1c2430")
        tk.Label(
            tip,
            text=self.text,
            bg="#1c2430",
            fg=FG,
            font=self.font,
            padx=8,
            pady=4,
            justify="left",
        ).pack()
        tip.update_idletasks()
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip.wm_geometry(f"+{x}+{y}")
        self.tip = tip

    def hide(self, _event: object = None) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class BitVaultApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FF-BITVault-Sync — Quantitative Crypto Data Warehouse")
        self.configure(bg=BG)
        self.minsize(1280, 860)
        ui_choices, mono_choices = platform_font_choices()
        self.ui_font = choose_font(self, ui_choices, "TkDefaultFont")
        self.mono_font = choose_font(self, mono_choices, "TkFixedFont")
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._closing = False
        self._auto_after_id: str | None = None
        self._next_auto_at: datetime | None = None
        self.auto_sync_var = tk.BooleanVar(value=False)
        self._job_notes: list[str] = []
        self._job_kind = ""
        self._job_started = 0.0
        self._verify_report = ""
        self._export_path = ""
        self._dialog_open = False
        self._log_open = False
        self._apply_theme()
        self._build()
        self.after(80, self._poll_queue)
        self.refresh_dashboard()
        self._apply_ready_state(announce=True)
        self._place_window()

    def _place_window(self) -> None:
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(1480, max(1280, screen_w - 80))
        height = min(1100, max(900, screen_h - 80))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _apply_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure(
            "Terminal.TRadiobutton",
            background=BG,
            foreground=MUTED,
            font=(self.ui_font, 11, "bold"),
            indicatorcolor="#30363d",
            focuscolor=BG,
        )
        style.map(
            "Terminal.TRadiobutton",
            background=[("active", BG), ("selected", BG)],
            foreground=[("selected", GOLD), ("active", FG)],
            indicatorcolor=[("selected", GOLD)],
        )
        style.configure(
            "Primary.TButton",
            font=(self.ui_font, 12, "bold"),
            foreground="#1a1403",
            background=GOLD,
            borderwidth=0,
            padding=(18, 10),
            focuscolor=GOLD,
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#ffd45a"), ("disabled", "#3a3f46")],
            foreground=[("disabled", "#8b949e")],
        )
        style.configure(
            "Secondary.TButton",
            font=(self.ui_font, 12, "bold"),
            foreground="#04221e",
            background=TEAL,
            borderwidth=0,
            padding=(18, 10),
            focuscolor=TEAL,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#5ef0dc"), ("disabled", "#1d4f49")],
            foreground=[("disabled", "#d7fffa")],
        )
        style.configure(
            "Outline.TButton",
            font=(self.ui_font, 11, "bold"),
            foreground=FG,
            background=BG,
            bordercolor="#8b949e",
            lightcolor=BG,
            darkcolor=BG,
            borderwidth=1,
            padding=(14, 8),
            focuscolor=BG,
        )
        style.map(
            "Outline.TButton",
            background=[("active", "#21262d"), ("disabled", BG)],
            foreground=[("active", FG), ("disabled", MUTED)],
            bordercolor=[("active", FG), ("disabled", "#30363d")],
        )
        style.configure(
            "AutoOff.TButton",
            font=(self.ui_font, 11, "bold"),
            foreground=TEAL,
            background=BG,
            bordercolor=TEAL,
            lightcolor=BG,
            darkcolor=BG,
            borderwidth=1,
            padding=(14, 8),
            focuscolor=BG,
        )
        style.map(
            "AutoOff.TButton",
            background=[("active", "#102218"), ("disabled", BG)],
            foreground=[("active", TEAL), ("disabled", "#6e7681")],
            bordercolor=[("active", TEAL), ("disabled", "#3a3f46")],
        )
        style.configure(
            "AutoOn.TButton",
            font=(self.ui_font, 11, "bold"),
            foreground="#04221e",
            background=TEAL,
            bordercolor=TEAL,
            lightcolor=TEAL,
            darkcolor=TEAL,
            borderwidth=0,
            padding=(14, 8),
            focuscolor=TEAL,
        )
        style.map(
            "AutoOn.TButton",
            background=[("active", "#5ef0dc"), ("disabled", "#1d4f49")],
            foreground=[("disabled", "#d7fffa")],
        )
        style.configure(
            "Gold.Horizontal.TProgressbar",
            troughcolor="#21262d",
            background=GOLD,
            bordercolor="#21262d",
            lightcolor=GOLD,
            darkcolor=GOLD,
            thickness=4,
            borderwidth=0,
        )
        style.configure(
            "BitVault.Treeview",
            background="#12171f",
            fieldbackground="#12171f",
            foreground=FG,
            borderwidth=0,
            rowheight=28,
            font=(self.ui_font, 11),
        )
        # Clam paints headings with a light image. A wide stretched column
        # (Market Regime / Classification) shows that image as a white bar.
        # A solid cell image keeps every heading on the same dark fill.
        self._heading_fill = tk.PhotoImage(width=8, height=8)
        self._heading_fill.put("#1c2430", to=(0, 0, 8, 8))
        style.element_create(
            "BitVault.Treeheading.cell",
            "image",
            self._heading_fill,
            border=1,
            sticky="nswe",
        )
        style.layout(
            "BitVault.Treeview.Heading",
            [
                ("BitVault.Treeheading.cell", {"sticky": "nswe"}),
                (
                    "Treeheading.border",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Treeheading.padding",
                                {
                                    "sticky": "nswe",
                                    "children": [
                                        ("Treeheading.text", {"sticky": "we"}),
                                    ],
                                },
                            )
                        ],
                    },
                ),
            ],
        )
        style.configure(
            "BitVault.Treeview.Heading",
            background="#1c2430",
            foreground=GOLD,
            bordercolor="#1c2430",
            lightcolor="#1c2430",
            darkcolor="#1c2430",
            borderwidth=0,
            relief="flat",
            font=(self.ui_font, 10, "bold"),
        )
        style.map(
            "BitVault.Treeview.Heading",
            background=[("active", "#1c2430"), ("pressed", "#1c2430")],
            foreground=[("active", GOLD), ("pressed", GOLD)],
            bordercolor=[("active", "#1c2430"), ("pressed", "#1c2430")],
            lightcolor=[("active", "#1c2430"), ("pressed", "#1c2430")],
            darkcolor=[("active", "#1c2430"), ("pressed", "#1c2430")],
        )
        style.map(
            "BitVault.Treeview",
            background=[("selected", "#3a2f12")],
            foreground=[("selected", "#fff8e8")],
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#21262d",
            troughcolor=LOG_BG,
            bordercolor=LOG_BG,
            arrowcolor=MUTED,
        )

    def _build(self) -> None:
        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True, padx=20, pady=16)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(4, weight=1)

        header = tk.Frame(shell, bg=BG)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        titles = tk.Frame(header, bg=BG)
        titles.grid(row=0, column=0, sticky="ew")
        tk.Label(
            titles,
            text="FF-BITVAULT-SYNC",
            bg=BG,
            fg=GOLD,
            font=(self.ui_font, 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            titles,
            text="Automated Spot OHLCV, Order-Flow Microstructure & Macro Sentiment Ingestion Engine",
            bg=BG,
            fg=FG,
            font=(self.ui_font, 12),
        ).pack(anchor="w", pady=(2, 0))
        self.badge_var = tk.StringVar(value="● Not initialized")
        self.badge_label = tk.Label(
            header,
            textvariable=self.badge_var,
            bg="#3a1518",
            fg=RED,
            font=(self.ui_font, 11, "bold"),
            anchor="center",
            padx=12,
            pady=6,
        )
        self.badge_label.grid(row=0, column=1, sticky="ne", padx=(16, 0))
        tk.Frame(header, bg=GOLD, height=2).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0)
        )

        toolbar = tk.Frame(shell, bg=BG)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(14, 8))
        toolbar.columnconfigure(3, weight=1)
        self.btn_init = ttk.Button(
            toolbar,
            text="Initialize Database",
            style="Primary.TButton",
            command=self.on_initialize,
            cursor="hand2",
        )
        self.btn_init.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.btn_sync = ttk.Button(
            toolbar,
            text="Sync Database",
            style="Primary.TButton",
            command=self.on_sync,
            cursor="hand2",
        )
        self.btn_sync.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.btn_auto = ttk.Button(
            toolbar,
            text="Auto-Sync: OFF",
            style="AutoOff.TButton",
            command=self._on_auto_button,
            cursor="hand2",
        )
        self.btn_auto.grid(row=0, column=2, sticky="w", padx=(0, 8))
        self.btn_verify = ttk.Button(
            toolbar,
            text="Verify Integrity",
            style="Outline.TButton",
            command=self.on_verify,
            cursor="hand2",
        )
        self.btn_verify.grid(row=0, column=4, sticky="e", padx=(8, 8))
        self.btn_export = ttk.Button(
            toolbar,
            text="Export CSV",
            style="Outline.TButton",
            command=self.on_export,
            cursor="hand2",
        )
        self.btn_export.grid(row=0, column=5, sticky="e")
        tip_font = (self.ui_font, 10)
        HoverTip(
            self.btn_init,
            "One-time setup: create tables + full history since 2026-09-01 UTC",
            tip_font,
        )
        self._sync_tip = HoverTip(
            self.btn_sync,
            "Incremental: fetch only hours after the last stored record",
            tip_font,
        )
        self._auto_tip = HoverTip(
            self.btn_auto,
            "Run Sync Database every 5 minutes. A tick is skipped if a job is already running.",
            tip_font,
        )
        HoverTip(
            self.btn_verify,
            "Read-only check for duplicate keys, hourly gaps, expected row counts, and Fear & Greed dates.",
            tip_font,
        )
        HoverTip(
            self.btn_export,
            "Save the joined hourly analysis table as CSV.",
            tip_font,
        )
        self.status_var = tk.StringVar(value="No actions yet this session.")
        tk.Label(
            toolbar,
            textvariable=self.status_var,
            bg=BG,
            fg=FG,
            font=(self.ui_font, 11),
            anchor="w",
        ).grid(row=1, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_canvas = tk.Canvas(
            toolbar,
            height=4,
            bg="#21262d",
            highlightthickness=0,
            bd=0,
        )
        self.progress_canvas.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(6, 0))
        self.progress_canvas.grid_remove()

        metrics = tk.Frame(shell, bg=BG)
        metrics.grid(row=2, column=0, sticky="ew", pady=(8, 12))
        for column in range(4):
            metrics.columnconfigure(column, weight=1, uniform="metric")
        self.count_value, self.count_sub = self._metric_card(
            metrics, 0, "Total Row Count", GOLD, "0", 24
        )
        self.first_value, self.first_sub = self._metric_card(
            metrics, 1, "First Record Timestamp", TEAL, "—", 14
        )
        self.last_value, self.last_sub = self._metric_card(
            metrics, 2, "Last Record Timestamp", BLUE, "—", 14
        )
        self.health_value, self.health_sub = self._metric_card(
            metrics, 3, "Warehouse Enrichment & Health", "#c4b5fd", "—", 18
        )
        self._show_metrics(DashboardMetrics(), Enrichment())

        selector = tk.Frame(shell, bg=BG)
        selector.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.view_var = tk.StringVar(value="market")
        for column, (key, label) in enumerate(VIEW_LABELS):
            selector.columnconfigure(column, weight=1)
            ttk.Radiobutton(
                selector,
                text=label,
                value=key,
                variable=self.view_var,
                command=self._on_view_change,
                style="Terminal.TRadiobutton",
            ).grid(row=0, column=column, sticky="w", padx=(0, 12))
        self._terminal = {
            "market": [],
            "sentiment": [],
            "symbols": [],
            "indexes": [],
            "counts": {"symbols": 0, "hourly_klines": 0, "daily_fear_greed": 0},
        }

        table_wrap = tk.Frame(shell, bg=CARD, highlightthickness=1, highlightbackground=CARD_EDGE)
        table_wrap.grid(row=4, column=0, sticky="nsew")
        table_wrap.rowconfigure(1, weight=1)
        table_wrap.columnconfigure(0, weight=1)
        self.candle_note = tk.Label(
            table_wrap,
            text="LIVE = candle still forming; values update on next Sync. Use CLOSED rows for backtesting.",
            bg=CARD,
            fg=AMBER,
            font=(self.ui_font, 10),
            anchor="w",
            justify="left",
        )
        self.candle_note.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 2))
        self.tree = ttk.Treeview(
            table_wrap,
            columns=[item[0] for item in MARKET_COLUMNS],
            show="headings",
            style="BitVault.Treeview",
            height=12,
        )
        self._apply_columns(MARKET_COLUMNS)
        self.tree.tag_configure("up", background="#102218", foreground="#3dd68c")
        self.tree.tag_configure("down", background="#2a1418", foreground="#ff7b72")
        self.tree.tag_configure("flat", background="#12171f", foreground=FG)
        self.tree.tag_configure("even", background="#12171f", foreground=FG)
        self.tree.tag_configure("odd", background="#18202b", foreground=FG)
        self.tree.tag_configure("regime_greed", background="#102218", foreground="#3dd68c")
        self.tree.tag_configure("regime_fear", background="#2a1418", foreground="#ff7b72")
        self.tree.tag_configure("regime_neutral", background="#241c10", foreground=AMBER)
        self.tree.tag_configure("live", foreground=AMBER)
        table_scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=table_scroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        table_scroll.grid(row=1, column=1, sticky="ns")

        self.log_toggle = tk.Label(
            shell,
            text="▸ Activity Log",
            bg=BG,
            fg=FG,
            font=(self.ui_font, 13, "bold"),
            anchor="w",
            cursor="hand2",
        )
        self.log_toggle.bind("<Button-1>", lambda _event: self._toggle_log())
        self.log_toggle.grid(row=5, column=0, sticky="w", pady=(12, 6))

        log_wrap = tk.Frame(shell, bg=LOG_BG, highlightthickness=1, highlightbackground=CARD_EDGE)
        self.log_wrap = log_wrap
        log_wrap.grid(row=6, column=0, sticky="nsew")
        log_wrap.rowconfigure(0, weight=1)
        log_wrap.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_wrap,
            bg=LOG_BG,
            fg="#c9d1d9",
            insertbackground="#c9d1d9",
            font=(self.mono_font, 11),
            relief="flat",
            highlightthickness=0,
            padx=12,
            pady=8,
            height=6,
            wrap="word",
            state="disabled",
        )
        log_scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")
        for name, color in (
            ("plain", "#c9d1d9"),
            ("api", BLUE),
            ("sync", GOLD),
            ("ok", GREEN),
            ("warn", AMBER),
            ("error", RED),
        ):
            self.log_text.tag_configure(name, foreground=color)
        self.log_wrap.grid_remove()

        self.footer_var = tk.StringVar(value=footer_status())
        tk.Label(
            shell,
            textvariable=self.footer_var,
            bg=BG,
            fg=MUTED,
            font=(self.ui_font, 9),
            anchor="w",
        ).grid(row=7, column=0, sticky="ew", pady=(8, 0))
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _metric_card(
        self,
        parent: tk.Widget,
        column: int,
        title: str,
        accent: str,
        initial: str,
        value_size: int,
    ) -> tuple[tk.Label, tk.Label]:
        frame = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=CARD_EDGE)
        padx = (0, 8) if column < 3 else 0
        frame.grid(row=0, column=column, sticky="nsew", padx=padx)
        tk.Frame(frame, bg=accent, height=3).pack(fill="x")
        tk.Label(
            frame,
            text=title,
            bg=CARD,
            fg=MUTED,
            font=(self.ui_font, 10, "bold"),
            anchor="w",
            wraplength=300,
            justify="left",
        ).pack(fill="x", padx=14, pady=(10, 0))
        value = tk.Label(
            frame,
            text=initial,
            bg=CARD,
            fg=FG,
            font=(self.ui_font, value_size, "bold"),
            anchor="w",
            justify="left",
            wraplength=300,
        )
        value.pack(fill="x", padx=14, pady=(4, 0))
        subtitle = tk.Label(
            frame,
            text="",
            bg=CARD,
            fg=MUTED,
            font=(self.ui_font, 11),
            anchor="w",
            justify="left",
            wraplength=300,
        )
        subtitle.pack(fill="x", padx=14, pady=(2, 12))
        return value, subtitle

    def _on_close(self) -> None:
        self._closing = True
        self._cancel_auto_sync()
        self.destroy()

    def _set_job_buttons(self, enabled: bool) -> None:
        state = ["!disabled"] if enabled else ["disabled"]
        for button in (self.btn_init, self.btn_sync, self.btn_verify, self.btn_export, self.btn_auto):
            button.state(state)

    def _apply_ready_state(self, *, announce: bool = False) -> None:
        """Sync and Auto-Sync stay off until BTCUSDT hourly history exists."""
        if self._busy:
            return
        ready = read_init_state().initialized
        self.btn_init.state(["!disabled"])
        self.btn_init.configure(style="Primary.TButton")
        self.btn_verify.state(["!disabled"])
        self.btn_export.state(["!disabled"])
        if ready:
            self.btn_sync.state(["!disabled"])
            self.btn_auto.state(["!disabled"])
            self._sync_tip.text = "Incremental: fetch only hours after the last stored record"
            self._auto_tip.text = (
                "Run Sync Database every 5 minutes. A tick is skipped if a job is already running."
            )
            return
        self.btn_sync.state(["disabled"])
        self.btn_auto.state(["disabled"])
        self._sync_tip.text = "Initialize the database first"
        self._auto_tip.text = "Initialize the database first"
        if self.auto_sync_var.get():
            self.auto_sync_var.set(False)
            self._cancel_auto_sync()
            self._next_auto_at = None
            self._paint_auto_button()
            self.log(
                "[AUTO-SYNC] Turned off: database is not initialized. "
                "Click Initialize Database first."
            )
        if announce:
            self.status_var.set(
                "Start here: click Initialize Database to create tables and "
                "load history since 2026-09-01 UTC."
            )

    def _toggle_log(self) -> None:
        self._log_open = not self._log_open
        if self._log_open:
            self.log_toggle.configure(text="▾ Activity Log")
            self.log_wrap.grid()
        else:
            self.log_toggle.configure(text="▸ Activity Log")
            self.log_wrap.grid_remove()

    def _show_progress(self) -> None:
        self.progress_canvas.grid()
        self.after_idle(lambda: self._set_progress(float(self.progress_var.get())))

    def _hide_progress(self) -> None:
        self.progress_var.set(0)
        self.progress_canvas.delete("all")
        self.progress_canvas.grid_remove()

    def _set_progress(self, percent: float) -> None:
        self.progress_var.set(percent)
        canvas = self.progress_canvas
        canvas.update_idletasks()
        width = canvas.winfo_width()
        if width <= 1:
            width = max(canvas.winfo_reqwidth(), 1)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, max(0, width * (percent / 100.0)), 4, fill=GOLD, width=0)

    def _paint_auto_button(self) -> None:
        if self.auto_sync_var.get() and self._next_auto_at is not None:
            stamp = self._next_auto_at.strftime("%H:%M:%S")
            self.btn_auto.configure(
                text=f"Auto-Sync: ON · next {stamp} UTC",
                style="AutoOn.TButton",
            )
            return
        self.btn_auto.configure(text="Auto-Sync: OFF", style="AutoOff.TButton")

    def _remember_action(self, text: str) -> None:
        self.status_var.set(text)

    def on_initialize(self) -> None:
        state = read_init_state()
        if state.initialized and state.last_open_ms is not None:
            prompt = (
                f"The warehouse is already initialized ({state.btc_count:,} rows, "
                f"last record {format_utc(state.last_open_ms)} UTC). "
                "For routine updates use Sync Database, which only fetches new hours. "
                "Re-run the full historical download anyway?"
            )
            self._dialog_open = True
            try:
                confirmed = messagebox.askyesno("Initialize Database", prompt, parent=self)
            finally:
                self._dialog_open = False
            if not confirmed:
                self.log("[INITIALIZE] Skipped by user: database already initialized.")
                return
        self._start_job(self._initialize_job, "Running: Initialize Database...", "initialize")

    def _update_init_badge(self) -> None:
        state = read_init_state()
        if not state.initialized:
            self.badge_var.set("● Not initialized")
            self.badge_label.configure(fg=RED, bg="#3a1518")
            return
        self.badge_var.set(f"● Initialized · {state.btc_count:,} rows")
        self.badge_label.configure(fg=GREEN, bg="#102218")

    def on_sync(self) -> None:
        self._start_job(self._sync_job, "Running: Sync Database...", "sync")

    def on_verify(self) -> None:
        if self._busy:
            self.log("A database job is already running.")
            return
        if not os.path.exists(DB_FILE):
            messagebox.showinfo("Verify Integrity", "bitvault.db does not exist yet.", parent=self)
            return
        self._start_job(self._verify_job, "Running: Verify Integrity...", "verify")

    def on_export(self) -> None:
        if self._busy:
            self.log("A database job is already running.")
            return
        if not os.path.exists(DB_FILE):
            messagebox.showinfo("Export CSV", "bitvault.db does not exist yet.", parent=self)
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        self._dialog_open = True
        try:
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Export CSV",
                defaultextension=".csv",
                initialfile=f"ff_bitvault_hourly_{stamp}.csv",
                filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
            )
        finally:
            self._dialog_open = False
        if not path:
            return
        self._export_path = path
        self._start_job(self._export_job, "Running: Export CSV...", "export")

    def _on_auto_button(self) -> None:
        if not read_init_state().initialized:
            return
        turning_on = not self.auto_sync_var.get()
        self.auto_sync_var.set(turning_on)
        self._on_auto_sync_toggle()
        if turning_on and not self._busy and not self._dialog_open:
            self.log("[AUTO-SYNC]")
            self._start_job(self._sync_job, "Running: Sync Database...", "sync")

    def _on_auto_sync_toggle(self) -> None:
        if self.auto_sync_var.get():
            self._schedule_auto_sync()
            self.log("[AUTO-SYNC] Enabled. Incremental sync runs every 5 minutes.")
        else:
            self._cancel_auto_sync()
            self._next_auto_at = None
            self._paint_auto_button()
            self.log("[AUTO-SYNC] Disabled. Timer cancelled.")

    def _schedule_auto_sync(self) -> None:
        self._cancel_auto_sync()
        if self._closing or not self.auto_sync_var.get():
            self._next_auto_at = None
            self._paint_auto_button()
            return
        self._next_auto_at = datetime.now(timezone.utc) + timedelta(milliseconds=AUTO_SYNC_INTERVAL_MS)
        self._paint_auto_button()
        self._auto_after_id = self.after(AUTO_SYNC_INTERVAL_MS, self._auto_sync_tick)

    def _cancel_auto_sync(self) -> None:
        if self._auto_after_id is not None:
            try:
                self.after_cancel(self._auto_after_id)
            except tk.TclError:
                pass
            self._auto_after_id = None

    def _auto_sync_tick(self) -> None:
        self._auto_after_id = None
        if self._closing or not self.auto_sync_var.get():
            self._next_auto_at = None
            self._paint_auto_button()
            return
        self._schedule_auto_sync()
        if self._dialog_open:
            self.log("[AUTO-SYNC] Skipped: a dialog is open.")
            return
        if self._busy:
            self.log("[AUTO-SYNC] Skipped: a job is already running.")
            return
        if not read_init_state().initialized:
            self._apply_ready_state()
            return
        self.log("[AUTO-SYNC]")
        self._start_job(self._sync_job, "Running: Sync Database...", "sync")

    def _start_job(self, target: Callable[[], None], status: str, kind: str) -> None:
        if self._busy:
            self.log("A database job is already running.")
            return
        self._busy = True
        self._job_kind = kind
        self._job_started = time.perf_counter()
        self._job_notes = []
        self._verify_report = ""
        self.configure(cursor="watch")
        self._set_job_buttons(False)
        self._remember_action(status)
        self._show_progress()
        self._set_progress(2)
        threading.Thread(target=self._wrap_job, args=(target,), name="bitvault-sync", daemon=True).start()

    def _wrap_job(self, target: Callable[[], None]) -> None:
        error: str | None = None
        try:
            target()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                body = exc.response.text[:160].replace("\n", " ")
                error = f"{error} | body={body}"
            self.log(f"ERROR: {error}")
        self._queue.put(("done", error))

    def _initialize_job(self) -> None:
        conn = connect()
        try:
            initialize_database(conn, self.log, self.report)
        finally:
            conn.close()

    def _sync_job(self) -> None:
        conn = connect()
        try:
            incremental_sync(conn, self.log, self.report)
        finally:
            conn.close()

    def _verify_job(self) -> None:
        conn = connect()
        try:
            report = verify_integrity(conn, self.log)
        finally:
            conn.close()
        self._verify_report = report
        self._queue.put(("dialog", "Verify Integrity", report))

    def _export_job(self) -> None:
        export_hourly_csv(self._export_path, self.log)

    def log(self, message: str) -> None:
        if self._busy:
            self._job_notes.append(message)
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{stamp} UTC] {message}"
        print(line, flush=True)
        self._queue.put(("log", line))

    def report(self, percent: float, text: str) -> None:
        self._queue.put(("progress", max(0.0, min(100.0, percent)), text))

    def _poll_queue(self) -> None:
        if self._closing:
            return
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log(item[1])
                elif kind == "progress":
                    self._set_progress(item[1])
                elif kind == "dialog":
                    messagebox.showinfo(item[1], item[2], parent=self)
                elif kind == "done":
                    self._finish_job(item[1])
        except queue.Empty:
            pass
        if not self._closing and self.winfo_exists():
            self.after(80, self._poll_queue)

    def _finish_job(self, error: str | None) -> None:
        elapsed = max(0.0, time.perf_counter() - self._job_started)
        notes = list(self._job_notes)
        kind = self._job_kind
        report = self._verify_report
        self._busy = False
        self.configure(cursor="")
        self._set_job_buttons(True)
        self._hide_progress()
        self._remember_action(self._action_summary(kind, notes, report, elapsed, error))
        self._paint_auto_button()
        self.refresh_dashboard()
        self._apply_ready_state()
        self._refresh_footer()
        if error:
            if not self._log_open:
                self._toggle_log()
            self.after(0, lambda message=error: self._show_error_dialog(message))

    def _show_error_dialog(self, message: str) -> None:
        if self._closing or not self.winfo_exists():
            return
        self._dialog_open = True
        try:
            messagebox.showerror("FF-BITVault-Sync", message, parent=self)
        finally:
            self._dialog_open = False

    def _action_summary(
        self,
        kind: str,
        notes: list[str],
        report: str,
        elapsed: float,
        error: str | None,
    ) -> str:
        clock = action_clock()
        duration = f"{elapsed:.1f} s"
        if kind == "verify":
            if error:
                return f"Last Integrity Check: {clock} · Failed"
            return f"Last Integrity Check: {clock} · {integrity_headline(report)}"
        if kind == "export":
            if error or not self._export_path:
                return f"Last Export: {clock} · Failed"
            return f"Last Export: {clock} · {os.path.basename(self._export_path)}"
        if any(note.startswith("[SYNC] Skipped:") for note in notes) and not error:
            return (
                "Start here: click Initialize Database to create tables and "
                "load history since 2026-09-01 UTC."
            )
        counts = written_counts(notes)
        if kind == "initialize":
            if error or counts is None:
                return f"Last Initialize: {clock} · Failed · {duration}"
            loaded = counts[0] + counts[1]
            return f"Last Initialize: {clock} · {loaded:,} rows loaded · {duration}"
        if error or counts is None:
            return f"Last Sync: {clock} · Failed · {duration}"
        new, updated = counts
        return f"Last Sync: {clock} · +{new:,} new / {updated:,} updated · {duration}"

    def _append_log(self, line: str) -> None:
        if "ERROR" in line:
            tag = "error"
        elif "WARNING" in line:
            tag = "warn"
        elif "INCREMENTAL SYNC" in line or "INITIALIZE" in line or "AUTO-SYNC" in line or "[VERIFY]" in line:
            tag = "sync"
        elif "COMMIT" in line or "Continuity OK" in line:
            tag = "ok"
        elif "API GET" in line:
            tag = "api"
        else:
            tag = "plain"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n", tag)
        line_count = int(float(self.log_text.index("end-1c")))
        if line_count > 2000:
            self.log_text.delete("1.0", "501.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def refresh_dashboard(self) -> None:
        self._update_init_badge()
        if not os.path.exists(DB_FILE):
            self._terminal = {
                "market": [],
                "sentiment": [],
                "symbols": [],
                "indexes": [],
                "counts": {"symbols": 0, "hourly_klines": 0, "daily_fear_greed": 0},
            }
            self._show_metrics(DashboardMetrics(), Enrichment())
            self._render_active_view()
            self.log("No bitvault.db yet. Click Initialize Database to create the schema and load history.")
            return
        conn = connect()
        try:
            if not table_exists(conn, "hourly_klines"):
                self._terminal = {
                    "market": [],
                    "sentiment": [],
                    "symbols": [],
                    "indexes": [],
                    "counts": {"symbols": 0, "hourly_klines": 0, "daily_fear_greed": 0},
                }
                self._show_metrics(DashboardMetrics(), Enrichment())
                self._render_active_view()
                self.log("bitvault.db has no hourly_klines table yet. Click Initialize Database.")
                return
            metrics = load_metrics(conn, self.log)
            enrichment = load_enrichment(conn)
            market = load_market_rows(conn, self.log)
            sentiment = load_sentiment_rows(conn)
            symbols = load_symbol_rows(conn)
            self._terminal = {
                "market": market,
                "sentiment": sentiment,
                "symbols": symbols,
                "indexes": load_index_names(conn),
                "counts": {
                    "symbols": len(symbols),
                    "hourly_klines": metrics.btc_count + metrics.eth_count,
                    "daily_fear_greed": metrics.fear_greed_count,
                },
            }
        finally:
            conn.close()
        self._show_metrics(metrics, enrichment)
        self._render_active_view()

    def _show_metrics(self, metrics: DashboardMetrics, enrichment: Enrichment) -> None:
        self.count_value.configure(text=f"{metrics.btc_count:,}")
        self.count_sub.configure(
            text=(
                f"BTCUSDT klines: {metrics.btc_count:,}\n"
                f"ETHUSDT klines: {metrics.eth_count:,}\n"
                f"Fear & Greed: {metrics.fear_greed_count:,}\n"
                f"All tables: {metrics.all_tables:,}"
            )
        )
        self.first_value.configure(text=format_utc_label(metrics.btc_first))
        self.first_sub.configure(text="BTCUSDT  ·  hourly_klines.open_time")
        self.last_value.configure(text=format_utc_label(metrics.btc_last))
        self.last_sub.configure(text="BTCUSDT  ·  hourly_klines.open_time")
        if enrichment.fear_value is None:
            fear_text = "—"
        else:
            label = enrichment.fear_class or "—"
            fear_text = f"{enrichment.fear_value} ({label})"
        self.health_value.configure(text=fear_text)
        if enrichment.btc_eth_ratio is None:
            ratio_text = "—"
        else:
            ratio_text = f"{enrichment.btc_eth_ratio:,.2f}"
        self.health_sub.configure(
            text=(
                f"BTC/ETH Ratio: {ratio_text}\n"
                f"Continuity: {continuity_label(enrichment.missing_hours)}"
            )
        )

    def _on_view_change(self) -> None:
        self._render_active_view()

    def _open_time_column_width(self) -> int:
        """Pixel width that fits YYYY-MM-DD HH:MM:SS and the Open Time heading."""
        sample = "2026-09-01 00:00:00"
        body = tkfont.Font(self, font=(self.ui_font, 11))
        heading = tkfont.Font(self, font=(self.ui_font, 10, "bold"))
        text = max(body.measure(sample), heading.measure("Open Time (UTC)"))
        return text + 28

    def _refresh_footer(self) -> None:
        self.footer_var.set(footer_status())

    def _apply_columns(self, specs: tuple) -> None:
        names = [spec[0] for spec in specs]
        self.tree.configure(columns=names, displaycolumns=names)
        open_time_floor = self._open_time_column_width()
        for name, heading, width, anchor, stretch in specs:
            floor = 64
            if name == "open_time":
                floor = open_time_floor
                width = max(width, floor)
            self.tree.heading(name, text=heading, anchor="center")
            self.tree.column(name, width=width, minwidth=floor, anchor=anchor, stretch=stretch)

    def _render_active_view(self) -> None:
        view = self.view_var.get()
        if view == "sentiment":
            self.candle_note.grid_remove()
            self._apply_columns(SENTIMENT_COLUMNS)
            self._fill_sentiment()
        elif view == "schema":
            self.candle_note.grid_remove()
            self._apply_columns(SCHEMA_COLUMNS)
            self._fill_schema()
        else:
            self.candle_note.grid()
            self._apply_columns(MARKET_COLUMNS)
            self._fill_market()

    def _fill_market(self) -> None:
        self.tree.delete(*self.tree.get_children())
        now_ms = utc_now_ms()
        for row in self._terminal["market"]:
            (
                open_time,
                open_price,
                high_price,
                low_price,
                close_price,
                volume,
                quote_volume,
                taker_base,
                trades,
                eth_close,
                close_time,
            ) = row
            change_text, tone = format_change(open_price, close_price)
            status = candle_status(int(close_time), now_ms)
            values = (
                format_utc(int(open_time)),
                format_usdt(open_price),
                format_usdt(high_price),
                format_usdt(low_price),
                format_usdt(close_price),
                change_text,
                format_btc_volume(volume),
                format_quote_millions(quote_volume),
                format_taker_share(taker_base, volume),
                f"{int(trades):,}",
                format_usdt(eth_close),
                status,
            )
            tags = ("live",) if status == "LIVE" else (tone,)
            self.tree.insert("", "end", values=values, tags=tags)

    def _fill_sentiment(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self._terminal["sentiment"]):
            date_str, timestamp, value, classification = row
            text = str(classification).lower()
            if "greed" in text:
                tag = "regime_greed"
            elif "fear" in text:
                tag = "regime_fear"
            elif "neutral" in text:
                tag = "regime_neutral"
            else:
                tag = "even" if index % 2 == 0 else "odd"
            self.tree.insert(
                "",
                "end",
                values=(date_str, f"{int(timestamp):,}", f"{int(value)}", classification),
                tags=(tag,),
            )

    def _fill_schema(self) -> None:
        self.tree.delete(*self.tree.get_children())
        counts = self._terminal["counts"]
        rows: list[tuple[str, str, str, str]] = []
        for symbol, base_asset, quote_asset, market_type in self._terminal["symbols"]:
            rows.append(
                (
                    str(symbol),
                    "Dimension asset",
                    f"{base_asset}/{quote_asset}  ·  {market_type}",
                    "—",
                )
            )
        rows.extend(
            (
                ("symbols", "Dimension table", "PRIMARY KEY (symbol)", f"{counts['symbols']:,}"),
                (
                    "hourly_klines",
                    "Fact table",
                    "PRIMARY KEY (symbol, open_time)  ·  FK symbols(symbol)",
                    f"{counts['hourly_klines']:,}",
                ),
                (
                    "daily_fear_greed",
                    "Sentiment table",
                    "PRIMARY KEY (timestamp)",
                    f"{counts['daily_fear_greed']:,}",
                ),
            )
        )
        index_detail = {
            "idx_klines_open_time": "hourly_klines (open_time)",
            "idx_klines_symbol": "hourly_klines (symbol)",
            "idx_fear_greed_date": "daily_fear_greed (date_str)",
            "ux_fear_greed_date": "daily_fear_greed (date_str) UNIQUE",
        }
        for name in self._terminal["indexes"]:
            rows.append((name, "Index", index_detail.get(name, name), "—"))
        for index, row in enumerate(rows):
            self.tree.insert("", "end", values=row, tags=("even" if index % 2 == 0 else "odd",))


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    app = BitVaultApp()
    app.mainloop()


if __name__ == "__main__":
    main()
