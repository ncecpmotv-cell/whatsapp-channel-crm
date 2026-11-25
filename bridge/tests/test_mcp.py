import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import make_server
from config import Config
from mcp import McpServer
from service import Bridge


class FakeEspo:
    def __init__(self):
        self.calls = []
        self.posts = {}

    def _call(self, method, path, payload=None, params=None):
        self.calls.append((method, path, params))
        if method == "GET" and path == "/Contact":
            return {"total": 1, "list": [{"id": "c1", "firstName": "أحمد",
                                          "phoneNumber": "+966500000000"}]}
        return {"id": "x1"}

    def create_channel_post(self, fields):
        rec = dict(fields, id="p1")
        self.posts["p1"] = rec
        return rec

    def update_channel_post(self, post_id, fields):
        self.posts.setdefault(post_id, {}).update(fields)
        return self.posts[post_id]

    def list_ready_to_publish(self, limit=10):
        return [r for r in self.posts.values() if r.get("status") == "Ready to Publish"]

    def ping(self):
        return True


class FakeGowa:
    def __init__(self):
        self.sent = []

    def send_message(self, to, message):
        self.sent.append((to, message))
        return {"code": "SUCCESS"}

    def newsletter_messages(self, jid, count=20):
        return {"results": {"messages": [{"message_id": "m1", "text": "منشور"}]}}

    def device_status(self):
        return {"code": "SUCCESS"}


def cfg_for(tmp, token="tok"):
    return Config(
        gowa_base_url="http://127.0.0.1:3000", gowa_device_id="primary",
        gowa_webhook_secret="s",
        bridge_host="127.0.0.1", bridge_port=0, bridge_token=token,
        espo_base_url="http://127.0.0.1:8081", espo_api_key="k", espo_user="wa-bridge",
        newsletter_jids=(), default_country_code="966",
        db_path=os.path.join(tmp, "b.db"), poll_interval=60,
        channel_sync_interval=300, log_level="INFO",
    )


class McpProtocolTests(unittest.TestCase):
    def setUp(self):
        self.espo, self.gowa = FakeEspo(), FakeGowa()
        self.mcp = McpServer(self.espo, self.gowa,
                             health=lambda: {"ok": True, "queue": 0})

    def call(self, method, params=None, req_id=1):
        return self.mcp.handle({"jsonrpc": "2.0", "id": req_id,
                                "method": method, "params": params or {}})

    def tool(self, name, args):
        res = self.call("tools/call", {"name": name, "arguments": args})
        return res["result"]

    def test_initialize_negotiates_version(self):
        out = self.call("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(out["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", out["result"]["capabilities"])
        self.assertEqual(out["result"]["serverInfo"]["name"], "gowa-espocrm-mcp")

    def test_initialize_falls_back_on_unknown_version(self):
        out = self.call("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(out["result"]["protocolVersion"], "2025-06-18")

    def test_notification_returns_none(self):
        self.assertIsNone(self.mcp.handle({"jsonrpc": "2.0",
                                           "method": "notifications/initialized"}))

    def test_tools_list_has_expected_tools(self):
        names = {t["name"] for t in self.call("tools/list")["result"]["tools"]}
        self.assertEqual(names, {
            "crm_search", "crm_get", "crm_create_channel_post",
            "crm_update_channel_post", "crm_list_ready_posts",
            "wa_send", "wa_channel_messages", "bridge_health"})
        for tool in self.call("tools/list")["result"]["tools"]:
            self.assertIn("inputSchema", tool)

    def test_crm_search_by_phone_builds_filter(self):
        out = self.tool("crm_search", {"entity": "Contact", "phone": "+966500000000"})
        self.assertFalse(out["isError"])
        method, path, params = self.espo.calls[-1]
        self.assertEqual(path, "/Contact")
        self.assertEqual(params["where[0][field]"], "phoneNumber")

    def test_crm_search_by_text_uses_textFilter(self):
        self.tool("crm_search", {"entity": "Lead", "q": "أحمد"})
        self.assertEqual(self.espo.calls[-1][2]["textFilter"], "أحمد")

    def test_invalid_entity_is_tool_error(self):
        out = self.tool("crm_search", {"entity": "Evil"})
        self.assertTrue(out["isError"])

    def test_create_and_publish_flow(self):
        out = self.tool("crm_create_channel_post",
                        {"name": "إعلان", "channelJid": "1203630@newsletter",
                         "body": "نص", "status": "Ready to Publish"})
        self.assertFalse(out["isError"])
        self.assertEqual(self.espo.posts["p1"]["status"], "Ready to Publish")
        ready = self.tool("crm_list_ready_posts", {})
        self.assertEqual(ready["content"][0]["type"], "text")

    def test_wa_send_reaches_gowa(self):
        out = self.tool("wa_send", {"to": "1203630@newsletter", "message": "مرحبا"})
        self.assertFalse(out["isError"])
        self.assertEqual(self.gowa.sent, [("1203630@newsletter", "مرحبا")])

    def test_missing_required_arg_is_tool_error(self):
        self.assertTrue(self.tool("wa_send", {"to": "x"})["isError"])

    def test_unknown_tool_and_method(self):
        self.assertTrue(self.tool("nope", {})["isError"])
        err = self.call("nope/method")
        self.assertEqual(err["error"]["code"], -32601)


class McpHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = cfg_for(self.tmp.name)
        self.bridge = Bridge(self.cfg, espo=FakeEspo(), gowa=FakeGowa())
        self.server = make_server(self.cfg, self.bridge)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.bridge.store.close()
        self.tmp.cleanup()

    def post(self, body, token="tok"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("POST", "/mcp", body=json.dumps(body), headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode()
        sid = resp.getheader("Mcp-Session-Id")
        conn.close()
        return resp.status, (json.loads(data) if data else None), sid

    def test_requires_token(self):
        status, _, _ = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=None)
        self.assertEqual(status, 401)

    def test_rejects_wrong_token(self):
        status, _, _ = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                 token="not-the-token")
        self.assertEqual(status, 401)

    def test_initialize_over_http_returns_session(self):
        status, payload, sid = self.post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                          "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(status, 200)
        self.assertTrue(sid)
        self.assertEqual(payload["result"]["serverInfo"]["name"], "gowa-espocrm-mcp")

    def test_tool_call_over_http(self):
        status, payload, _ = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                        "params": {"name": "wa_send",
                                                   "arguments": {"to": "+9665", "message": "hi"}}})
        self.assertEqual(status, 200)
        self.assertFalse(payload["result"]["isError"])

    def test_notification_returns_202(self):
        status, payload, _ = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(status, 202)
        self.assertIsNone(payload)

    def test_get_mcp_is_405_with_allow_header(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/mcp")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 405)
        self.assertEqual(resp.getheader("Allow"), "POST")
        conn.close()


if __name__ == "__main__":
    unittest.main()
