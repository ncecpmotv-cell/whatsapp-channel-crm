"""CRM storage on one SQLite file — content pipeline, contacts, deals, metrics.

One file, one connection (shared with the bridge's outbox), stdlib only.
The public surface mirrors the old EspoClient so the rest of the bridge and
the MCP face barely change:

    find_contact_by_phone / create_contact / add_stream_note
    create_channel_post / update_channel_post / get_channel_post
    find_channel_post_by_message / list_ready_to_publish / ping

Content pipeline statuses: idea -> draft -> review -> scheduled -> publishing
-> published | failed. An agent may create drafts and propose a time; moving a
post into `scheduled` is a human approval (or an explicitly privileged token).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS crm_contacts (
    id           TEXT PRIMARY KEY,
    phone        TEXT UNIQUE,
    jid          TEXT,
    name         TEXT,
    org          TEXT,
    stage        TEXT NOT NULL DEFAULT 'lead',
    tags         TEXT NOT NULL DEFAULT '',
    notes        TEXT,
    last_inbound INTEGER,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS crm_posts (
    id           TEXT PRIMARY KEY,
    channel_jid  TEXT NOT NULL,
    title        TEXT,
    body         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK (status IN ('draft','scheduled','publishing','published','failed')),
    scheduled_at INTEGER,
    published_at INTEGER,
    message_id   TEXT,
    server_id    INTEGER,
    media_type   TEXT NOT NULL DEFAULT 'none',
    media_path   TEXT,
    meta         TEXT,
    views        INTEGER NOT NULL DEFAULT 0,
    forwards     INTEGER NOT NULL DEFAULT 0,
    reactions    INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    created_by   TEXT NOT NULL DEFAULT 'human',
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS crm_posts_message_id ON crm_posts(message_id)
    WHERE message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS crm_posts_board ON crm_posts(status, updated_at);
CREATE INDEX IF NOT EXISTS crm_posts_status_order
    ON crm_posts(status, COALESCE(scheduled_at, published_at, updated_at) DESC);
CREATE TABLE IF NOT EXISTS crm_messages (
    id          TEXT PRIMARY KEY,
    contact_id  TEXT,
    direction   TEXT NOT NULL,
    message_id  TEXT UNIQUE,
    body        TEXT,
    media_type  TEXT,
    at          INTEGER NOT NULL,
    read        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS crm_messages_contact ON crm_messages(contact_id, at DESC);
CREATE INDEX IF NOT EXISTS crm_contacts_last ON crm_contacts(last_inbound DESC);
CREATE INDEX IF NOT EXISTS crm_contacts_sort
    ON crm_contacts(COALESCE(last_inbound, updated_at) DESC);
CREATE TABLE IF NOT EXISTS crm_deals (
    id             TEXT PRIMARY KEY,
    contact_id     TEXT,
    title          TEXT NOT NULL,
    value          REAL,
    currency       TEXT NOT NULL DEFAULT 'SAR',
    stage          TEXT NOT NULL DEFAULT 'new',
    next_action_at INTEGER,
    notes          TEXT,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS crm_activities (
    id         TEXT PRIMARY KEY,
    contact_id TEXT,
    deal_id    TEXT,
    type       TEXT NOT NULL DEFAULT 'note',
    at         INTEGER NOT NULL,
    due_at     INTEGER,
    body       TEXT,
    done       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS crm_activities_due ON crm_activities(due_at) WHERE done = 0;
CREATE TABLE IF NOT EXISTS crm_stats (
    post_id    TEXT NOT NULL,
    day        TEXT NOT NULL,
    views      INTEGER NOT NULL DEFAULT 0,
    forwards   INTEGER NOT NULL DEFAULT 0,
    reactions  INTEGER NOT NULL DEFAULT 0,
    captured_at INTEGER NOT NULL,
    PRIMARY KEY (post_id, day)
);
CREATE TABLE IF NOT EXISTS crm_notifications (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT,
    link       TEXT,
    at         INTEGER NOT NULL,
    read       INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS crm_notifications_unread ON crm_notifications(read, at DESC);
CREATE INDEX IF NOT EXISTS crm_notifications_recent ON crm_notifications(at DESC);
CREATE TABLE IF NOT EXISTS crm_chat (
    id      TEXT PRIMARY KEY,
    role    TEXT NOT NULL,
    content TEXT NOT NULL,
    at      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS crm_channel_info (
    jid         TEXT PRIMARY KEY,
    name        TEXT,
    subscribers INTEGER,
    invite      TEXT,
    picture     TEXT,
    fetched_at  INTEGER
);
"""

STAGES = ("draft", "scheduled", "publishing", "published", "failed")
LEGACY_STATUSES = {"idea": "draft", "review": "draft"}
DEAL_STAGES = ("new", "contacted", "proposal", "negotiation", "won", "lost")
CONTACT_STAGES = ("lead", "qualified", "customer", "partner", "cold")


def _now() -> int:
    return int(time.time())


def _tz_offset() -> int:
    try:
        return int(os.environ.get("TZ_OFFSET", "0"))
    except ValueError:
        return 0


def _row(row) -> dict | None:
    return dict(row) if row is not None else None


class CrmClient:
    """SQLite-backed CRM. Shares the bridge Store's connection and lock."""

    def __init__(self, store):
        self.store = store
        self._conn = store.conn
        self._lock = store.lock
        with self._lock:
            self._conn.executescript(SCHEMA)
            # one-way migration: legacy stages collapse into draft
            for old, new in LEGACY_STATUSES.items():
                self._conn.execute(
                    "UPDATE crm_posts SET status = ? WHERE status = ?", (new, old))
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(crm_posts)")}
            if "meta" not in columns:
                self._conn.execute("ALTER TABLE crm_posts ADD COLUMN meta TEXT")
            self._conn.commit()

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    def _exec(self, sql: str, params: tuple = ()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> dict | None:
        with self._lock:
            return _row(self._conn.execute(sql, params).fetchone())

    def ping(self) -> bool:
        try:
            self._one("SELECT 1 AS ok")
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # contacts
    # ------------------------------------------------------------------
    def find_contact_by_phone(self, phone: str) -> dict | None:
        return self._one("SELECT * FROM crm_contacts WHERE phone = ?", (phone,))

    def get_contact(self, contact_id: str) -> dict | None:
        return self._one("SELECT * FROM crm_contacts WHERE id = ?", (contact_id,))

    def create_contact(self, phone: str, first_name: str = "", last_name: str = "",
                       org: str = "", jid: str = "") -> dict:
        name = " ".join(p for p in (first_name, last_name) if p).strip() or phone
        contact_id = uuid.uuid4().hex[:12]
        ts = _now()
        self._exec(
            "INSERT INTO crm_contacts (id, phone, jid, name, org, created_at, updated_at, last_inbound) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (contact_id, phone, jid or None, name, org, ts, ts, ts),
        )
        return self.get_contact(contact_id) or {}

    def upsert_contact(self, phone: str, name: str | None = None, org: str | None = None,
                       stage: str | None = None, tags: list[str] | None = None,
                       notes: str | None = None) -> dict:
        existing = self.find_contact_by_phone(phone)
        if not existing:
            rec = self.create_contact(phone, first_name=name or "")
            existing = rec
        fields, params = [], []
        if name:
            fields.append("name = ?")
            params.append(name)
        if org:
            fields.append("org = ?")
            params.append(org)
        if stage and stage in CONTACT_STAGES:
            fields.append("stage = ?")
            params.append(stage)
        if tags is not None:
            fields.append("tags = ?")
            params.append(",".join(tags))
        if notes:
            fields.append("notes = ?")
            params.append(notes)
        if fields:
            fields.append("updated_at = ?")
            params.append(_now())
            params.append(existing["id"])
            self._exec(f"UPDATE crm_contacts SET {', '.join(fields)} WHERE id = ?", tuple(params))
        return self.get_contact(existing["id"]) or existing

    def touch_inbound(self, contact_id: str) -> None:
        self._exec("UPDATE crm_contacts SET last_inbound = ?, updated_at = ? WHERE id = ?",
                   (_now(), _now(), contact_id))

    def list_contacts(self, q: str | None = None, limit: int = 200) -> list[dict]:
        if q:
            like = f"%{q}%"
            return self._all(
                "SELECT * FROM crm_contacts WHERE name LIKE ? OR phone LIKE ? OR org LIKE ? "
                "ORDER BY COALESCE(last_inbound, updated_at) DESC LIMIT ?",
                (like, like, like, limit),
            )
        return self._all(
            "SELECT * FROM crm_contacts ORDER BY COALESCE(last_inbound, updated_at) DESC LIMIT ?",
            (limit,),
        )

    # ------------------------------------------------------------------
    # timeline
    # ------------------------------------------------------------------
    def add_message(self, contact_id: str | None, direction: str, body: str,
                    message_id: str | None = None, media_type: str | None = None,
                    at: int | None = None, read: bool = False) -> dict:
        mid = uuid.uuid4().hex[:12]
        self._exec(
            "INSERT OR IGNORE INTO crm_messages (id, contact_id, direction, message_id, body, media_type, at, read) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, contact_id, direction, message_id, body, media_type, at or _now(), 1 if read else 0),
        )
        if direction == "in" and contact_id:
            self.touch_inbound(contact_id)
        return {"id": mid}

    def list_messages(self, contact_id: str, limit: int = 50) -> list[dict]:
        return self._all(
            "SELECT * FROM crm_messages WHERE contact_id = ? ORDER BY at DESC LIMIT ?",
            (contact_id, limit),
        )

    def unread_count(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM crm_messages WHERE direction='in' AND read=0")
        return int(row["n"]) if row else 0

    def add_stream_note(self, entity_type: str, entity_id: str, text: str) -> dict:
        note_id = uuid.uuid4().hex[:12]
        self._exec(
            "INSERT INTO crm_activities (id, contact_id, type, at, body) VALUES (?, ?, 'note', ?, ?)",
            (note_id, entity_id if entity_type in ("Contact", "crm_contacts") else None, _now(), text),
        )
        return {"id": note_id, "type": "note"}

    def add_activity(self, contact_id: str | None, type_: str, body: str,
                     due_at: int | None = None, deal_id: str | None = None) -> dict:
        aid = uuid.uuid4().hex[:12]
        self._exec(
            "INSERT INTO crm_activities (id, contact_id, deal_id, type, at, due_at, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (aid, contact_id, deal_id, type_, _now(), due_at, body),
        )
        return {"id": aid}

    def followups(self, days: int = 0, limit: int = 50) -> list[dict]:
        horizon = _now() + max(0, days) * 86400
        return self._all(
            "SELECT a.*, c.name AS contact_name, c.phone AS contact_phone, d.title AS deal_title "
            "FROM crm_activities a LEFT JOIN crm_contacts c ON c.id = a.contact_id "
            "LEFT JOIN crm_deals d ON d.id = a.deal_id "
            "WHERE a.done = 0 AND a.due_at IS NOT NULL AND a.due_at <= ? "
            "ORDER BY a.due_at ASC LIMIT ?",
            (horizon, limit),
        )

    def complete_activity(self, activity_id: str) -> bool:
        cur = self._exec("UPDATE crm_activities SET done = 1 WHERE id = ?", (activity_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # deals
    # ------------------------------------------------------------------
    def upsert_deal(self, title: str, contact_id: str | None = None, value: float | None = None,
                    stage: str | None = None, next_action_at: int | None = None,
                    notes: str | None = None, deal_id: str | None = None) -> dict:
        ts = _now()
        if deal_id:
            fields, params = [], []
            for col, val in (("title", title), ("value", value), ("stage", stage),
                             ("next_action_at", next_action_at), ("notes", notes)):
                if val is not None:
                    fields.append(f"{col} = ?")
                    params.append(val)
            fields.append("updated_at = ?")
            params.append(ts)
            params.append(deal_id)
            self._exec(f"UPDATE crm_deals SET {', '.join(fields)} WHERE id = ?", tuple(params))
            return self._one("SELECT * FROM crm_deals WHERE id = ?", (deal_id,)) or {}
        new_id = uuid.uuid4().hex[:12]
        self._exec(
            "INSERT INTO crm_deals (id, contact_id, title, value, stage, next_action_at, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, contact_id, title, value, stage if stage in DEAL_STAGES else "new",
             next_action_at, notes, ts, ts),
        )
        return self._one("SELECT * FROM crm_deals WHERE id = ?", (new_id,)) or {}

    def list_deals(self, stage: str | None = None, limit: int = 200) -> list[dict]:
        if stage:
            return self._all(
                "SELECT d.*, c.name AS contact_name FROM crm_deals d "
                "LEFT JOIN crm_contacts c ON c.id = d.contact_id "
                "WHERE d.stage = ? ORDER BY d.updated_at DESC LIMIT ?", (stage, limit))
        return self._all(
            "SELECT d.*, c.name AS contact_name FROM crm_deals d "
            "LEFT JOIN crm_contacts c ON c.id = d.contact_id "
            "ORDER BY d.updated_at DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------
    # content pipeline
    # ------------------------------------------------------------------
    def create_channel_post(self, fields: dict) -> dict:
        """Create a post. Status is clamped unless the caller is privileged.

        Accepts both the legacy Espo field names (name/channelJid/status) and
        the new ones (title/channel_jid/status).
        """
        channel = fields.get("channel_jid") or fields.get("channelJid") or ""
        if not channel:
            raise ValueError("channel_jid is required")
        title = fields.get("title") or fields.get("name") or ""
        body = fields.get("body") or ""
        status = fields.get("status") or "draft"
        if status in ("New", ""):
            status = "draft"
        if status not in STAGES:
            status = "draft"
        post_id = uuid.uuid4().hex[:12]
        ts = _now()
        self._exec(
            "INSERT INTO crm_posts (id, channel_jid, title, body, status, scheduled_at, media_type, "
            "media_path, meta, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (post_id, channel, title, body, status, fields.get("scheduled_at"),
             fields.get("media_type") or "none", fields.get("media_path"), fields.get("meta"),
             fields.get("created_by") or "human", ts, ts),
        )
        return self.get_channel_post(post_id) or {}

    def update_channel_post(self, post_id: str, fields: dict, allowed_statuses: tuple | None = None) -> dict:
        mapping = {
            "status": "status", "title": "title", "name": "title", "body": "body",
            "scheduled_at": "scheduled_at", "published_at": "published_at",
            "message_id": "message_id", "messageId": "message_id",
            "server_id": "server_id", "serverId": "server_id",
            "views": "views", "viewsCount": "views",
            "forwards": "forwards", "forwardsCount": "forwards",
            "reactions": "reactions", "reactionsCount": "reactions",
            "last_error": "last_error", "lastError": "last_error",
            "media_type": "media_type", "media_path": "media_path", "meta": "meta",
        }
        sets, params = [], []
        for key, value in fields.items():
            column = mapping.get(key)
            if not column:
                continue
            if column == "status":
                if value not in STAGES:
                    continue
                if allowed_statuses is not None and value not in allowed_statuses:
                    raise PermissionError(
                        f"status '{value}' needs human approval (allowed: {', '.join(allowed_statuses)})"
                    )
            sets.append(f"{column} = ?")
            params.append(value)
        if not sets:
            return self.get_channel_post(post_id) or {}
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(post_id)
        self._exec(f"UPDATE crm_posts SET {', '.join(sets)} WHERE id = ?", tuple(params))
        return self.get_channel_post(post_id) or {}

    # Drafts were never sent; cancelled items are already out of the way.
    # Published posts belong to the channel, and scheduled/publishing ones are
    # in flight — cancel first, then delete.
    DELETABLE = ("draft", "failed")

    def cancel_post(self, post_id: str) -> dict:
        """Mark as cancelled (ملغى): keeps the record, stops any queued send."""
        post = self.get_channel_post(post_id)
        if not post:
            raise ValueError("المنشور غير موجود")
        if post["status"] == "published":
            raise PermissionError("لا يمكن إلغاء منشور منشور على القناة")
        self._exec("DELETE FROM outbox WHERE ref = ? AND status = 'pending'", (post_id,))
        return self.update_channel_post(
            post_id, {"status": "failed", "last_error": "أُلغي يدويًا"},
            allowed_statuses=("draft", "scheduled", "publishing", "failed"),
        )

    def restore_post(self, post_id: str) -> dict:
        """Bring a cancelled post back to draft."""
        return self.update_channel_post(
            post_id, {"status": "draft", "last_error": "", "scheduled_at": None},
            allowed_statuses=("draft",),
        )

    def delete_post(self, post_id: str) -> dict:
        """Permanently remove a cancelled post."""
        post = self.get_channel_post(post_id)
        if not post:
            raise ValueError("المنشور غير موجود")
        if post["status"] == "published":
            raise PermissionError("لا يمكن حذف منشور منشور على القناة")
        if post["status"] not in self.DELETABLE:
            raise PermissionError("ألغِ العنصر أولًا ثم احذفه نهائيًا")
        self._exec("DELETE FROM outbox WHERE ref = ? AND status IN ('pending','failed')", (post_id,))
        self._exec("DELETE FROM crm_stats WHERE post_id = ?", (post_id,))
        self._exec("DELETE FROM crm_posts WHERE id = ?", (post_id,))
        return {"id": post_id, "deleted": True}

    def get_channel_post(self, post_id: str) -> dict | None:
        return self._one("SELECT * FROM crm_posts WHERE id = ?", (post_id,))

    def find_channel_post_by_message(self, message_id: str) -> dict | None:
        return self._one("SELECT * FROM crm_posts WHERE message_id = ?", (message_id,))

    def find_post_by_server_id(self, server_id: int) -> dict | None:
        return self._one("SELECT * FROM crm_posts WHERE server_id = ?", (server_id,))

    def list_posts(self, status: str | None = None, limit: int = 100,
                   offset: int = 0) -> list[dict]:
        if status:
            return self._all(
                "SELECT * FROM crm_posts WHERE status = ? ORDER BY "
                "COALESCE(scheduled_at, published_at, updated_at) DESC LIMIT ? OFFSET ?",
                (status, limit, max(0, offset)))
        return self._all(
            "SELECT * FROM crm_posts ORDER BY COALESCE(scheduled_at, published_at, updated_at) DESC "
            "LIMIT ? OFFSET ?", (limit, max(0, offset)))

    def due_posts(self, limit: int = 10) -> list[dict]:
        return self._all(
            "SELECT * FROM crm_posts WHERE status = 'scheduled' AND scheduled_at IS NOT NULL "
            "AND scheduled_at <= ? ORDER BY scheduled_at ASC LIMIT ?", (_now(), limit))

    def list_ready_to_publish(self, limit: int = 10) -> list[dict]:
        """Legacy name used by the outbox poller."""
        return self.due_posts(limit)

    def claim_post(self, post_id: str) -> bool:
        cur = self._exec(
            "UPDATE crm_posts SET status='publishing', updated_at=? "
            "WHERE id=? AND status IN ('scheduled','publishing')",
            (_now(), post_id))
        return cur.rowcount > 0

    def release_post(self, post_id: str) -> None:
        """Return a claimed post to the queue so the outbox can retry it."""
        self._exec(
            "UPDATE crm_posts SET status='scheduled', updated_at=? "
            "WHERE id=? AND status='publishing'", (_now(), post_id))

    def mark_published(self, post_id: str, message_id: str | None = None) -> None:
        fields = {"status": "published", "published_at": _now(), "last_error": None}
        if message_id:
            fields["message_id"] = message_id
        self.update_channel_post(post_id, fields)

    def mark_failed(self, post_id: str, error: str) -> None:
        self.update_channel_post(post_id, {"status": "failed", "last_error": error[:1000]})

    def schedule_post(self, post_id: str, at: int, approved: bool) -> dict:
        status = "scheduled" if approved else "draft"
        return self.update_channel_post(
            post_id, {"status": status, "scheduled_at": at},
            allowed_statuses=("draft", "scheduled", "failed"),
        )

    def count_posts(self, status: str | None = None) -> int:
        if status:
            row = self._one("SELECT COUNT(*) AS n FROM crm_posts WHERE status = ?", (status,))
        else:
            row = self._one("SELECT COUNT(*) AS n FROM crm_posts")
        return int((row or {}).get("n") or 0)

    # ------------------------------------------------------------------
    # metrics
    # ------------------------------------------------------------------
    def update_counters(self, post_id: str, views: int | None, forwards: int | None,
                        reactions: int | None, server_id: int | None = None) -> None:
        fields = {}
        if views is not None:
            fields["views"] = views
        if forwards is not None:
            fields["forwards"] = forwards
        if reactions is not None:
            fields["reactions"] = reactions
        if server_id is not None:
            fields["server_id"] = server_id
        if fields:
            self.update_channel_post(post_id, fields)

    def channel_metrics(self, days: int = 7) -> dict:
        since = _now() - max(1, days) * 86400
        rows = self._all(
            "SELECT id, title, substr(body, 1, 80) AS body, published_at, views, forwards, reactions "
            "FROM crm_posts WHERE status='published' AND COALESCE(published_at, updated_at) >= ? "
            "ORDER BY COALESCE(published_at, updated_at) DESC LIMIT 100", (since,))
        total = {
            "views": sum(r["views"] or 0 for r in rows),
            "forwards": sum(r["forwards"] or 0 for r in rows),
            "reactions": sum(r["reactions"] or 0 for r in rows),
            "posts": len(rows),
        }
        return {"days": days, "total": total, "posts": rows}

    def content_insights(self, days: int = 30) -> dict:
        """Aggregate what worked: per type, cadence, best and worst posts."""
        since = _now() - max(1, days) * 86400
        rows = self._all(
            "SELECT id, title, substr(body, 1, 90) AS body, media_type, published_at, "
            "views, forwards, reactions FROM crm_posts "
            "WHERE status='published' AND COALESCE(published_at, updated_at) >= ? "
            "ORDER BY COALESCE(views, 0) DESC", (since,))
        if not rows:
            return {"days": days, "posts": 0, "note": "لا منشورات منشورة في هذه الفترة"}

        def rate(views: float, forwards: float, reactions: float) -> float:
            return round((forwards + reactions) * 100 / views, 2) if views else 0.0

        total: dict[str, float] = {"posts": len(rows),
                 "views": sum(r["views"] or 0 for r in rows),
                 "forwards": sum(r["forwards"] or 0 for r in rows),
                 "reactions": sum(r["reactions"] or 0 for r in rows)}
        total["avg_views"] = round(total["views"] / total["posts"], 1)
        total["engagement_pct"] = rate(total["views"], total["forwards"], total["reactions"])

        by_type: dict[str, dict] = {}
        for row in rows:
            key = row.get("media_type") or "text"
            bucket = by_type.setdefault(
                key, {"posts": 0, "views": 0, "forwards": 0, "reactions": 0})
            bucket["posts"] += 1
            bucket["views"] += row["views"] or 0
            bucket["forwards"] += row["forwards"] or 0
            bucket["reactions"] += row["reactions"] or 0
        for bucket in by_type.values():
            bucket["avg_views"] = round(bucket["views"] / bucket["posts"], 1)
            bucket["engagement_pct"] = rate(
                bucket["views"], bucket["forwards"], bucket["reactions"])

        def brief(row: dict) -> dict:
            return {"id": row["id"], "title": row.get("title") or (row.get("body") or "")[:60],
                    "type": row.get("media_type") or "text", "views": row["views"] or 0,
                    "forwards": row["forwards"] or 0, "reactions": row["reactions"] or 0,
                    "engagement_pct": rate(row["views"] or 0, row["forwards"] or 0,
                                           row["reactions"] or 0)}

        return {
            "days": days,
            "posts": len(rows),
            "total": total,
            "by_type": by_type,
            "top": [brief(r) for r in rows[:5]],
            "bottom": [brief(r) for r in reversed(rows[-3:])],
            "cadence_per_week": round(len(rows) / max(1, days / 7), 1),
        }

    def posting_times(self, days: int = 90, tz_offset: int | None = None) -> dict:
        """Which weekday/hour pairs actually collected views (local time)."""
        offset = _tz_offset() if tz_offset is None else int(tz_offset)
        since = _now() - max(1, days) * 86400
        rows = self._all(
            "SELECT published_at, views, forwards, reactions FROM crm_posts "
            "WHERE status='published' AND published_at IS NOT NULL AND published_at >= ?",
            (since,))
        days_ar = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
        buckets: dict[tuple[int, int], dict] = {}
        for row in rows:
            local = dt.datetime.utcfromtimestamp(int(row["published_at"])) + dt.timedelta(hours=offset)
            key = (local.weekday(), local.hour)
            bucket = buckets.setdefault(key, {"posts": 0, "views": 0})
            bucket["posts"] += 1
            bucket["views"] += row["views"] or 0
        ranked = [
            {"weekday": days_ar[wd], "hour": hour, "posts": b["posts"],
             "avg_views": round(b["views"] / b["posts"], 1)}
            for (wd, hour), b in buckets.items()
        ]
        ranked.sort(key=lambda x: (-x["avg_views"], -x["posts"]))
        return {"days": days, "tz_offset": offset, "buckets": len(ranked),
                "best": ranked[:8], "worst": ranked[-3:] if len(ranked) > 3 else []}

    # -- history / channel profile -----------------------------------------
    def record_stats(self, post_id: str) -> None:
        """Snapshot today's counters for a post (one row per day)."""
        post = self.get_channel_post(post_id)
        if not post:
            return
        day = time.strftime("%Y-%m-%d", time.gmtime())
        self._exec(
            "INSERT INTO crm_stats (post_id, day, views, forwards, reactions, captured_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(post_id, day) DO UPDATE SET "
            "views=excluded.views, forwards=excluded.forwards, reactions=excluded.reactions, "
            "captured_at=excluded.captured_at",
            (post_id, day, post.get("views") or 0, post.get("forwards") or 0,
             post.get("reactions") or 0, _now()),
        )

    def post_history(self, post_id: str, days: int = 30) -> list[dict]:
        return self._all(
            "SELECT day, views, forwards, reactions FROM crm_stats "
            "WHERE post_id = ? ORDER BY day ASC", (post_id,))[-max(1, days):]

    def save_channel_info(self, info: dict) -> dict:
        self._exec(
            "INSERT INTO crm_channel_info (jid, name, subscribers, invite, picture, fetched_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(jid) DO UPDATE SET name=excluded.name, "
            "subscribers=excluded.subscribers, invite=excluded.invite, picture=excluded.picture, "
            "fetched_at=excluded.fetched_at",
            (info.get("jid"), info.get("name"), info.get("subscribers"),
             info.get("invite"), info.get("picture"), _now()),
        )
        return self.get_channel_info(info.get("jid") or "") or {}

    def get_channel_info(self, jid: str) -> dict | None:
        return self._one("SELECT * FROM crm_channel_info WHERE jid = ?", (jid,))

    def channel_summary(self, days: int = 30) -> dict:
        since = _now() - max(1, days) * 86400
        posts = self._all(
            "SELECT id, title, body, views, forwards, reactions, published_at FROM crm_posts "
            "WHERE status='published' AND COALESCE(published_at, updated_at) >= ? "
            "ORDER BY COALESCE(published_at, updated_at) DESC", (since,))
        views = sum(p["views"] or 0 for p in posts)
        forwards = sum(p["forwards"] or 0 for p in posts)
        reactions = sum(p["reactions"] or 0 for p in posts)
        best = max(posts, key=lambda p: p["views"] or 0, default=None)
        return {
            "days": days,
            "count": len(posts),
            "views": views,
            "forwards": forwards,
            "reactions": reactions,
            "avg_views": round(views / len(posts), 1) if posts else 0,
            "engagement_pct": round((forwards + reactions) * 100 / views, 2) if views else 0,
            "best": best,
            "top": sorted(posts, key=lambda p: (p["views"] or 0), reverse=True)[:5],
            "posts": posts,
        }

    def daily_series(self, days: int = 14) -> list[dict]:
        rows = self._all(
            "SELECT day, SUM(views) AS views, SUM(forwards) AS forwards, SUM(reactions) AS reactions "
            "FROM crm_stats WHERE day >= date('now', ?) GROUP BY day ORDER BY day ASC",
            (f"-{max(1, days)} day",))
        return rows

    # -- notifications ------------------------------------------------------
    def notify(self, kind: str, title: str, body: str = "", link: str = "",
               dedupe_key: str | None = None) -> bool:
        try:
            self._exec(
                "INSERT INTO crm_notifications (id, kind, title, body, link, at, dedupe_key) "
                "VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex[:12], kind, title, body, link, _now(), dedupe_key))
            return True
        except Exception:  # duplicate dedupe_key
            return False

    def notifications(self, limit: int = 50) -> list[dict]:
        return self._all("SELECT * FROM crm_notifications ORDER BY at DESC LIMIT ?", (limit,))

    def unread_notifications(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM crm_notifications WHERE read = 0")
        return int(row["n"]) if row else 0

    def mark_notifications_read(self) -> None:
        self._exec("UPDATE crm_notifications SET read = 1 WHERE read = 0")

    # -- chat transcript ----------------------------------------------------
    def add_chat(self, role: str, content: str) -> dict:
        cid = uuid.uuid4().hex[:12]
        self._exec("INSERT INTO crm_chat (id, role, content, at) VALUES (?,?,?,?)",
                   (cid, role, content, _now()))
        return {"id": cid, "role": role, "content": content}

    def chat_history(self, limit: int = 50) -> list[dict]:
        rows = self._all("SELECT * FROM crm_chat ORDER BY at DESC, rowid DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    def stats(self) -> dict:
        def count(sql: str) -> int:
            row = self._one(sql)
            return int(row["n"]) if row else 0
        return {
            "contacts": count("SELECT COUNT(*) AS n FROM crm_contacts"),
            "posts": count("SELECT COUNT(*) AS n FROM crm_posts"),
            "published": count("SELECT COUNT(*) AS n FROM crm_posts WHERE status='published'"),
            "scheduled": count("SELECT COUNT(*) AS n FROM crm_posts WHERE status='scheduled'"),
            "deals": count("SELECT COUNT(*) AS n FROM crm_deals"),
            "unread": count("SELECT COUNT(*) AS n FROM crm_messages WHERE direction='in' AND read=0"),
        }

    def search(self, entity: str, q: str | None = None, phone: str | None = None,
               limit: int = 20) -> dict:
        limit = max(1, min(int(limit or 20), 100))
        if entity in ("Contact", "contacts"):
            if phone:
                row = self.find_contact_by_phone(phone)
                return {"total": 1 if row else 0, "list": [row] if row else []}
            return {"total": len(self.list_contacts(q, limit)), "list": self.list_contacts(q, limit)}
        if entity in ("WhatsAppChannelPost", "posts", "content"):
            rows = self.list_posts(None, limit)
            if q:
                rows = [r for r in rows if q.lower() in (r["body"] or "").lower()
                        or q.lower() in (r["title"] or "").lower()]
            return {"total": len(rows), "list": rows[:limit]}
        if entity in ("Deal", "deals"):
            return {"total": len(self.list_deals(None, limit)), "list": self.list_deals(None, limit)}
        raise ValueError(f"unsupported entity: {entity}")

    def get_record(self, entity: str, record_id: str) -> dict:
        if entity in ("Contact", "contacts"):
            rec = self.get_contact(record_id)
        elif entity in ("WhatsAppChannelPost", "posts", "content"):
            rec = self.get_channel_post(record_id)
        elif entity in ("Deal", "deals"):
            rec = self._one("SELECT * FROM crm_deals WHERE id = ?", (record_id,))
        else:
            raise ValueError(f"unsupported entity: {entity}")
        if not rec:
            raise ValueError(f"{entity} {record_id} not found")
        return rec


def dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
