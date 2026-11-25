"""Business logic for the GOWA <-> EspoCRM bridge."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time

from config import Config
from espocrm import EspoClient, EspoError
from gowa import GowaClient, GowaError
from store import Store

log = logging.getLogger("bridge")

MAX_ATTEMPTS = 5
BACKOFF_STEP = 30  # seconds


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def jid_to_phone(jid: str, default_cc: str = "") -> str | None:
    """`9665xxxx@s.whatsapp.net` -> `+9665xxxx`. Returns None for non-phone JIDs."""
    if not jid or "@" not in jid:
        return None
    user = jid.split("@", 1)[0].split(":", 1)[0]
    digits = re.sub(r"\D", "", user)
    if len(digits) < 8:
        return None
    if default_cc and digits.startswith("0"):
        digits = default_cc + digits[1:]
    return "+" + digits


def to_espo_datetime(value) -> str | None:
    """Accept ISO-8601 or epoch seconds and return Espo's UTC 'Y-m-d H:i:s'."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        stamp = float(value)
        if stamp > 1e11:  # milliseconds
            stamp /= 1000.0
        return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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
    def __init__(self, cfg: Config, espo: EspoClient | None = None,
                 gowa: GowaClient | None = None, store: Store | None = None):
        self.cfg = cfg
        self.espo = espo or EspoClient(cfg.espo_base_url, cfg.espo_api_key)
        self.gowa = gowa or GowaClient(cfg.gowa_base_url, device_id=cfg.gowa_device_id)
        self.store = store or Store(cfg.db_path)
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
        # first run shortly after boot so a restart does not lose posts
        self._stop.wait(15)
        while not self._stop.is_set():
            try:
                self.sync_channels()
                self.sync_counters()
            except Exception:
                log.exception("channel sync error")
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
            contact = self.espo.find_contact_by_phone(phone)
            created = False
            if not contact:
                contact = self.espo.create_contact(phone, first_name=sender or phone)
                created = True
            body = (payload.get("body") or "").strip()
            media = media_type_for(payload)
            text = body if body else f"[{media}]"
            stamp = to_espo_datetime(payload.get("timestamp"))
            note = f"WhatsApp ({phone})"
            if stamp:
                note += f" · {stamp} UTC"
            note += f": {text}"
            self.espo.add_stream_note("Contact", contact["id"], note[:1500])
            if message_id:
                self.store.mark_seen(message_id)
            self.stats["dms"] += 1
            return {"ok": True, "contactId": contact["id"], "created": created}
        except EspoError as exc:
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
        fields = {
            "name": subject_for(payload),
            "channelJid": jid,
            "channelName": _first(payload, "chat_name", "channel_name", default="") or "",
            "messageId": message_id,
            "body": payload.get("body") or "",
            "mediaType": media_type_for(payload),
            "postedAt": to_espo_datetime(payload.get("timestamp")),
            "status": "New",
        }
        server_id = _first(payload, "server_id", "serverId")
        if isinstance(server_id, (int, str)) and str(server_id).isdigit():
            fields["serverId"] = int(server_id)
        try:
            record = self.espo.create_channel_post(fields)
            self.store.mark_seen(message_id)
            self.stats["channel_posts"] += 1
            log.info("channel post stored: %s (%s)", message_id, jid)
            return {"ok": True, "postId": record.get("id")}
        except EspoError as exc:
            self.stats["errors"] += 1
            log.error("channel post store failed: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    def handle_counters(self, payload: dict) -> dict:
        message_id = _first(payload, "message_id", "messageId", "id")
        if not message_id:
            return {"ok": True, "ignored": "no_message_id"}
        updates = {}
        mapping = {
            "viewsCount": ("views_count", "viewsCount", "views"),
            "forwardsCount": ("forwards_count", "forwardsCount", "forwards"),
            "reactionsCount": ("reactions_count", "reactionsCount", "reactions"),
        }
        for field, keys in mapping.items():
            value = _first(payload, *keys)
            if isinstance(value, dict):
                value = sum(v for v in value.values() if isinstance(v, (int, float)))
            if isinstance(value, (int, float)):
                updates[field] = int(value)
        if not updates:
            return {"ok": True, "ignored": "no_counters"}
        try:
            record = self.espo.find_channel_post_by_message(str(message_id))
            if not record:
                return {"ok": True, "ignored": "post_not_found"}
            self.espo.update_channel_post(record["id"], updates)
            log.info("counters updated for %s: %s", message_id, updates)
            return {"ok": True, "updated": updates}
        except EspoError as exc:
            self.stats["errors"] += 1
            log.error("counter update failed: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    # -- inbound: EspoCRM --------------------------------------------------
    def handle_espocrm_hook(self, body: dict) -> dict:
        entity_type = body.get("entityType") or body.get("entity_type") or "WhatsAppChannelPost"
        entity_id = body.get("entityId") or body.get("entity_id") or body.get("id")
        if not entity_id:
            return {"ok": False, "error": "entityId required"}
        if entity_type == "WhatsAppChannelPost":
            queued = self.store.enqueue("publish", entity_id, {"postId": entity_id})
            self.drain_outbox()
            return {"ok": True, "queued": queued, "postId": entity_id}
        if entity_type in ("Contact", "Lead"):
            message = body.get("message")
            if not message:
                return {"ok": False, "error": "message required for direct send"}
            try:
                record = self.espo._call("GET", f"/{entity_type}/{entity_id}")
                phone = record.get("phoneNumber")
                if not phone:
                    return {"ok": False, "error": "record has no phoneNumber"}
                self.gowa.send_message(phone, message)
                self.espo.add_stream_note(entity_type, entity_id, f"WhatsApp sent: {message}"[:1500])
                return {"ok": True, "sentTo": phone}
            except (EspoError, GowaError) as exc:
                return {"ok": False, "error": str(exc)[:200]}
        return {"ok": False, "error": f"unsupported entityType {entity_type}"}

    # -- outbound publishing ----------------------------------------------
    def sync_ready_posts(self) -> int:
        try:
            records = self.espo.list_ready_to_publish()
        except EspoError as exc:
            log.error("cannot list ready posts: %s", exc)
            return 0
        queued = 0
        for record in records:
            if self.store.enqueue("publish", record["id"], {"postId": record["id"]}):
                queued += 1
        if queued:
            log.info("queued %d ready post(s)", queued)
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
                    log.warning("publish retry %d for %s: %s", attempts + 1,
                                payload.get("postId"), exc)
        return processed

    def _publish(self, post_id: str) -> None:
        record = self.espo.get_channel_post(post_id)
        status = record.get("status")
        if status != "Ready to Publish":
            log.info("skip %s: status=%s", post_id, status)
            return
        jid = record.get("channelJid")
        if not jid:
            raise ValueError("record has no channelJid")
        text = (record.get("body") or "").strip() or (record.get("name") or "").strip()
        if not text:
            raise ValueError("record has no body/name to publish")
        media_url = (record.get("mediaUrl") or "").strip()
        if media_url:
            text = f"{text}\n{media_url}"
        response = self.gowa.send_message(jid, text)
        results = response.get("results") if isinstance(response.get("results"), dict) else {}
        fields = {
            "status": "Published",
            "publishedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "lastError": None,
        }
        message_id = results.get("message_id") or results.get("id")
        if message_id:
            # Needed to map channel counters (views/forwards/reactions) back.
            fields["messageId"] = message_id
            # Our own posts also come back through the channel feed; mark them
            # seen so the backfill does not create a duplicate CRM record.
            self.store.mark_seen(message_id)
        self.espo.update_channel_post(post_id, fields)
        self.stats["published"] += 1
        log.info("published %s to %s", post_id, jid)

    def _mark_failed(self, post_id: str | None, exc: Exception) -> None:
        if not post_id:
            return
        try:
            self.espo.update_channel_post(post_id, {
                "status": "Failed",
                "lastError": str(exc)[:1000],
            })
        except EspoError:
            log.exception("could not flag post %s as Failed", post_id)

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
        """Map GOWA's /newsletter/messages shape onto the webhook payload shape."""
        return {
            "id": _first(item, "message_id", "id"),
            "chat_id": jid,
            "body": _first(item, "text", "body", "caption", default=""),
            "media_type": _first(item, "media_type", "type", default="none"),
            "timestamp": _first(item, "timestamp", "time", "posted_at"),
            "server_id": _first(item, "server_id", "serverId"),
            "chat_name": _first(item, "channel_name", "newsletter_name", default=""),
        }

    # -- engagement counters ----------------------------------------------
    def sync_counters(self) -> int:
        """Refresh views/forwards/reactions on CRM records from the channel.

        GOWA exposes two shapes: /newsletter/messages carries message_id +
        views_count (but no reactions), while /newsletter/message-updates
        carries reaction_counts keyed by server_id. Join them on server_id.
        """
        updated = 0
        for jid in self.cfg.newsletter_jids:
            try:
                feed_response = self.gowa.newsletter_messages(jid, count=20)
            except GowaError as exc:
                log.warning("counter fetch failed for %s: %s", jid, exc)
                continue
            feed = (feed_response.get("results") or {}).get("data") or []
            server_ids = [i.get("server_id") for i in feed if isinstance(i.get("server_id"), int)]
            # A wide range (after=1) makes WhatsApp scan everything and time out
            # with 504; asking only for the ids we just saw is fast.
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
                record = self.espo.find_channel_post_by_message(message_id)
                if not record:
                    continue
                server_id = item.get("server_id")
                counter = counters.get(server_id) or item
                fields = {}
                if server_id and record.get("serverId") != server_id:
                    fields["serverId"] = server_id
                for field, key in (("viewsCount", "views_count"),
                                   ("forwardsCount", "forwards_count")):
                    value = counter.get(key, item.get(key))
                    if isinstance(value, (int, float)) and int(value) != int(record.get(field) or 0):
                        fields[field] = int(value)
                reactions = counter.get("reaction_counts", item.get("reactions"))
                total = None
                if isinstance(reactions, dict):
                    total = sum(v for v in reactions.values() if isinstance(v, (int, float)))
                elif isinstance(reactions, list):
                    total = len(reactions)
                elif isinstance(reactions, (int, float)):
                    total = int(reactions)
                if total is not None and total != int(record.get("reactionsCount") or 0):
                    fields["reactionsCount"] = int(total)
                if fields:
                    try:
                        self.espo.update_channel_post(record["id"], fields)
                        updated += 1
                        log.info("counters updated for %s: %s", message_id, fields)
                    except EspoError as exc:
                        log.warning("counter update failed for %s: %s", message_id, exc)
        return updated

    # -- diagnostics -------------------------------------------------------
    def health(self) -> dict:
        gowa_ok = True
        try:
            self.gowa.device_status()
        except GowaError:
            gowa_ok = False
        return {
            "ok": gowa_ok and bool(self.cfg.espo_api_key),
            "gowa": gowa_ok,
            "espocrm": self.espo.ping(),
            "queue": self.store.pending_count(),
            "stats": dict(self.stats),
            "monitoredChannels": list(self.cfg.newsletter_jids),
        }
