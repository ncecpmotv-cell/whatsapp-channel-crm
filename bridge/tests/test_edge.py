"""Edge client + brand kit: no network, no surprises."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crm import CrmClient  # noqa: E402
from edge import EdgeClient  # noqa: E402
from store import Store  # noqa: E402


class FakeEdge(EdgeClient):
    def __init__(self, status=200, body=b'{"ok": true}', base="https://edge.test", token="t"):
        super().__init__(base, token)
        self.status = status
        self.body = body
        self.calls = []

    def _request(self, method, path, body=None, headers=None):
        self.calls.append({"method": method, "path": path, "size": len(body or b""),
                           "headers": headers or {}})
        return self.status, self.body


class EdgeClientTest(unittest.TestCase):
    def test_disabled_client_is_silent(self):
        client = EdgeClient("", "")
        self.assertFalse(client.enabled())
        self.assertFalse(client.heartbeat({"posts": 1}))
        self.assertEqual(client.backups(), [])
        self.assertFalse(client.transcribe("/nope")["ok"])

    def test_backup_upload_reports_success_and_keeps_the_name(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
        tmp.write(b"x" * 2048)
        tmp.close()
        self.addCleanup(lambda: os.unlink(tmp.name))
        client = FakeEdge()
        result = client.upload_backup(tmp.name)
        self.assertTrue(result["ok"])
        self.assertIn("name=", client.calls[0]["path"])
        self.assertEqual(client.calls[0]["size"], 2048)

    def test_failed_upload_is_not_ok(self):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(b"x")
        tmp.close()
        self.addCleanup(lambda: os.unlink(tmp.name))
        client = FakeEdge(status=500, body=b'{"error":"boom"}')
        self.assertFalse(client.upload_backup(tmp.name)["ok"])

    def test_transcribe_rejects_a_missing_file_without_calling_remote(self):
        client = FakeEdge()
        result = client.transcribe("/definitely/missing.ogg")
        self.assertFalse(result["ok"])
        self.assertEqual(client.calls, [])

    def test_transcribe_sends_the_file_bytes(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        tmp.write(b"OggS" + b"\x00" * 100)
        tmp.close()
        self.addCleanup(lambda: os.unlink(tmp.name))
        client = FakeEdge(body='{"ok": true, "text": "مرحبا"}'.encode())
        result = client.transcribe(tmp.name)
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "مرحبا")
        self.assertEqual(client.calls[0]["size"], 104)


class BrandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)

    def tearDown(self):
        self.store.close()

    def test_defaults_include_the_owner_rules(self):
        brand = self.crm.get_brand()
        self.assertEqual(brand["palette"]["gold"], "#C5A059")
        self.assertIn("بلا شعارات أو أسماء شخصية", brand["donts"])
        self.assertFalse(brand["limits"]["polls"])

    def test_partial_update_deep_merges(self):
        brand = self.crm.set_brand({"palette": {"gold": "#B08A3E"}, "tagline": "دفء الشتاء"})
        self.assertEqual(brand["palette"]["gold"], "#B08A3E")
        self.assertEqual(brand["palette"]["deep"], "#2A3A31")
        self.assertEqual(brand["tagline"], "دفء الشتاء")
        self.assertEqual(self.crm.get_brand()["palette"]["gold"], "#B08A3E")


if __name__ == "__main__":
    unittest.main()
