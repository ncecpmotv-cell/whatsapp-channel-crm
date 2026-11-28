"""Fast context tools: the inbox query and the single-post pack."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crm import CrmClient  # noqa: E402
from store import Store  # noqa: E402


class PackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)

    def tearDown(self):
        self.store.close()

    def test_inbox_returns_unread_with_contact_context(self):
        contact = self.crm.create_contact("966500000000", first_name="سارة")
        self.crm.add_message(contact["id"], "in", "هل عندكم عرض للشتاء؟")
        self.crm.add_message(contact["id"], "in", "رسالة قديمة", read=True)
        rows = self.crm.inbox(10)
        self.assertEqual(len(rows), 1)
        self.assertIn("عرض", rows[0]["body"])
        self.assertIn("سارة", rows[0]["contact_name"])
        self.assertEqual(rows[0]["phone"], "966500000000")
        every = self.crm.inbox(10, unread_only=False)
        self.assertEqual(len(every), 2)

    def test_post_pack_bundles_metrics_lint_and_brand(self):
        post = self.crm.create_channel_post({
            "channel_jid": "1@newsletter", "title": "أربع قواعد لصورة منتج تبيع",
            "body": "نص", "status": "draft", "media_type": "image"})
        self.crm.update_channel_post(post["id"], {"views": 12})
        pack = self.crm.post_pack(post["id"])
        self.assertEqual(pack["views"], 12)
        self.assertEqual(pack["brand_version"], self.crm.get_brand()["version"])
        self.assertIn("visual_brief_missing", {i["code"] for i in pack["lint"]})
        self.assertIsInstance(pack["similar"], list)

    def test_post_pack_refuses_a_missing_post(self):
        with self.assertRaises(ValueError):
            self.crm.post_pack("nope")


if __name__ == "__main__":
    unittest.main()
