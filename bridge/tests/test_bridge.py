
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from crm import CrmClient
from service import Bridge, jid_to_phone, to_epoch
from store import Store


class FakeGowa:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_message(self, to, message):
        if self.fail:
            raise RuntimeError("gateway down")
        self.sent.append((to, message))
        return {"code": "SUCCESS", "results": {"message_id": f"MID{len(self.sent)}"}}

    def device_status(self):
        return {"state": "connected"}

    def newsletter_messages(self, jid, count=20):
        return {"results": {"data": []}}

    def newsletter_message_updates(self, jid, after=1, count=20):
        return {"results": {"data": []}}

    def subscribe_live_updates(self, jid):
        return {"ok": True}


def make_config(tmp):
    return Config(
        gowa_base_url="http://127.0.0.1:3000", gowa_device_id="primary",
        gowa_webhook_secret="secret", bridge_host="127.0.0.1", bridge_port=0,
        bridge_token="tok", newsletter_jids=("1203630@newsletter",),
        default_country_code="966", db_path=os.path.join(tmp, "crm.db"),
        poll_interval=60, channel_sync_interval=300, log_level="INFO",
        agent_can_publish=False, daily_publish_cap=30,
    )


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = make_config(self.tmp)
        self.store = Store(self.cfg.db_path)
        self.crm = CrmClient(self.store)
        self.gowa = FakeGowa()
        self.bridge = Bridge(self.cfg, crm=self.crm, gowa=self.gowa, store=self.store)

    def tearDown(self):
        self.store.close()

    def test_jid_helpers(self):
        self.assertEqual(jid_to_phone("966500000000@s.whatsapp.net", "966"), "+966500000000")
        self.assertIsNone(jid_to_phone("1203630@newsletter"))
        self.assertIsNotNone(to_epoch("2026-11-27T18:30:00+03:00"))

    def test_inbound_dm_creates_contact_and_message(self):
        res = self.bridge.handle_gowa_event({"event": "message", "payload": {
            "id": "m1", "chat_id": "966500000000@s.whatsapp.net",
            "from": "966500000000@s.whatsapp.net", "body": "السلام عليكم",
            "timestamp": "2026-11-26T10:00:00Z", "is_from_me": False}})
        self.assertTrue(res["ok"])
        contact = self.crm.find_contact_by_phone("+966500000000")
        self.assertIsNotNone(contact)
        self.assertEqual(self.crm.unread_count(), 1)

    def test_inbound_channel_post_is_archived_as_published(self):
        res = self.bridge.handle_gowa_event({"event": "message", "payload": {
            "id": "cp1", "chat_id": "1203630@newsletter", "body": "منشور قديم",
            "timestamp": 1700000000, "is_from_me": True}})
        self.assertTrue(res["ok"])
        posts = self.crm.list_posts("published")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["message_id"], "cp1")

    def test_counters_update(self):
        self.bridge.handle_gowa_event({"event": "message", "payload": {
            "id": "cp2", "chat_id": "1203630@newsletter", "body": "x", "timestamp": 1700000000}})
        self.bridge.handle_gowa_event({"event": "newsletter.message", "payload": {
            "message_id": "cp2", "views_count": 42, "forwards_count": 3}})
        posts = self.crm.list_posts("published")
        self.assertEqual(posts[0]["views"], 42)

    def test_publish_flow_end_to_end(self):
        post = self.crm.create_channel_post({
            "channel_jid": "1203630@newsletter", "body": "منشور جديد"})
        self.crm.schedule_post(post["id"], 1, approved=True)
        self.assertEqual(self.bridge.sync_ready_posts(), 1)
        self.bridge.drain_outbox()
        row = self.crm.get_channel_post(post["id"])
        self.assertEqual(row["status"], "published")
        self.assertTrue(row["message_id"].startswith("MID"))
        self.assertEqual(len(self.gowa.sent), 1)

    def test_failed_publish_returns_to_queue(self):
        self.gowa.fail = True
        post = self.crm.create_channel_post({
            "channel_jid": "1203630@newsletter", "body": "سيفشل"})
        self.crm.schedule_post(post["id"], 1, approved=True)
        self.bridge.sync_ready_posts()
        self.bridge.drain_outbox()
        row = self.crm.get_channel_post(post["id"])
        self.assertEqual(row["status"], "scheduled")
        self.assertIsNone(row["message_id"])
        self.assertEqual(self.store.pending_count(), 1)


if __name__ == "__main__":
    unittest.main()
