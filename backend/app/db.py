import sqlite3
import threading
from contextlib import contextmanager

from .config import DB_PATH

_local = threading.local()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def cursor():
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id TEXT UNIQUE,
    name TEXT,
    brand TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    region TEXT,
    address TEXT,
    fuels TEXT,            -- json array of known fuel types
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_stations_bbox ON stations(lat, lon);
CREATE INDEX IF NOT EXISTS idx_stations_brand ON stations(brand);
CREATE INDEX IF NOT EXISTS idx_stations_region ON stations(region);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id INTEGER NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    status TEXT NOT NULL,          -- have/low/queue/none/closed
    fuel_type TEXT,                -- specific fuel or NULL = overall
    comment TEXT,
    photo TEXT,
    device_id TEXT,
    confirms INTEGER DEFAULT 0,
    flags INTEGER DEFAULT 0,
    hidden INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reports_station ON reports(station_id, created_at);

CREATE TABLE IF NOT EXISTS confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    device_id TEXT,
    kind TEXT,                     -- confirm / dispute
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(report_id, device_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id INTEGER NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    fuel_type TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(station_id, device_id, fuel_type)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db():
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_meta(key, default=None):
    with cursor() as cur:
        cur.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_meta(key, value):
    with cursor() as cur:
        cur.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
