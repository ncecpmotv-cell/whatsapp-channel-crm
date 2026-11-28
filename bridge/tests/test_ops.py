"""Operations: backups, watchdog, growth snapshots, variants and the daily brief."""
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backup  # noqa: E402
import digest  # noqa: E402
import watchdog  # noqa: E402
from crm import CrmClient  # noqa: E402
from store import Store  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store, media_dir=os.path.join(self.tmp, "media"))

    def tearDown(self):
        self.store.close()

    def published(self, title, views=10, at=None, kind="none"):
        post = self.crm.create_channel_post({"channel_jid": "1@newsletter", "title": title,
                                             "body": "س", "media_type": kind})
        self.crm.mark_published(post["id"], "MID-" + post["id"])
        self.store.conn.execute("UPDATE crm_posts SET views=?, published_at=? WHERE id=?",
                                (views, at or int(time.time()) - 3600, post["id"]))
        self.store.conn.commit()
        return post["id"]


class BackupTest(Base):
    def test_backup_verifies_and_restores(self):
        self.published("منشور", 5)
        result = backup.make_backup(os.path.join(self.tmp, "t.db"), self.crm.media_dir,
                                    os.path.join(self.tmp, "backups"), keep=2)
        self.assertTrue(result["verified"])
        self.assertEqual(result["posts"], 1)

        # mutate, then restore the archive over the live db
        self.crm.create_channel_post({"channel_jid": "1@newsletter", "title": "جديد"})
        self.store.close()  # restore is an offline operation: close the writer first
        restored = backup.restore(result["archive"], os.path.join(self.tmp, "t.db"),
                                  self.crm.media_dir)
        self.assertTrue(restored["restored"])
        self.store.close()  # a restore replaces the file; reopen to see it
        self.store = Store(os.path.join(self.tmp, "t.db"))
        count = self.store.conn.execute("SELECT COUNT(*) FROM crm_posts").fetchone()[0]
        self.assertEqual(count, 1)

    def test_rotation_keeps_the_newest(self):
        for i in range(4):
            backup.make_backup(os.path.join(self.tmp, "t.db"), self.crm.media_dir,
                               os.path.join(self.tmp, "backups"), keep=2,
                               now=time.time() - i * 3600)
        names = [n for n in os.listdir(os.path.join(self.tmp, "backups")) if n.endswith(".tar.gz")]
        self.assertLessEqual(len(names), 2)


class WatchdogTest(Base):
    def test_logged_out_gowa_raises_one_alert(self):
        gowa = SimpleNamespace(device_status=lambda timeout=3: {"results": {"is_connected": False,
                                                                           "is_logged_in": False}})
        cfg = SimpleNamespace(tz_offset=3)
        fired = watchdog.check(self.crm, gowa, cfg)
        self.assertEqual([a["code"] for a in fired], ["gowa"])
        self.assertEqual(self.crm.unread_notifications(), 1)
        # same hour -> deduplicated
        watchdog.check(self.crm, gowa, cfg)
        self.assertEqual(self.crm.unread_notifications(), 1)

    def test_healthy_gowa_is_silent(self):
        gowa = SimpleNamespace(device_status=lambda timeout=3: {"results": {"is_connected": True,
                                                                           "is_logged_in": True}})
        self.assertEqual(watchdog.check(self.crm, gowa, SimpleNamespace(tz_offset=3)), [])


class GrowthTest(Base):
    def test_snapshot_is_idempotent_and_growth_reports_delta(self):
        self.store.conn.execute("INSERT INTO crm_channel_info (jid, name, subscribers, fetched_at) "
                                "VALUES ('1@newsletter','c',120,?)", (int(time.time()),))
        self.store.conn.commit()
        self.published("اليوم", 7)
        first = self.crm.snapshot_channel_day("2026-11-27")
        again = self.crm.snapshot_channel_day("2026-11-27")
        self.assertEqual(first["day"], again["day"])
        rows = self.store.conn.execute("SELECT COUNT(*) FROM crm_channel_daily").fetchone()[0]
        self.assertEqual(rows, 1)
        self.crm.snapshot_channel_day("2026-11-20")
        growth = self.crm.channel_growth(90)
        self.assertEqual(growth["points"], 2)


class VariantTest(Base):
    def test_create_and_compare(self):
        post = self.crm.create_channel_post({"channel_jid": "1@newsletter", "title": "أ",
                                             "body": "نسخة أ"})
        variant = self.crm.create_variant(post["id"])
        self.assertEqual(variant["variant_of"], post["id"])
        self.crm.mark_published(post["id"], "M1")
        self.crm.mark_published(variant["id"], "M2")
        self.store.conn.execute("UPDATE crm_posts SET views=30 WHERE id=?", (variant["id"],))
        self.store.conn.commit()
        result = self.crm.variant_results(post["id"])
        self.assertEqual(result["winner"], variant["id"])
        self.assertEqual(len(result["variants"]), 2)


class DailyBriefTest(Base):
    def test_brief_lists_today_and_blocked_drafts(self):
        self.crm.create_channel_post({"channel_jid": "1@newsletter", "title": "بلا صورة",
                                      "media_type": "image"})
        text = digest.build_daily_brief(self.crm)
        self.assertIn("موجز اليوم", text)
        self.assertIn("بانتظار وسائط", text)


if __name__ == "__main__":
    unittest.main()
