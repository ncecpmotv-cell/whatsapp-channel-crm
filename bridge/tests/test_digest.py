"""Weekly digest: schedule decision, message content, and credential discovery."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import digest  # noqa: E402


class FakeCrm:
    def channel_metrics(self, days):
        return {"total": {"posts": 5, "views": 40, "avg_views": 8.0}}

    def content_gaps(self, days):
        return {"per_type": [{"type": "video", "posts": 1, "avg_views": 16.0}],
                "opportunities": [{"term": "حملة شتاء", "posts": 4, "avg_views": 9.0}]}

    def posting_times(self, days):
        return {"best": [{"weekday": "الأربعاء", "hour": 21, "avg_views": 14.5}]}

    def get_plan(self):
        return {"week_start": "2026-12-07", "status": "proposed", "items": [1, 2, 3]}

    def count_posts(self, status):
        return 2

    def notify(self, *a, **k):
        return True


class ShouldSendTest(unittest.TestCase):
    def sunday_2000(self):
        # 2026-11-29 is a Sunday; 20:10 Riyadh == 17:10 UTC
        return time.mktime((2026, 11, 29, 17, 10, 0, 0, 0, -1))

    def test_sends_on_sunday_evening(self):
        self.assertTrue(digest.should_send(self.sunday_2000(), None, tz_offset=3))

    def test_not_again_within_six_days(self):
        now = self.sunday_2000()
        self.assertFalse(digest.should_send(now, now - 86400, tz_offset=3))

    def test_wrong_day(self):
        monday = self.sunday_2000() + 86400
        self.assertFalse(digest.should_send(monday, None, tz_offset=3))

    def test_outside_window(self):
        late = self.sunday_2000() + 6 * 3600
        self.assertFalse(digest.should_send(late, None, tz_offset=3))


class DigestTextTest(unittest.TestCase):
    def test_contains_the_numbers_and_the_next_action(self):
        text = digest.build_digest(FakeCrm())
        self.assertIn("المنشورات: 5", text)
        self.assertIn("أفضل نوع: video", text)
        self.assertIn("الأربعاء 21:00", text)
        self.assertIn("معتمدة" if False else "مقترحة", text)
        self.assertIn("حملة شتاء", text)


class CredsTest(unittest.TestCase):
    def test_reads_token_and_chat_from_the_pico_home(self):
        home = tempfile.mkdtemp()
        with open(os.path.join(home, "config.json"), "w", encoding="utf-8") as fh:
            fh.write('{"channel_list": {"telegram": {"allow_from": ["976417275"]}}}')
        with open(os.path.join(home, ".security.yml"), "w", encoding="utf-8") as fh:
            fh.write("channel_list:\n  telegram:\n    settings:\n      token: 123:ABC\n")
        token, chat = digest.telegram_creds(home)
        self.assertEqual(token, "123:ABC")
        self.assertEqual(chat, "976417275")

    def test_missing_files_do_not_raise(self):
        self.assertEqual(digest.telegram_creds(tempfile.mkdtemp()), ("", ""))


class SendTest(unittest.TestCase):
    def test_without_credentials_it_returns_false(self):
        self.assertFalse(digest.send_telegram("", "", "x"))
