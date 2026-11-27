"""Origin guard: same-origin posts must survive a reverse proxy (tailscale serve)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import origin_allowed  # noqa: E402


class OriginTest(unittest.TestCase):
    def test_no_origin_is_allowed(self):
        self.assertTrue(origin_allowed({"Host": "127.0.0.1:8085"}, {}))

    def test_same_host_is_allowed(self):
        h = {"Host": "smartp.tail16a0c8.ts.net", "Origin": "https://smartp.tail16a0c8.ts.net"}
        self.assertTrue(origin_allowed(h, {}))

    def test_default_port_is_ignored(self):
        h = {"Host": "smartp.tail16a0c8.ts.net:443", "Origin": "https://smartp.tail16a0c8.ts.net"}
        self.assertTrue(origin_allowed(h, {}))
        h = {"Host": "smartp.tail16a0c8.ts.net", "Origin": "https://smartp.tail16a0c8.ts.net:443"}
        self.assertTrue(origin_allowed(h, {}))

    def test_forwarded_host_is_allowed(self):
        """The proxy rewrites Host; the browser still sends the public Origin."""
        h = {
            "Host": "127.0.0.1:8085",
            "X-Forwarded-Host": "smartp.tail16a0c8.ts.net",
            "Origin": "https://smartp.tail16a0c8.ts.net",
        }
        self.assertTrue(origin_allowed(h, {}))

    def test_public_base_url_is_allowed(self):
        h = {"Host": "127.0.0.1:8085", "Origin": "https://smartp.tail16a0c8.ts.net"}
        self.assertTrue(origin_allowed(h, {"PUBLIC_BASE_URL": "https://smartp.tail16a0c8.ts.net"}))

    def test_trusted_origins_list_is_allowed(self):
        h = {"Host": "127.0.0.1:8085", "Origin": "https://crm.example.test"}
        env = {"TRUSTED_ORIGINS": "https://a.test, https://crm.example.test"}
        self.assertTrue(origin_allowed(h, env))

    def test_foreign_origin_is_rejected(self):
        h = {"Host": "smartp.tail16a0c8.ts.net", "Origin": "https://evil.example"}
        self.assertFalse(origin_allowed(h, {}))

    def test_cross_site_fetch_is_rejected(self):
        h = {"Host": "smartp.tail16a0c8.ts.net", "Sec-Fetch-Site": "cross-site"}
        self.assertFalse(origin_allowed(h, {}))

    def test_scheme_must_be_http(self):
        h = {"Host": "x", "Origin": "file://x"}
        self.assertFalse(origin_allowed(h, {}))


if __name__ == "__main__":
    unittest.main()
