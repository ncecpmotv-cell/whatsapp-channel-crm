"""Radar on the phone: novelty, storage, dedupe, and angle → draft."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import edge  # noqa: E402
import radar  # noqa: E402
from crm import CrmClient, _tokens  # noqa: E402
from store import Store  # noqa: E402


class FakeEdge:
    def __init__(self, items):
        self.items = items
        self.summary_calls = 0

    def enabled(self):
        return True

    def radar(self):
        return {"items": self.items, "fetchedAt": "2026-11-28T00:00:00Z"}

    def radar_summarize(self, titles):
        self.summary_calls += 1
        return {"angles": [{"i": 0, "angle": "لماذا هذا يهم جمهورك؟"}]}


class RadarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)
        self.cfg = SimpleNamespace(edge_url="https://edge.test", edge_token="t",
                                   newsletter_jids=("120363409750144525@newsletter",))
        self.original = edge.from_config

    def tearDown(self):
        edge.from_config = self.original
        self.store.close()

    def test_novelty_is_zero_for_a_near_duplicate(self):
        tokens = set(_tokens("أربع قواعد لصورة منتج تبيع"))
        self.assertGreater(radar.novelty(tokens, []), 0.99)
        same = set(_tokens("أربع قواعد لصورة منتج تبيع"))
        self.assertLess(radar.novelty(tokens, [same]), 0.05)
        other = set(_tokens("ميزانية التسويق في الأزمات"))
        self.assertGreater(radar.novelty(tokens, [other]), 0.8)

    def test_scan_stores_new_angles_and_never_duplicates(self):
        fake = FakeEdge([
            {"id": "a1", "title": "خبر جديد عن التسويق بالمحتوى", "url": "https://ex.test/1",
             "source": "ex.test", "published": ""},
            {"id": "a2", "title": "موضوع آخر تمامًا", "url": "https://ex.test/2",
             "source": "ex.test", "published": ""},
        ])
        edge.from_config = lambda cfg: fake
        first = radar.scan(self.crm, self.cfg, summarize=False)
        self.assertEqual(first["stored"], 2)
        self.assertEqual(fake.summary_calls, 0)
        second = radar.scan(self.crm, self.cfg, summarize=False)
        self.assertEqual(second["stored"], 0)
        self.assertEqual(self.crm.count_angles(), 2)

    def test_summarize_costs_exactly_one_call(self):
        fake = FakeEdge([
            {"id": f"a{i}", "title": f"عنوان رقم {i}", "url": f"https://ex.test/{i}",
             "source": "ex.test", "published": ""} for i in range(4)
        ])
        edge.from_config = lambda cfg: fake
        result = radar.scan(self.crm, self.cfg, summarize=True)
        self.assertTrue(result["summarized"])
        self.assertEqual(fake.summary_calls, 1)
        stored = self.crm.list_angles("new", 10)
        self.assertTrue(any(row["angle"] for row in stored))

    def test_disabled_edge_degrades_quietly(self):
        edge.from_config = lambda cfg: SimpleNamespace(enabled=lambda: False)
        result = radar.scan(self.crm, self.cfg)
        self.assertFalse(result["ok"])
        self.assertIn("edge", result["error"])

    def test_angle_becomes_a_draft(self):
        self.crm.add_angle({"id": "x1", "title": "خبر", "url": "https://ex.test/x",
                            "angle": "زاوية مقترحة", "score": 0.9})
        row = self.crm.list_angles("new", 1)[0]
        post = self.crm.create_channel_post({
            "channel_jid": self.cfg.newsletter_jids[0], "title": row["angle"],
            "body": f"{row['angle']}\n\nالمصدر: {row['url']}", "status": "draft",
        })
        updated = self.crm.set_angle_status(row["id"], "used", post["id"])
        self.assertEqual(updated["status"], "used")
        self.assertEqual(updated["post_id"], post["id"])
        self.assertEqual(post["status"], "draft")


if __name__ == "__main__":
    unittest.main()
