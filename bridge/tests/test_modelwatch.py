"""Model failover: parse keys, probe cheaply, switch only when needed."""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import modelwatch  # noqa: E402
from crm import CrmClient  # noqa: E402
from store import Store  # noqa: E402


class ModelWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)
        self.cfg = SimpleNamespace(picoclaw_home=self.tmp, model_watch_interval=1800)
        self.models = [
            {"name": "default", "base": "https://primary.test/v1", "model": "m1", "key": "k1",
             "enabled": True},
            {"name": "fallback", "base": "https://fallback.test/v1", "model": "m2", "key": "k2",
             "enabled": True},
        ]

    def tearDown(self):
        self.store.close()

    def test_key_parser_reads_the_pico_shape(self):
        path = os.path.join(self.tmp, ".security.yml")
        with open(path, "w") as handle:
            handle.write("model_list:\n  default:0:\n    api_keys:\n      - abc123\n"
                         "  fallback:0:\n    api_keys:\n      - xyz789\nweb:\n  brave: {}\n")
        keys = modelwatch.read_keys(path)
        self.assertEqual(keys, {"default": "abc123", "fallback": "xyz789"})

    def test_probe_fails_fast_on_an_unreachable_host(self):
        healthy, reason = modelwatch.probe({"base": "http://127.0.0.1:9/v1", "key": "x"},
                                           timeout=1)
        self.assertFalse(healthy)
        self.assertTrue(reason)

    def test_switch_to_fallback_when_primary_is_down(self):
        with mock.patch.object(modelwatch, "read_models", return_value=self.models), \
             mock.patch.object(modelwatch, "probe", return_value=(False, "HTTP 429")), \
             mock.patch.object(modelwatch, "current_model", return_value="default"), \
             mock.patch.object(modelwatch, "switch", return_value=(True, "ok")) as sw:
            state = modelwatch.check(self.crm, self.cfg)
        self.assertEqual(state["switched"]["to"], "fallback")
        sw.assert_called_once_with("fallback", self.tmp)
        stored = json.loads(self.store.get_meta("model_health"))
        self.assertFalse(stored["healthy"])

    def test_no_switch_when_primary_is_healthy(self):
        with mock.patch.object(modelwatch, "read_models", return_value=self.models), \
             mock.patch.object(modelwatch, "probe", return_value=(True, "ok")), \
             mock.patch.object(modelwatch, "current_model", return_value="default"), \
             mock.patch.object(modelwatch, "switch") as sw:
            state = modelwatch.check(self.crm, self.cfg)
        self.assertIsNone(state["switched"])
        sw.assert_not_called()

    def test_recovery_switches_back(self):
        with mock.patch.object(modelwatch, "read_models", return_value=self.models), \
             mock.patch.object(modelwatch, "probe", return_value=(True, "ok")), \
             mock.patch.object(modelwatch, "current_model", return_value="fallback"), \
             mock.patch.object(modelwatch, "switch", return_value=(True, "ok")) as sw:
            state = modelwatch.check(self.crm, self.cfg)
        self.assertTrue(state["switched"]["recovered"])
        sw.assert_called_once_with("default", self.tmp)


if __name__ == "__main__":
    unittest.main()
