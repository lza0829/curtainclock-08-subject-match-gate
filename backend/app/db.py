from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  capacity INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS teachers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  subject TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  subject TEXT NOT NULL,
  room_code TEXT NOT NULL,
  teacher_code TEXT NOT NULL,
  day TEXT NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
);
CREATE TABLE IF NOT EXISTS leases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lease_no TEXT NOT NULL UNIQUE,
  session_code TEXT NOT NULL,
  room_code TEXT NOT NULL,
  teacher_code TEXT NOT NULL,
  day TEXT NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  status TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS conflicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  session_code TEXT NOT NULL,
  resource_code TEXT NOT NULL,
  day TEXT NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watermarks (
  key TEXT PRIMARY KEY,
  value INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- 替身优先级表：每个主执行器一条有序替身链，position 从 1 开始
CREATE TABLE IF NOT EXISTS substitute_chains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  primary_code TEXT NOT NULL,
  position INTEGER NOT NULL,
  substitute_code TEXT NOT NULL,
  UNIQUE(primary_code, position),
  UNIQUE(primary_code, substitute_code)
);
"""

# 老库补列：租约快照需留替身痕迹
_LEASE_MIGRATIONS = (
    "ALTER TABLE leases ADD COLUMN primary_teacher_code TEXT",
    "ALTER TABLE leases ADD COLUMN substitute_hit INTEGER",
)


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction():
    # BEGIN IMMEDIATE：开窗/替身落库同事务，写锁立即取得，
    # 并发两路抢同一执行者时第二路被串行化，杜绝双占
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(leases)")}
    for stmt in _LEASE_MIGRATIONS:
        col = stmt.split("ADD COLUMN")[1].strip().split()[0]
        if col not in existing:
            conn.execute(stmt)


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
