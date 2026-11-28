"""Agent tokens may draft, never approve or schedule."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crm import CrmClient  # noqa: E402
from mcp import McpServer  # noqa: E402
from store import Store  # noqa: E402


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)
        self.server = McpServer(self.crm, None, self.store, None, can_publish=False,
                                cfg=SimpleNamespace(newsletter_jids=("120363@newsletter",)))
        self.post = self.crm.create_channel_post({
            "channel_jid": "120363@newsletter", "title": "مسودة", "body": "نص",
            "status": "draft"})

    def tearDown(self):
        self.store.close()

    def call(self, name, args, caller):
        return self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": args}}, caller=caller)["result"]

    def test_agent_cannot_approve_a_plan(self):
        result = self.call("crm_approve_plan", {"plan_id": "x"}, caller="agent")
        self.assertTrue(result["isError"])
        self.assertIn("human-only", result["content"][0]["text"])

    def test_agent_cannot_schedule_a_post(self):
        result = self.call("content_schedule",
                           {"id": self.post["id"], "at": "2030-01-01T10:00:00"}, caller="agent")
        self.assertTrue(result["isError"])
        self.assertIn("human-only", result["content"][0]["text"])

    def test_agent_cannot_flip_a_draft_to_scheduled(self):
        result = self.call("crm_update_channel_post",
                           {"id": self.post["id"], "status": "scheduled"}, caller="agent")
        self.assertTrue(result["isError"])
        self.assertIn("human-only", result["content"][0]["text"])

    def test_agent_may_still_draft_and_read(self):
        draft = self.call("crm_create_channel_post",
                          {"channelJid": "120363@newsletter", "title": "عنوان",
                           "body": "نص", "status": "draft"}, caller="agent")
        self.assertFalse(draft.get("isError", False))
        brief = self.call("crm_editorial_brief", {}, caller="agent")
        self.assertFalse(brief.get("isError", False))
        self.assertIn("channel", brief["content"][0]["text"])

    def test_human_path_is_not_blocked(self):
        result = self.call("crm_approve_plan", {"plan_id": "missing"}, caller="human")
        text = result["content"][0]["text"]
        self.assertNotIn("human-only", text)


if __name__ == "__main__":
    unittest.main()
