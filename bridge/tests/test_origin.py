"""Origin guard: same-origin posts must survive a reverse proxy (tailscale serve)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import origin_allowed  # noqa: E402
from config import Config  # noqa: E402


class ConfigOriginTest(unittest.TestCase):
    def test_proxy_settings_are_read_from_the_env_file(self):
        """The UI settings live in the env file, not in os.environ."""
        path = tempfile.mktemp()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("GOWA_WEBHOOK_SECRET=s\nBRIDGE_TOKEN=t\n"
                     "PUBLIC_BASE_URL=https://smartp.tail16a0c8.ts.net\n"
                     "ALLOW_TAILNET_DOMAIN=tail16a0c8.ts.net\n")
        cfg = Config.load(path)
        self.assertEqual(cfg.public_base_url, "https://smartp.tail16a0c8.ts.net")
        self.assertEqual(cfg.allow_tailnet_domain, "tail16a0c8.ts.net")
        h = {"Host": "127.0.0.1:8085", "Origin": "https://smartp.tail16a0c8.ts.net"}
        self.assertTrue(origin_allowed(h, {
            "PUBLIC_BASE_URL": cfg.public_base_url,
            "ALLOW_TAILNET_DOMAIN": cfg.allow_tailnet_domain}))


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

    def test_tailnet_domain_is_allowed(self):
        h = {"Host": "127.0.0.1:8085", "Origin": "https://pot-lx1af.tail16a0c8.ts.net"}
        self.assertTrue(origin_allowed(h, {"ALLOW_TAILNET_DOMAIN": "tail16a0c8.ts.net"}))

    def test_tailnet_domain_suffix_cannot_be_spoofed(self):
        h = {"Host": "127.0.0.1:8085", "Origin": "https://evil-tail16a0c8.ts.net"}
        self.assertFalse(origin_allowed(h, {"ALLOW_TAILNET_DOMAIN": "tail16a0c8.ts.net"}))
        h = {"Host": "127.0.0.1:8085", "Origin": "https://tail16a0c8.ts.net.evil.com"}
        self.assertFalse(origin_allowed(h, {"ALLOW_TAILNET_DOMAIN": "tail16a0c8.ts.net"}))

    def test_tailnet_ip_and_loopback_are_allowed(self):
        for origin in ("https://100.107.57.87", "http://127.0.0.1:8085", "http://localhost:8085"):
            h = {"Host": "127.0.0.1:8085", "Origin": origin}
            self.assertTrue(origin_allowed(h, {}), origin)
        h = {"Host": "127.0.0.1:8085", "Origin": "http://8.8.8.8"}
        self.assertFalse(origin_allowed(h, {}))

    def test_same_site_fetch_is_allowed(self):
        h = {"Host": "127.0.0.1:8085", "Sec-Fetch-Site": "same-site"}
        self.assertTrue(origin_allowed(h, {}))

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
