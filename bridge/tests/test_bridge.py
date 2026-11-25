import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import service
from config import Config
from gowa import GowaError, verify_signature
from service import Bridge, jid_to_phone, media_type_for, subject_for, to_espo_datetime
from store import Store


class FakeEspo:
    def __init__(self):
        self.contacts, self.posts, self.notes = {}, {}, []
        self._seq = 0

    def _id(self, prefix):
        self._seq += 1
        return f"{prefix}{self._seq}"

    def find_contact_by_phone(self, phone):
        return self.contacts.get(phone)

    def create_contact(self, phone, first_name="", last_name=""):
        rec = {"id": self._id("c"), "phoneNumber": phone, "firstName": first_name}
        self.contacts[phone] = rec
        return rec

    def add_stream_note(self, entity_type, entity_id, text):
        self.notes.append((entity_type, entity_id, text))
        return {"id": "n1", "type": "Post"}

    def create_channel_post(self, fields):
        rec = dict(fields, id=self._id("p"))
        self.posts[rec["id"]] = rec
        return rec

    def find_channel_post_by_message(self, message_id):
        for rec in self.posts.values():
            if rec.get("messageId") == message_id:
                return rec
        return None

    def get_channel_post(self, post_id):
        return self.posts[post_id]

    def update_channel_post(self, post_id, fields):
        self.posts[post_id].update(fields)
        return self.posts[post_id]

    def list_ready_to_publish(self, limit=10):
        return [r for r in self.posts.values() if r.get("status") == "Ready to Publish"][:limit]

    def ping(self):
        return True


class FakeGowa:
    def __init__(self, fail_times=0):
        self.sent, self.fail_times = [], fail_times
        self.subscribed = []

    def send_message(self, phone, message):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise GowaError(500, "temporary failure", "/send/message")
        self.sent.append((phone, message))
        return {"code": "SUCCESS", "results": {"message_id": "3EB0TEST" + str(len(self.sent))}}

    def subscribe_live_updates(self, jid):
        self.subscribed.append(jid)
        return {"code": "SUCCESS"}

    def newsletter_messages(self, jid, count=20):
        return {"results": {"data": []}}

    def newsletter_message_updates(self, jid, after=1, count=100):
        return {"results": {"data": []}}

    def device_status(self):
        return {"code": "SUCCESS"}


def cfg_for(tmp):
    return Config(
        gowa_base_url="http://127.0.0.1:3000", gowa_device_id="primary",
        gowa_webhook_secret="s3cret",
        bridge_host="127.0.0.1", bridge_port=8085, bridge_token="tok",
        espo_base_url="http://127.0.0.1:8081", espo_api_key="key", espo_user="wa-bridge",
        newsletter_jids=(), default_country_code="966",
        db_path=os.path.join(tmp, "bridge.db"), poll_interval=60,
        channel_sync_interval=300, log_level="INFO",
    )


class HelperTests(unittest.TestCase):
    def test_jid_to_phone(self):
        self.assertEqual(jid_to_phone("966501234567@s.whatsapp.net"), "+966501234567")
        self.assertEqual(jid_to_phone("966501234567:12@s.whatsapp.net"), "+966501234567")
        self.assertIsNone(jid_to_phone("1203630@newsletter"))
        self.assertIsNone(jid_to_phone("123@s.whatsapp.net"))

    def test_datetime(self):
        self.assertEqual(to_espo_datetime("2023-10-15T10:30:00Z"), "2023-10-15 10:30:00")
        self.assertEqual(to_espo_datetime(1700000000), "2023-11-14 22:13:20")
        self.assertIsNone(to_espo_datetime("not-a-date"))
        self.assertIsNone(to_espo_datetime(None))

    def test_subject_and_media(self):
        self.assertEqual(subject_for({"body": "hello\nworld"}), "hello world")
        self.assertIn("image", subject_for({"media_type": "image"}))
        self.assertEqual(media_type_for({"media_type": "imageMessage"}), "image")
        self.assertEqual(media_type_for({}), "none")

    def test_signature(self):
        body = b'{"event":"message"}'
        good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature("s3cret", body, good))
        self.assertFalse(verify_signature("s3cret", body, good[:-2] + "00"))
        self.assertFalse(verify_signature("s3cret", body, None))
        self.assertFalse(verify_signature("", body, good))


class StoreTests(unittest.TestCase):
    def test_idempotency_and_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(os.path.join(tmp, "s.db"))
            self.assertFalse(store.seen("m1"))
            store.mark_seen("m1")
            self.assertTrue(store.seen("m1"))
            self.assertTrue(store.enqueue("publish", "p1", {"postId": "p1"}))
            self.assertFalse(store.enqueue("publish", "p1", {"postId": "p1"}))  # dedupe
            self.assertEqual(store.pending_count(), 1)
            items = store.due()
            self.assertEqual(len(items), 1)
            store.finish(items[0]["id"], status="done")
            self.assertEqual(store.pending_count(), 0)
            store.close()


class InboundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = cfg_for(self.tmp.name)
        self.espo, self.gowa = FakeEspo(), FakeGowa()
        self.bridge = Bridge(self.cfg, espo=self.espo, gowa=self.gowa)

    def tearDown(self):
        self.bridge.store.close()
        self.tmp.cleanup()

    def test_dm_creates_contact_and_stream_note(self):
        result = self.bridge.handle_gowa_event({
            "event": "message",
            "payload": {"id": "m1", "chat_id": "966501234567@s.whatsapp.net",
                        "from": "966501234567@s.whatsapp.net", "body": "مرحبا",
                        "is_from_me": False, "sender_display_name": "أحمد",
                        "timestamp": "2026-11-25T10:00:00Z"},
        })
        self.assertTrue(result["ok"])
        self.assertTrue(result["created"])
        self.assertEqual(len(self.espo.notes), 1)
        self.assertIn("مرحبا", self.espo.notes[0][2])
        # duplicate delivery is idempotent
        again = self.bridge.handle_gowa_event({
            "event": "message",
            "payload": {"id": "m1", "chat_id": "966501234567@s.whatsapp.net",
                        "from": "966501234567@s.whatsapp.net", "body": "مرحبا"},
        })
        self.assertEqual(again.get("ignored"), "duplicate")

    def test_existing_contact_reused(self):
        self.espo.create_contact("+966500000002", first_name="موجود")
        result = self.bridge.handle_gowa_event({
            "event": "message",
            "payload": {"id": "m2", "chat_id": "966500000002@s.whatsapp.net",
                        "from": "966500000002@s.whatsapp.net", "body": "ثاني"},
        })
        self.assertFalse(result["created"])
        self.assertEqual(len(self.espo.contacts), 1)

    def test_channel_post_stored(self):
        result = self.bridge.handle_gowa_event({
            "event": "message",
            "payload": {"id": "ch1", "chat_id": "120363000000000000@newsletter",
                        "body": "منشور جديد", "timestamp": "2026-11-25T11:00:00Z",
                        "media_type": "image"},
        })
        self.assertTrue(result["ok"])
        post = self.espo.posts[result["postId"]]
        self.assertEqual(post["channelJid"], "120363000000000000@newsletter")
        self.assertEqual(post["mediaType"], "image")
        self.assertEqual(post["status"], "New")
        self.assertEqual(post["postedAt"], "2026-11-25 11:00:00")

    def test_group_messages_ignored(self):
        result = self.bridge.handle_gowa_event({
            "event": "message",
            "payload": {"id": "g1", "chat_id": "1203630-123@g.us", "body": "hi"},
        })
        self.assertEqual(result.get("ignored"), "chat_type")

    def test_counters_updated(self):
        rec = self.espo.create_channel_post({
            "name": "x", "channelJid": "1203630@newsletter", "messageId": "ch9", "status": "New"})
        result = self.bridge.handle_gowa_event({
            "event": "newsletter.message",
            "payload": {"message_id": "ch9", "views_count": 150, "forwards_count": 7,
                        "reactions": {"👍": 3, "❤️": 2}},
        })
        self.assertTrue(result["ok"])
        self.assertEqual(self.espo.posts[rec["id"]]["viewsCount"], 150)
        self.assertEqual(self.espo.posts[rec["id"]]["forwardsCount"], 7)
        self.assertEqual(self.espo.posts[rec["id"]]["reactionsCount"], 5)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = cfg_for(self.tmp.name)
        self.espo = FakeEspo()
        self.gowa = FakeGowa()
        self.bridge = Bridge(self.cfg, espo=self.espo, gowa=self.gowa)
        self.post = self.espo.create_channel_post({
            "name": "إعلان", "channelJid": "1203630@newsletter", "body": "نص المنشور",
            "messageId": "ch2", "status": "Ready to Publish"})

    def tearDown(self):
        self.bridge.store.close()
        self.tmp.cleanup()

    def test_ready_post_is_published(self):
        self.bridge.handle_espocrm_hook({"entityType": "WhatsAppChannelPost",
                                         "entityId": self.post["id"]})
        self.assertEqual(self.gowa.sent, [("1203630@newsletter", "نص المنشور")])
        self.assertEqual(self.espo.posts[self.post["id"]]["status"], "Published")
        self.assertIsNotNone(self.espo.posts[self.post["id"]]["publishedAt"])

    def test_not_ready_is_not_sent(self):
        self.espo.update_channel_post(self.post["id"], {"status": "New"})
        self.bridge.handle_espocrm_hook({"entityType": "WhatsAppChannelPost",
                                         "entityId": self.post["id"]})
        self.assertEqual(self.gowa.sent, [])

    def test_failure_marks_failed_after_retries(self):
        service.BACKOFF_STEP = 0
        self.gowa.fail_times = service.MAX_ATTEMPTS
        self.bridge.handle_espocrm_hook({"entityType": "WhatsAppChannelPost",
                                         "entityId": self.post["id"]})
        for _ in range(service.MAX_ATTEMPTS):
            self.bridge.drain_outbox()
        self.assertEqual(self.espo.posts[self.post["id"]]["status"], "Failed")
        self.assertIn("temporary failure", self.espo.posts[self.post["id"]]["lastError"])

    def test_transient_failure_recovers(self):
        service.BACKOFF_STEP = 0
        self.gowa.fail_times = 1
        self.bridge.handle_espocrm_hook({"entityType": "WhatsAppChannelPost",
                                         "entityId": self.post["id"]})
        self.bridge.drain_outbox()
        self.assertEqual(self.gowa.sent, [("1203630@newsletter", "نص المنشور")])
        self.assertEqual(self.espo.posts[self.post["id"]]["status"], "Published")


class ChannelSyncTests(unittest.TestCase):
    def test_sync_stores_messages_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfg_for(tmp)
            cfg = Config(**{**cfg.__dict__, "newsletter_jids": ("1203630@newsletter",)})
            espo, gowa = FakeEspo(), FakeGowa()
            gowa.newsletter_messages = lambda jid, count=20: {"results": {"messages": [
                {"message_id": "s1", "text": "من القناة", "timestamp": 1700000000,
                 "media_type": "none"}]}}
            bridge = Bridge(cfg, espo=espo, gowa=gowa)
            self.assertEqual(bridge.sync_channels(), 1)
            self.assertEqual(bridge.sync_channels(), 0)  # idempotent
            self.assertEqual(gowa.subscribed, ["1203630@newsletter"] * 2)
            bridge.store.close()


if __name__ == "__main__":
    unittest.main()


class ContactPayloadTests(unittest.TestCase):
    def test_split_name_always_fills_last_name(self):
        from espocrm import EspoClient
        self.assertEqual(EspoClient.split_name("أحمد علي", "+1"), ("أحمد", "علي"))
        self.assertEqual(EspoClient.split_name("أحمد", "+1"), ("", "أحمد"))
        self.assertEqual(EspoClient.split_name("", "+966500"), ("", "+966500"))

    def test_create_contact_payload_has_last_name(self):
        from espocrm import EspoClient

        class Capture(EspoClient):
            def __init__(self):
                super().__init__("http://x", "k")
                self.payload = None

            def _call(self, method, path, payload=None, params=None):
                self.payload = payload
                return {"id": "c1"}

        client = Capture()
        client.create_contact("+966500000000", first_name="أحمد علي")
        self.assertTrue(client.payload["lastName"])
        self.assertEqual(client.payload["firstName"], "أحمد")


class CounterSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = cfg_for(self.tmp.name)
        self.cfg = Config(**{**cfg.__dict__, "newsletter_jids": ("1203630@newsletter",)})
        self.espo, self.gowa = FakeEspo(), FakeGowa()
        self.bridge = Bridge(self.cfg, espo=self.espo, gowa=self.gowa)
        self.post = self.espo.create_channel_post({
            "name": "x", "channelJid": "1203630@newsletter",
            "messageId": "CH1", "status": "New"})

    def tearDown(self):
        self.bridge.store.close()
        self.tmp.cleanup()

    def test_counters_written_to_record(self):
        self.gowa.newsletter_messages = lambda jid, count=20: {"results": {"data": [
            {"message_id": "CH1", "server_id": 7, "views_count": 42, "forwards_count": 3}]}}
        self.gowa.newsletter_message_updates = lambda jid, after=1, count=100: {"results": {"data": [
            {"server_id": 7, "views_count": 42, "forwards_count": 3,
             "reaction_counts": {"👍": 2, "❤️": 1}}]}}
        updated = self.bridge.sync_counters()
        self.assertEqual(updated, 1)
        rec = self.espo.posts[self.post["id"]]
        self.assertEqual(rec["viewsCount"], 42)
        self.assertEqual(rec["forwardsCount"], 3)
        self.assertEqual(rec["reactionsCount"], 3)

    def test_unknown_message_is_ignored(self):
        self.gowa.newsletter_messages = lambda jid, count=20: {"results": {"data": [
            {"message_id": "NOPE", "server_id": 9, "views_count": 9}]}}
        self.assertEqual(self.bridge.sync_counters(), 0)

    def test_publish_records_message_id(self):
        self.espo.update_channel_post(self.post["id"], {"status": "Ready to Publish"})
        self.bridge.handle_espocrm_hook({"entityType": "WhatsAppChannelPost",
                                         "entityId": self.post["id"]})
        rec = self.espo.posts[self.post["id"]]
        self.assertEqual(rec["status"], "Published")
        self.assertTrue(rec.get("messageId"))
