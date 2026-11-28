"""The orchestrator: intent → compact execution pack, and the capability matrix."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import orchestrator  # noqa: E402
from crm import CrmClient  # noqa: E402
from store import Store  # noqa: E402


class OrchestratorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)

    def tearDown(self):
        self.store.close()

    def test_intent_is_classified_deterministically(self):
        cases = {
            "وش في الوارد؟": "reply",
            "أبي خطة أسبوع": "plan",
            "تحليل الأرقام": "analyze",
            "كيف ينتشر المحتوى؟": "visibility",
            "نطلق منتجًا": "launch",
            "وزّع على لينكدإن": "distribute",
            "اكتب مسودة": "write",
        }
        for idea, mode in cases.items():
            self.assertEqual(orchestrator.classify(idea), mode, idea)

    def test_pack_is_compact_and_actionable(self):
        pack = orchestrator.build(self.crm, "عندي فكرة عن سلسلة منتجات تجميل")
        self.assertTrue(pack["ok"])
        self.assertEqual(pack["mode"], "plan")
        self.assertTrue(pack["skills"])
        self.assertLessEqual(len(pack["steps"]), 4)
        self.assertIn("brief", pack)
        self.assertIn("guards", pack)
        self.assertLessEqual(pack["budget"]["model_calls"], 3)
        self.assertEqual(pack["note"], "نفّذ الخطوات بالترتيب، ولا تعد قراءة ما في هذا الموجز.")

    def test_each_build_is_recorded(self):
        orchestrator.build(self.crm, "وش في الوارد؟")
        runs = self.crm.list_runs(5)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["mode"], "reply")

    def test_capabilities_reads_the_agent_home(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "skills", "alpha"))
        with open(os.path.join(home, "skills", "alpha", "SKILL.md"), "w") as handle:
            handle.write("---\nname: alpha\ndescription: x\n---\n")
        os.makedirs(os.path.join(home, "workspace", "cron"))
        with open(os.path.join(home, "workspace", "cron", "jobs.json"), "w") as handle:
            json.dump({"jobs": [{"name": "weekly", "schedule": {"expr": "0 10 * * 1"},
                                 "enabled": True}]}, handle)
        with open(os.path.join(home, "config.json"), "w") as handle:
            json.dump({"tools": {"mcp": {"servers": {
                "crm": {"url": "http://127.0.0.1:8085/mcp", "enabled": True}}}}}, handle)
        caps = orchestrator.capabilities(self.crm, home, tools_count=42)
        self.assertEqual(caps["tools"]["count"], 42)
        self.assertIn("alpha", caps["skills"]["names"])
        self.assertTrue(caps["mcp"]["crm"]["enabled"])
        self.assertEqual(caps["cron"][0]["schedule"], "0 10 * * 1")


if __name__ == "__main__":
    unittest.main()
