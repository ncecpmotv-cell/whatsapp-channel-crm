
import os
import sys
import tempfile
import time
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

    def test_lifecycle_notifications(self):
        """Every lifecycle step lands in the bell; reading clears the badge."""
        post = self.crm.create_channel_post({
            "channel_jid": "1203630@newsletter", "title": "منشور اختبار", "body": "x"})
        self.assertEqual(self.crm.unread_notifications(), 0)

        self.crm.schedule_post(post["id"], 9999999999, approved=True)
        self.crm.cancel_post(post["id"])
        self.assertEqual(self.crm.unread_notifications(), 2)
        kinds = [n["kind"] for n in self.crm.notifications()]
        self.assertTrue(all(k == "content" for k in kinds))
        self.assertTrue(any("أُلغي" in n["title"] for n in self.crm.notifications()))

        self.crm.delete_post(post["id"])
        titles = [n["title"] for n in self.crm.notifications()]
        self.assertIn("حُذف عنصر", titles)
        self.assertEqual(self.crm.unread_notifications(), 3)

        self.crm.mark_notifications_read()
        self.assertEqual(self.crm.unread_notifications(), 0)

    def test_publish_notifications_dedupe(self):
        post = self.crm.create_channel_post({
            "channel_jid": "1203630@newsletter", "title": "نشر", "body": "x"})
        self.crm.mark_published(post["id"], "MID")
        self.crm.mark_published(post["id"], "MID")
        publish = [n for n in self.crm.notifications() if n["kind"] == "publish"]
        self.assertEqual(len(publish), 1)  # dedupe_key keeps one row per post

        other = self.crm.create_channel_post({
            "channel_jid": "1203630@newsletter", "title": "فشل", "body": "x"})
        self.crm.mark_failed(other["id"], "GOWA 500")
        self.assertTrue(any("فشل النشر" in n["title"] for n in self.crm.notifications()))

    def test_plan_save_replace_and_approve(self):
        plan = self.crm.save_plan("2026-12-07", [
            {"title": "منشور أول", "body": "نص", "kind": "text", "slot_at": "2026-12-07 19:00"},
            {"title": "فيديو قصير", "kind": "video", "goal": "engagement"},
        ], title="خطة الشتاء")
        self.assertEqual(plan["status"], "proposed")
        self.assertEqual(len(plan["items"]), 2)
        self.assertEqual(plan["items"][0]["slot_at"] % 60, 0)

        # same week replaces items, not a second plan
        plan = self.crm.save_plan("2026-12-07", [{"title": "بديل", "kind": "text"}])
        self.assertEqual(len(plan["items"]), 1)
        self.assertEqual(len(self.crm.list_plans()), 1)

        result = self.crm.approve_plan(plan["id"], "1203630@newsletter")
        self.assertEqual(result["created"], 1)
        post = self.crm.get_channel_post(result["posts"][0])
        self.assertEqual(post["status"], "draft")           # no slot -> draft
        self.assertEqual(self.crm.get_plan(plan_id=plan["id"])["status"], "approved")

        # idempotent
        again = self.crm.approve_plan(plan["id"], "1203630@newsletter")
        self.assertTrue(again.get("already"))

        # approved plans are immutable
        with self.assertRaises(PermissionError):
            self.crm.save_plan("2026-12-07", [{"title": "تعديل"}])

    def test_plan_slot_schedules_and_publishes_later(self):
        plan = self.crm.save_plan("2020-01-06", [
            {"title": "مجدول", "slot_at": "2020-01-06 21:00"}])
        result = self.crm.approve_plan(plan["id"], "1203630@newsletter")
        post = self.crm.get_channel_post(result["posts"][0])
        self.assertEqual(post["status"], "scheduled")
        self.assertEqual(len(self.crm.due_posts()), 1)

    def test_media_plan_items_stay_drafts_until_media_exists(self):
        plan = self.crm.save_plan("2026-12-21", [
            {"title": "فيديو بلا ملف", "kind": "video", "slot_at": "2099-01-01 20:00"},
            {"title": "نص جاهز", "kind": "text", "slot_at": "2099-01-01 21:00"},
        ])
        result = self.crm.approve_plan(plan["id"], "1203630@newsletter")
        self.assertEqual(len(result["needs_media"]), 1)
        video = self.crm.get_channel_post(result["needs_media"][0])
        self.assertEqual(video["status"], "draft")      # not scheduled into a failure
        text_post = [p for p in result["posts"] if p != video["id"]][0]
        self.assertEqual(self.crm.get_channel_post(text_post)["status"], "scheduled")

    def test_content_gaps_finds_opportunities_and_saturation(self):
        """A term that appears once with high views is an opportunity, not a trend."""
        def add(title, body, kind, views, at):
            post = self.crm.create_channel_post({
                "channel_jid": "1203630@newsletter", "title": title,
                "body": body, "content_type": kind})
            self.crm.mark_published(post["id"], "MID-" + post["id"])
            self.store.conn.execute(
                "UPDATE crm_posts SET views=?, published_at=? WHERE id=?",
                (views, at, post["id"]))
            self.store.conn.commit()

        now = int(time.time())
        add("صور المنتجات", "إضاءة طبيعية وخلفية ثابتة", "image", 90, now - 6 * 86400)
        add("فيديو خلف الكواليس", "كيف نجهز الطلب", "video", 120, now - 5 * 86400)
        add("نصائح سريعة", "ثلاث نصائح للتصوير بالجوال", "text", 12, now - 4 * 86400)
        add("نصائح أخرى", "نصائح للكتابة", "text", 10, now - 3 * 86400)
        add("نصائح ثالثة", "نصائح للنشر", "text", 8, now - 2 * 86400)

        gaps = self.crm.content_gaps(days=30)
        self.assertEqual(gaps["posts"], 5)
        # only repeated terms can be called a theme
        self.assertTrue(all(o["posts"] >= 2 for o in gaps["opportunities"]))
        self.assertTrue(all(o["avg_views"] > gaps["avg_views"] for o in gaps["opportunities"]))
        saturated = {s["term"] for s in gaps["saturated"]}
        self.assertIn("نصائح", saturated)     # three posts, low views
        self.assertGreaterEqual(gaps["cadence_per_week"], 1)

    def test_semantic_search_ranks_the_right_post_first(self):
        a = self.crm.create_channel_post({"channel_jid": "1@newsletter", "title": "تصوير المنتجات",
                                          "body": "الإضاءة الطبيعية تصنع الفرق"})
        self.crm.create_channel_post({"channel_jid": "1@newsletter", "title": "إدارة الوقت",
                                      "body": "نظم يومك بمهام صغيرة"})
        hits = self.crm.semantic_search("اضاءة المنتجات", limit=3)
        self.assertTrue(hits["results"])
        self.assertEqual(hits["results"][0]["id"], a["id"])
        # hamza/taa-marbuta normalisation: "الإضاءة" matches "اضاءه"
        self.assertEqual(self.crm.semantic_search("الإضاءة")["results"][0]["id"], a["id"])
        # light stemming: plural + definite article find the singular stem
        self.assertEqual(self.crm.semantic_search("المنتجات")["results"][0]["id"], a["id"])
        self.assertEqual(self.crm.semantic_search("منتج")["results"][0]["id"], a["id"])

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
