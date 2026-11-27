
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crm import CrmClient
from store import Store


class CrmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)

    def tearDown(self):
        self.store.close()

    def test_post_lifecycle(self):
        post = self.crm.create_channel_post({
            "channel_jid": "1203630@newsletter", "title": "t", "body": "hello"})
        self.assertEqual(post["status"], "draft")

        # agent proposal (not approved) -> stays draft with a proposed time
        self.crm.schedule_post(post["id"], 1000, approved=False)
        self.assertEqual(self.crm.get_channel_post(post["id"])["status"], "draft")
        self.assertEqual(self.crm.due_posts(), [])

        # human approval -> scheduled and due
        self.crm.schedule_post(post["id"], 1, approved=True)
        due = self.crm.due_posts()
        self.assertEqual(len(due), 1)
        self.assertTrue(self.crm.claim_post(post["id"]))
        self.crm.mark_published(post["id"], "MID1")
        row = self.crm.get_channel_post(post["id"])
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["message_id"], "MID1")

    def test_delete_rules(self):
        """Drafts and cancelled items can be deleted; scheduled/published cannot."""
        draft = self.crm.create_channel_post({
            "channel_jid": "1203630@newsletter", "title": "d", "body": "x"})
        self.crm.delete_post(draft["id"])
        self.assertIsNone(self.crm.get_channel_post(draft["id"]))

        scheduled = self.crm.create_channel_post({
            "channel_jid": "1203630@newsletter", "title": "s", "body": "x"})
        self.crm.schedule_post(scheduled["id"], 9999999999, approved=True)
        with self.assertRaises(PermissionError):
            self.crm.delete_post(scheduled["id"])

        self.crm.cancel_post(scheduled["id"])
        self.crm.delete_post(scheduled["id"])  # cancelled -> deletable
        self.assertIsNone(self.crm.get_channel_post(scheduled["id"]))

    def test_content_insights(self):
        now = int(__import__("time").time())
        for kind, views, forwards, reactions, hour in (
                ("text", 100, 10, 5, 9), ("text", 50, 0, 0, 10), ("video", 300, 30, 15, 21)):
            post = self.crm.create_channel_post(
                {"channel_jid": "1@newsletter", "body": f"b{hour}", "media_type": kind})
            self.crm.update_channel_post(post["id"], {
                "status": "published", "published_at": now - 4 * 86400 + hour * 3600,
                "message_id": f"M{hour}"})
            self.crm.update_counters(post["id"], views, forwards, reactions)
        insights = self.crm.content_insights(30)
        self.assertEqual(insights["posts"], 3)
        self.assertEqual(insights["total"]["views"], 450)
        self.assertEqual(insights["by_type"]["video"]["avg_views"], 300.0)
        self.assertEqual(insights["by_type"]["text"]["posts"], 2)
        self.assertEqual(insights["top"][0]["views"], 300)
        self.assertEqual(insights["bottom"][0]["views"], 50)

        times = self.crm.posting_times(30, tz_offset=0)
        self.assertEqual(times["buckets"], 3)
        self.assertEqual(times["best"][0]["avg_views"], 300.0)
        self.assertGreaterEqual(times["best"][0]["avg_views"], times["best"][-1]["avg_views"])

    def test_status_guard(self):
        post = self.crm.create_channel_post({"channel_jid": "1@newsletter", "body": "x"})
        with self.assertRaises(PermissionError):
            self.crm.update_channel_post(post["id"], {"status": "published"},
                                         allowed_statuses=("idea", "draft", "review"))

    def test_contacts_and_followups(self):
        c = self.crm.upsert_contact("+966500000000", name="أحمد")
        self.assertEqual(c["name"], "أحمد")
        self.crm.add_message(c["id"], "in", "مرحبا")
        self.assertEqual(self.crm.unread_count(), 1)
        self.crm.add_activity(c["id"], "task", "اتصل به", due_at=1)
        due = self.crm.followups(0)
        self.assertEqual(len(due), 1)
        self.crm.complete_activity(due[0]["id"])
        self.assertEqual(self.crm.followups(0), [])

    def test_metrics(self):
        post = self.crm.create_channel_post({"channel_jid": "1@newsletter", "body": "x"})
        self.crm.schedule_post(post["id"], 1, approved=True)
        self.crm.claim_post(post["id"])
        self.crm.mark_published(post["id"], "M2")
        self.crm.update_counters(post["id"], 100, 5, 3, server_id=77)
        m = self.crm.channel_metrics(7)
        self.assertEqual(m["total"]["views"], 100)
        self.assertEqual(m["total"]["forwards"], 5)


if __name__ == "__main__":
    unittest.main()
