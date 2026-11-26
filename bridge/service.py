"""Business logic: GOWA <-> local CRM (SQLite). No EspoCRM, no MariaDB.

Inbound:  WhatsApp DM / channel post  -> CRM contact, timeline, content archive
Outbound: approved content            -> outbox -> GOWA -> published + counters
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time

from config import Config
from crm import CrmClient
from gowa import GowaClient, GowaError
from store import Store

log = logging.getLogger("bridge")

MAX_ATTEMPTS = 5
BACKOFF_STEP = 30  # seconds


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def jid_to_phone(jid: str, default_cc: str = "") -> str | None:
    """`9665xxxx@s.whatsapp.net` -> `+9665xxxx`. None for non-phone JIDs."""
    if not jid or "@" not in jid:
        return None
    user = jid.split("@", 1)[0].split(":", 1)[0]
    digits = re.sub(r"\D", "", user)
    if len(digits) < 8:
        return None
    if default_cc and digits.startswith("0"):
        digits = default_cc + digits[1:]
    return "+" + digits


def to_epoch(value) -> int | None:
    """Accept ISO-8601 or epoch seconds/milliseconds -> epoch seconds."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        stamp = float(value)
        if stamp > 1e11:  # milliseconds
            stamp /= 1000.0
        return int(stamp)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp())


def subject_for(payload: dict) -> str:
    body = (payload.get("body") or "").strip().replace("\n", " ")
    if body:
        return body[:120]
    return f"[{(payload.get('media_type') or 'post')}] channel post"


def media_type_for(payload: dict) -> str:
    raw = (payload.get("media_type") or payload.get("type") or "none").lower()
    for known in ("image", "video", "audio", "document", "sticker"):
        if known in raw:
            return known
    return "none"


def _first(payload: dict, *keys, default=None):
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


# --------------------------------------------------------------------------
# service
# --------------------------------------------------------------------------
class Bridge:
    def __init__(self, cfg: Config, crm: CrmClient | None = None,
                 gowa: GowaClient | None = None, store: Store | None = None):
        self.cfg = cfg
        self.store = store or Store(cfg.db_path)
        self.crm = crm or CrmClient(self.store)
        self.gowa = gowa or GowaClient(cfg.gowa_base_url, device_id=cfg.gowa_device_id)
        self._stop = threading.Event()
        self.stats = {"inbound": 0, "channel_posts": 0, "dms": 0, "published": 0, "errors": 0}

    # -- lifecycle ---------------------------------------------------------
    def start_workers(self) -> None:
        threading.Thread(target=self._outbox_loop, daemon=True, name="outbox").start()
        threading.Thread(target=self._poll_loop, daemon=True, name="poller").start()
        threading.Thread(target=self._channel_sync_loop, daemon=True, name="channelsync").start()

    def stop(self) -> None:
        self._stop.set()

    def _outbox_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.drain_outbox()
            except Exception:  # never let the worker die
                log.exception("outbox loop error")
            self._stop.wait(10)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_ready_posts()
            except Exception:
                log.exception("poller error")
            self._stop.wait(self.cfg.poll_interval)

    def _channel_sync_loop(self) -> None:
        # Sync immediately on boot (a restart must not lose posts), then on interval.
        while not self._stop.is_set():
            try:
                self.sync_channels()
                self.sync_counters()
                self.refresh_channel_info()
            except Exception:
                log.exception("channel sync error")
                self._stop.wait(5)
                continue
            self._stop.wait(self.cfg.channel_sync_interval)

    # -- inbound: GOWA -----------------------------------------------------
    def handle_gowa_event(self, event: dict) -> dict:
        self.stats["inbound"] += 1
        kind = event.get("event") or ""
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        if kind == "message":
            return self.handle_message(payload)
        if kind.startswith("newsletter."):
            if kind == "newsletter.message":
                return self.handle_counters(payload)
            log.info("newsletter event: %s", kind)
            return {"ok": True, "ignored": kind}
        return {"ok": True, "ignored": kind or "unknown"}

    def handle_message(self, payload: dict) -> dict:
        chat_id = payload.get("chat_id") or payload.get("from") or ""
        if chat_id.endswith("@newsletter"):
            return self.handle_channel_post(payload)
        if chat_id.endswith("@s.whatsapp.net"):
            return self.handle_dm(payload)
        return {"ok": True, "ignored": "chat_type"}

    def handle_dm(self, payload: dict) -> dict:
        if payload.get("is_from_me"):
            return {"ok": True, "ignored": "from_me"}
        jid = payload.get("from") or payload.get("chat_id") or ""
        phone = jid_to_phone(jid, self.cfg.default_country_code)
        if not phone:
            return {"ok": True, "ignored": "unmapped_jid"}
        message_id = payload.get("id")
        if message_id and self.store.seen(message_id):
            return {"ok": True, "ignored": "duplicate"}
        sender = _first(payload, "sender_display_name", "from_name", "push_name", default="")
        try:
            contact = self.crm.find_contact_by_phone(phone)
            created = False
            if not contact:
                contact = self.crm.create_contact(phone, first_name=sender or phone, jid=jid)
                created = True
            body = (payload.get("body") or "").strip()
            media = media_type_for(payload)
            text = body if body else f"[{media}]"
            self.crm.add_message(contact["id"], "in", text, message_id=message_id,
                                 media_type=media, at=to_epoch(payload.get("timestamp")))
            if message_id:
                self.store.mark_seen(message_id)
            self.stats["dms"] += 1
            return {"ok": True, "contactId": contact["id"], "created": created}
        except Exception as exc:  # noqa: BLE001
            self.stats["errors"] += 1
            log.error("DM mapping failed: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    def handle_channel_post(self, payload: dict) -> dict:
        message_id = payload.get("id")
        if not message_id:
            return {"ok": True, "ignored": "no_message_id"}
        if self.store.seen(message_id):
            return {"ok": True, "ignored": "duplicate"}
        jid = payload.get("chat_id") or ""
        if self.cfg.newsletter_jids and jid not in self.cfg.newsletter_jids:
            return {"ok": True, "ignored": "channel_not_monitored"}
        server_id = _first(payload, "server_id", "serverId")
        try:
            post = self.crm.create_channel_post({
                "channel_jid": jid,
                "title": subject_for(payload),
                "body": payload.get("body") or "",
                "status": "published",
                "media_type": media_type_for(payload),
                "created_by": "whatsapp",
            })
            self.crm.update_channel_post(post["id"], {
                "message_id": message_id,
                "published_at": to_epoch(payload.get("timestamp")) or int(time.time()),
                "server_id": int(server_id) if isinstance(server_id, (int, str)) and str(server_id).isdigit() else None,
                "views": int(_first(payload, "views_count", "views", default=0) or 0),
            })
            self.store.mark_seen(message_id)
            self.stats["channel_posts"] += 1
            log.info("channel post stored: %s (%s)", message_id, jid)
            return {"ok": True, "postId": post["id"]}
        except Exception as exc:  # noqa: BLE001
            self.stats["errors"] += 1
            log.error("channel post store failed: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    def handle_counters(self, payload: dict) -> dict:
        message_id = _first(payload, "message_id", "messageId", "id")
        if not message_id:
            return {"ok": True, "ignored": "no_message_id"}
        views = _first(payload, "views_count", "viewsCount", "views")
        forwards = _first(payload, "forwards_count", "forwardsCount", "forwards")
        reactions = _first(payload, "reaction_counts", "reactions", "reactionsCount")
        if isinstance(reactions, dict):
            reactions = sum(v for v in reactions.values() if isinstance(v, (int, float)))
        if not any(isinstance(v, (int, float)) for v in (views, forwards, reactions)):
            return {"ok": True, "ignored": "no_counters"}
        record = self.crm.find_channel_post_by_message(str(message_id))
        if not record:
            return {"ok": True, "ignored": "post_not_found"}
        self.crm.update_counters(record["id"],
                                 int(views) if isinstance(views, (int, float)) else None,
                                 int(forwards) if isinstance(forwards, (int, float)) else None,
                                 int(reactions) if isinstance(reactions, (int, float)) else None)
        log.info("counters updated for %s", message_id)
        return {"ok": True, "postId": record["id"]}

    # -- outbound publishing ----------------------------------------------
    def sync_ready_posts(self) -> int:
        due = self.crm.due_posts(limit=10)
        queued = 0
        for record in due:
            if self.store.enqueue("publish", record["id"], {"postId": record["id"]}):
                queued += 1
        if queued:
            log.info("queued %d due post(s)", queued)
            self.drain_outbox()
        return queued

    def drain_outbox(self) -> int:
        processed = 0
        for item in self.store.due(limit=5):
            payload = json.loads(item["payload"])
            attempts = int(item["attempts"])
            try:
                if item["kind"] == "publish":
                    self._publish(payload["postId"])
                self.store.finish(item["id"], status="done")
                processed += 1
            except Exception as exc:  # noqa: BLE001 - recorded and retried
                if attempts + 1 >= MAX_ATTEMPTS:
                    self.store.finish(item["id"], status="failed", error=str(exc)[:500])
                    self._mark_failed(payload.get("postId"), exc)
                    log.error("publish failed permanently for %s: %s", payload.get("postId"), exc)
                else:
                    self.store.finish(item["id"], error=str(exc)[:500],
                                      retry_in=BACKOFF_STEP * (attempts + 1))
                    if payload.get("postId"):
                        self.crm.release_post(payload["postId"])
                    log.warning("publish retry %d for %s: %s", attempts + 1,
                                payload.get("postId"), exc)
        return processed

    def _publish(self, post_id: str) -> None:
        record = self.crm.get_channel_post(post_id)
        if not record:
            raise ValueError(f"post {post_id} not found")
        if not self.crm.claim_post(post_id):
            log.info("skip %s: status=%s", post_id, record.get("status"))
            return
        jid = record.get("channel_jid")
        if not jid:
            self.crm.mark_failed(post_id, "post has no channel_jid")
            raise ValueError("post has no channel_jid")
        text = (record.get("body") or "").strip() or (record.get("title") or "").strip()
        if not text:
            self.crm.mark_failed(post_id, "post has no text")
            raise ValueError("post has no body/title to publish")
        response = self.gowa.send_message(jid, text)
        results = response.get("results") if isinstance(response.get("results"), dict) else {}
        message_id = results.get("message_id") or results.get("id")
        if message_id:
            # Our own post returns through the channel feed; mark it seen so the
            # archive sync does not create a duplicate record.
            self.store.mark_seen(message_id)
        self.crm.mark_published(post_id, message_id)
        self.stats["published"] += 1
        log.info("published %s to %s", post_id, jid)

    def _mark_failed(self, post_id: str | None, exc: Exception) -> None:
        if not post_id:
            return
        try:
            self.crm.mark_failed(post_id, str(exc))
        except Exception:  # noqa: BLE001
            log.exception("could not flag post %s as failed", post_id)

    # -- channel monitoring ------------------------------------------------
    def sync_channels(self) -> int:
        """Pull the newest posts per channel so nothing is lost while offline."""
        stored = 0
        for jid in self.cfg.newsletter_jids:
            try:
                self.gowa.subscribe_live_updates(jid)
            except GowaError as exc:
                log.warning("live-updates subscribe failed for %s: %s", jid, exc)
            try:
                response = self.gowa.newsletter_messages(jid, count=20)
            except GowaError as exc:
                log.warning("newsletter fetch failed for %s: %s", jid, exc)
                continue
            results = response.get("results") or {}
            messages = results.get("data") or results.get("messages") or []
            for item in messages or []:
                normalized = self._normalize_channel_message(item, jid)
                if not normalized.get("id"):
                    continue
                if self.store.seen(normalized["id"]):
                    continue
                result = self.handle_channel_post(normalized)
                if result.get("ok") and not result.get("ignored"):
                    stored += 1
        if stored:
            log.info("channel sync stored %d new post(s)", stored)
        return stored

    @staticmethod
    def _normalize_channel_message(item: dict, jid: str) -> dict:
        return {
            "id": _first(item, "message_id", "id"),
            "chat_id": jid,
            "body": _first(item, "text", "body", "caption", default=""),
            "media_type": _first(item, "media_type", "type", default="none"),
            "timestamp": _first(item, "timestamp", "time", "posted_at"),
            "server_id": _first(item, "server_id", "serverId"),
            "views_count": _first(item, "views_count", "views", default=0),
            "chat_name": _first(item, "channel_name", "newsletter_name", default=""),
        }

    # -- engagement counters ----------------------------------------------
    def sync_counters(self) -> int:
        updated = 0
        for jid in self.cfg.newsletter_jids:
            try:
                feed_response = self.gowa.newsletter_messages(jid, count=20)
            except GowaError as exc:
                log.warning("counter fetch failed for %s: %s", jid, exc)
                continue
            feed = (feed_response.get("results") or {}).get("data") or []
            server_ids = [i.get("server_id") for i in feed if isinstance(i.get("server_id"), int)]
            after = max(1, min(server_ids) - 1) if server_ids else 1
            try:
                updates_response = self.gowa.newsletter_message_updates(jid, after=after, count=20)
            except GowaError as exc:
                log.warning("counter updates failed for %s: %s", jid, exc)
                updates_response = {}
            counters = {
                item.get("server_id"): item
                for item in ((updates_response.get("results") or {}).get("data") or [])
            }
            for item in feed:
                message_id = item.get("message_id")
                if not message_id:
                    continue
                record = self.crm.find_channel_post_by_message(message_id)
                if not record:
                    continue
                server_id = item.get("server_id")
                counter = counters.get(server_id) or item
                views = counter.get("views_count", item.get("views_count"))
                forwards = counter.get("forwards_count", item.get("forwards_count"))
                reactions = counter.get("reaction_counts", item.get("reactions"))
                if isinstance(reactions, dict):
                    reactions = sum(v for v in reactions.values() if isinstance(v, (int, float)))
                changed = (
                    (isinstance(views, (int, float)) and int(views) != int(record.get("views") or 0)) or
                    (isinstance(forwards, (int, float)) and int(forwards) != int(record.get("forwards") or 0)) or
                    (isinstance(reactions, (int, float)) and int(reactions) != int(record.get("reactions") or 0)) or
                    (server_id and int(server_id) != int(record.get("server_id") or 0))
                )
                if not changed:
                    continue
                self.crm.update_counters(
                    record["id"],
                    int(views) if isinstance(views, (int, float)) else None,
                    int(forwards) if isinstance(forwards, (int, float)) else None,
                    int(reactions) if isinstance(reactions, (int, float)) else None,
                    int(server_id) if isinstance(server_id, int) else None,
                )
                self.crm.record_stats(record["id"])
                updated += 1
                log.info("counters updated for %s", message_id)
        return updated

    # -- channel profile ---------------------------------------------------
    def refresh_channel_info(self) -> dict:
        """Pull name/subscribers/invite from WhatsApp and cache it in SQLite."""
        jid = (self.cfg.newsletter_jids or ("",))[0]
        if not jid:
            return {}
        try:
            response = self.gowa.newsletter_info(jid)
        except GowaError as exc:
            log.warning("newsletter info failed: %s", exc)
            return {}
        result = response.get("results") or {}
        thread = result.get("thread_metadata") or {}
        viewer = result.get("viewer_metadata") or {}
        info = {
            "jid": result.get("id") or jid,
            "name": thread.get("name") or result.get("name") or "",
            "subscribers": viewer.get("subscribers") or result.get("subscribers"),
            "invite": result.get("invite") or "",
            "picture": thread.get("picture") or "",
        }
        saved = self.crm.save_channel_info(info)
        log.info("channel info cached: %s (%s subscribers)", info["name"], info["subscribers"])
        return saved

    # -- diagnostics -------------------------------------------------------
    def health(self) -> dict:
        gowa_ok = True
        try:
            self.gowa.device_status()
        except GowaError:
            gowa_ok = False
        return {
            "ok": gowa_ok and self.crm.ping(),
            "gowa": gowa_ok,
            "crm": self.crm.ping(),
            "queue": self.store.pending_count(),
            "stats": dict(self.stats),
            "db": self.cfg.db_path,
            "monitoredChannels": list(self.cfg.newsletter_jids),
        }
