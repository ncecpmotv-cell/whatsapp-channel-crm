
import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crm import CrmClient
from mcp import McpServer
from store import Store
from test_bridge import FakeGowa


class McpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)
        self.server = McpServer(self.crm, FakeGowa(), self.store, None, can_publish=False)

    def tearDown(self):
        self.store.close()

    def call(self, method, params=None):
        return self.server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})

    def tool(self, name, args):
        res = self.call("tools/call", {"name": name, "arguments": args})
        return res["result"]

    def test_initialize_and_tools(self):
        res = self.call("initialize", {"protocolVersion": "2025-06-18"})
        self.assertEqual(res["result"]["protocolVersion"], "2025-06-18")
        names = {t["name"] for t in self.call("tools/list")["result"]["tools"]}
        for expected in ("crm_search", "crm_create_channel_post", "wa_send", "bridge_health",
                         "content_schedule", "channel_metrics", "contact_upsert", "deal_update",
                         "followups_due"):
            self.assertIn(expected, names)

    def test_agent_cannot_publish(self):
        created = self.tool("crm_create_channel_post", {
            "name": "t", "channelJid": "1@newsletter", "body": "x", "status": "published"})
        post_id = json.loads(created["content"][0]["text"])["id"]
        self.assertEqual(self.crm.get_channel_post(post_id)["status"], "draft")

        sched = self.tool("content_schedule", {"id": post_id, "at": "2030-01-01T10:00:00+03:00"})
        self.assertFalse(sched["isError"])
        self.assertEqual(self.crm.get_channel_post(post_id)["status"], "draft")

        bad = self.tool("crm_update_channel_post", {"id": post_id, "status": "scheduled"})
        self.assertTrue(bad["isError"])

    def test_wa_send(self):
        res = self.tool("wa_send", {"to": "+966500000000", "message": "hi"})
        self.assertFalse(res["isError"])

    def test_contact_and_deal(self):
        c = self.tool("contact_upsert", {"phone": "+966511111111", "name": "سارة"})
        self.assertFalse(c["isError"])
        d = self.tool("deal_update", {"contact_phone": "+966511111111", "title": "تصوير",
                                      "value": 5000, "stage": "contacted"})
        self.assertFalse(d["isError"])
        self.assertEqual(len(self.crm.list_deals()), 1)


if __name__ == "__main__":
    unittest.main()
