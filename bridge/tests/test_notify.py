"""Push notifier: payload shape, event filter and the promise that it never raises."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notify  # noqa: E402


def cfg(**kw):
    base = dict(telegram_bot_token="", telegram_chat_id="", push_events="publish,failed",
                public_base_url="https://smartp.tail16a0c8.ts.net")
    base.update(kw)
    return SimpleNamespace(**base)


class NotifierTest(unittest.TestCase):
    def test_disabled_without_channels(self):
        n = notify.PushNotifier(cfg(), sender=lambda *a: True)
        self.assertFalse(n.enabled())
        calls = []
        n._send_safely("publish", "t", "b", "")  # must not explode or send
        self.assertEqual(calls, [])

    def test_event_filter(self):
        n = notify.PushNotifier(cfg(telegram_bot_token="t", telegram_chat_id="1"),
                                sender=lambda *a: True)
        self.assertTrue(n.wants("publish"))
        self.assertFalse(n.wants("content"))

    def test_telegram_payload(self):
        sent = {}

        def fake(url, payload, timeout=6.0):
            sent.update(url=url, payload=payload)
            return True

        n = notify.PushNotifier(cfg(telegram_bot_token="TOK", telegram_chat_id="42"),
                                sender=fake)
        n._telegram("تم النشر", "نُشر على القناة", "https://x/ui/post/1")
        self.assertIn("/botTOK/sendMessage", sent["url"])
        self.assertEqual(sent["payload"]["chat_id"], "42")
        self.assertIn("تم النشر", sent["payload"]["text"])
        self.assertIn("https://x/ui/post/1", sent["payload"]["text"])

    def test_absolute_link_uses_public_base_url(self):
        n = notify.PushNotifier(cfg(telegram_bot_token="T", telegram_chat_id="1",
                                    public_base_url="https://crm.test"))
        self.assertEqual(n.base_url, "https://crm.test")

    def test_termux_channel_is_used_when_installed(self):
        calls = []
        real_which, real_run = notify.shutil.which, notify.subprocess.run
        notify.shutil.which = lambda name: "/usr/bin/" + name
        notify.subprocess.run = lambda args, **kw: calls.append(args)
        try:
            n = notify.PushNotifier(cfg())
            self.assertTrue(n.enabled())
            n._termux("عنوان", "نص", "https://x")
        finally:
            notify.shutil.which, notify.subprocess.run = real_which, real_run
        self.assertEqual(calls[0][0], "termux-notification")
        self.assertIn("--title", calls[0])
        self.assertIn("https://x", calls[0])

    def test_failure_is_swallowed(self):
        def boom(url, payload, timeout=6.0):
            raise RuntimeError("network down")

        n = notify.PushNotifier(cfg(telegram_bot_token="T", telegram_chat_id="1"), sender=boom)
        n._send_safely("publish", "t", "b", "")  # no exception

    def test_describe_has_no_secrets(self):
        state = notify.describe(cfg(telegram_bot_token="SECRET", telegram_chat_id="9"))
        self.assertNotIn("SECRET", str(state))
        self.assertTrue(state["telegram"])


if __name__ == "__main__":
    unittest.main()
