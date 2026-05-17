"""aiosqlite-based database layer. Each call opens its own connection
so multiple processes (PM2 workers) can safely share the same WAL-mode file."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from core.config import settings

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS users (
    tg_id        INTEGER PRIMARY KEY,
    username     TEXT,
    sender_address TEXT UNIQUE,
    sender_address_verified INTEGER DEFAULT 1,
    balance_usdt TEXT    NOT NULL DEFAULT '0',
    total_spent  TEXT    NOT NULL DEFAULT '0',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id            TEXT    PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(tg_id),
    item_id       INTEGER NOT NULL,
    category      TEXT,
    price_paid    TEXT    NOT NULL,
    lzt_price_usd TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'PENDING'
                          CHECK (status IN ('PENDING','PURCHASING','DELIVERED','FAILED','REFUNDED')),
    phone         TEXT,
    login_code    TEXT,
    twofa_password TEXT,
    session_path  TEXT,
    fail_reason   TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    delivered_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS ix_orders_status  ON orders(status);

CREATE TABLE IF NOT EXISTS deposits (
    id           TEXT    PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(tg_id),
    tx_hash      TEXT    NOT NULL UNIQUE,
    from_address TEXT    NOT NULL,
    to_address   TEXT    NOT NULL,
    amount       TEXT    NOT NULL,
    block_ts     TEXT    NOT NULL,
    credited_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tron_cursor (
    id            INTEGER PRIMARY KEY DEFAULT 1,
    last_block_ts INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
-- 최초 생성 시 현재 시간으로 초기화 (과거 내역 조회 방지)
INSERT OR IGNORE INTO tron_cursor (id, last_block_ts)
  VALUES (1, CAST((strftime('%s','now')) * 1000 AS INTEGER));

CREATE TABLE IF NOT EXISTS deposit_sessions (
    user_id    INTEGER PRIMARY KEY,
    expires_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_cache (
    item_id    INTEGER PRIMARY KEY,
    category   TEXT,
    price_usd  TEXT,
    sell_price TEXT,
    country    TEXT,
    premium    INTEGER DEFAULT 0,
    spam_block INTEGER DEFAULT 0,
    title      TEXT,
    raw_json   TEXT,
    last_seen  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS unmatched_deposits (
    id           TEXT PRIMARY KEY,
    tx_hash      TEXT NOT NULL UNIQUE,
    from_address TEXT NOT NULL,
    amount       TEXT NOT NULL,
    block_ts     TEXT NOT NULL,
    raw_json     TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def init_db() -> None:
    """Create data directory and all tables on first run."""
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(_DDL)
        await db.commit()


@asynccontextmanager
async def get_conn() -> AsyncIterator[aiosqlite.Connection]:
    """Open a short-lived connection with Row factory enabled."""
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db
