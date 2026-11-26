
import os, sys, tempfile, unittest

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
