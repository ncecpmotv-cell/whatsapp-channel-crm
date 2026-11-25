"""SQLite persistence: idempotency keys and a durable outbound outbox.

The outbox exists so a WhatsApp/GOWA outage never loses a scheduled post:
each publish attempt is stored, retried with backoff, and only marked done
after GOWA accepts it and EspoCRM records Published.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    message_id  TEXT PRIMARY KEY,
    received_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,
    ref           TEXT NOT NULL,
    payload       TEXT NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    next_attempt  REAL NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    last_error    TEXT,
    created_at    REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS outbox_active_ref
    ON outbox(kind, ref) WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- idempotency -------------------------------------------------------
    def seen(self, message_id: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM seen WHERE message_id = ?", (message_id,))
        return cur.fetchone() is not None

    def mark_seen(self, message_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen(message_id, received_at) VALUES (?, ?)",
            (message_id, int(time.time())),
        )
        self._conn.commit()

    # -- outbox ------------------------------------------------------------
    def enqueue(self, kind: str, ref: str, payload: dict, delay: float = 0) -> bool:
        """Queue work unless an identical pending item already exists."""
        try:
            self._conn.execute(
                "INSERT INTO outbox(kind, ref, payload, next_attempt, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, ref, json.dumps(payload), time.time() + delay, time.time()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def due(self, limit: int = 10):
        cur = self._conn.execute(
            "SELECT * FROM outbox WHERE status = 'pending' AND next_attempt <= ? "
            "ORDER BY next_attempt LIMIT ?",
            (time.time(), limit),
        )
        return [dict(row) for row in cur.fetchall()]

    def finish(self, item_id: int, status: str = "done", error: str | None = None,
               retry_in: float | None = None) -> None:
        if retry_in is None:
            self._conn.execute(
                "UPDATE outbox SET status = ?, last_error = ? WHERE id = ?",
                (status, error, item_id),
            )
        else:
            self._conn.execute(
                "UPDATE outbox SET attempts = attempts + 1, next_attempt = ?, last_error = ? "
                "WHERE id = ?",
                (time.time() + retry_in, error, item_id),
            )
        self._conn.commit()

    def pending_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'pending'")
        return int(cur.fetchone()[0])

    # -- misc --------------------------------------------------------------
    def get_meta(self, key: str):
        cur = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()
