"""Local end-to-end harness: fake GOWA + the real bridge, over real HTTP.

Proves, without the phone: HMAC webhook ingest, MCP handshake, UI render,
draft -> human approval -> outbox -> GOWA send -> published.
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BRIDGE_DIR = os.path.expanduser("~/phone-crm/bridge")
sys.path.insert(0, BRIDGE_DIR)

FAKE_PORT = 3911
BRIDGE_PORT = 8099
TOKEN = "test-token-123"
SECRET = "whsec_test"
JID = "120363099999999999@newsletter"
SENT = []


class FakeGowa(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/devices/primary/status"):
            return self._json({"code": "SUCCESS", "results": {"state": "connected"}})
        if self.path.startswith("/newsletter/messages"):
            return self._json({"code": "SUCCESS", "results": {"data": [
                {"message_id": "WAMSG1", "server_id": 501, "text": "منشور أرشيفي",
                 "timestamp": int(time.time()) - 3600, "views_count": 12}
            ]}})
        if self.path.startswith("/newsletter/message-updates"):
            return self._json({"code": "SUCCESS", "results": {"data": [
                {"server_id": 501, "views_count": 33, "forwards_count": 4, "reaction_counts": {"👍": 2}}
            ]}})
        return self._json({"code": "ERROR", "message": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if self.path == "/send/message":
            SENT.append(json.loads(raw or b"{}"))
            return self._json({"code": "SUCCESS", "results": {"message_id": f"OUT{len(SENT)}"}})
        if self.path.startswith("/newsletter/live-updates"):
            return self._json({"code": "SUCCESS", "results": {"newsletter_id": JID}})
        return self._json({"code": "ERROR", "message": "not found"}, 404)


def http(method, path, body=None, headers=None, base=f"http://127.0.0.1:{BRIDGE_PORT}"):
    req = urllib.request.Request(base + path, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def main() -> int:
    tmp = tempfile.mkdtemp()
    env_path = os.path.join(tmp, ".env")
    with open(env_path, "w") as fh:
        fh.write(
            f"GOWA_BASE_URL=http://127.0.0.1:{FAKE_PORT}\n"
            f"GOWA_WEBHOOK_SECRET={SECRET}\n"
            f"BRIDGE_TOKEN={TOKEN}\n"
            f"BRIDGE_HOST=127.0.0.1\nBRIDGE_PORT={BRIDGE_PORT}\n"
            f"NEWSLETTER_JIDS={JID}\n"
            f"CRM_DB_PATH={tmp}/crm.db\n"
            f"DEFAULT_COUNTRY_CODE=966\n"
            f"BRIDGE_POLL_INTERVAL=2\nBRIDGE_CHANNEL_SYNC_INTERVAL=2\n"
            f"AGENT_CAN_PUBLISH=0\n"
        )

    fake = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeGowa)
    threading.Thread(target=fake.serve_forever, daemon=True).start()

    proc = subprocess.Popen(
        [sys.executable, "app.py"], cwd=BRIDGE_DIR,
        env={**os.environ, "BRIDGE_ENV_FILE": env_path},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(2.0)
    ok = True
    results = []

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        if isinstance(detail, (bytes, bytearray)):
            detail = detail.decode("utf-8", "replace")
        results.append(("PASS" if cond else "FAIL", name, str(detail)))

    try:
        status, body, _ = http("GET", "/health")
        health = json.loads(body)
        check("health 200 + crm ok", status == 200 and health.get("crm") is True, json.dumps(health)[:120])

        # --- inbound DM through the HMAC webhook
        event = {"event": "message", "payload": {
            "id": "IN1", "chat_id": "966500000001@s.whatsapp.net",
            "from": "966500000001@s.whatsapp.net", "body": "أبغى عرض سعر",
            "timestamp": "2026-11-26T12:00:00Z", "is_from_me": False}}
        raw = json.dumps(event).encode()
        sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        status, body, _ = http("POST", "/webhook/gowa", raw,
                               {"Content-Type": "application/json", "X-Hub-Signature-256": sig})
        check("webhook accepts signed DM", status == 200 and json.loads(body).get("ok") is True, body[:100])

        status, body, _ = http("POST", "/webhook/gowa", raw, {"Content-Type": "application/json",
                                                             "X-Hub-Signature-256": "sha256=bad"})
        check("webhook rejects bad signature", status == 401)

        # --- UI
        import base64
        auth = "Basic " + base64.b64encode(f"crm:{TOKEN}".encode()).decode()
        status, page_body, _ = http("GET", "/ui/content", headers={"Authorization": auth})
        match = re.search(rb'name="csrf" value="([a-f0-9]{32})"', page_body)
        csrf = match.group(1).decode() if match else ""
        check("UI forms carry a csrf token", bool(csrf), str(status))
        for path, needle in (("/ui", "لوحة اليوم"), ("/ui/content", "المحتوى"),
                             ("/ui/contacts", "العملاء"), ("/ui/metrics", "القياسات")):
            status, body, _ = http("GET", path, headers={"Authorization": auth})
            check(f"UI {path} renders", status == 200 and needle.encode() in body,
                  f"{status} {len(body)}b")
        status, _, _ = http("GET", "/ui")
        check("UI requires auth", status == 401)

        # --- create a draft from the UI form
        form = urllib.parse.urlencode({"title": "منشور اختبار", "body": "نص المنشور", "csrf": csrf}).encode()
        status, _, headers = http("POST", "/ui/content/new", form,
                                  {"Authorization": auth, "Content-Type": "application/x-www-form-urlencoded"})
        check("UI creates draft", status in (200, 303), str(status))

        import crm as crm_mod
        import store as store_mod
        store = store_mod.Store(os.path.join(tmp, "crm.db"))
        client = crm_mod.CrmClient(store)
        drafts = client.list_posts("draft")
        check("draft persisted", len(drafts) == 1, str(len(drafts)))
        post_id = drafts[0]["id"] if drafts else None

        # --- MCP handshake + approval policy
        rpc = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18"}}).encode()
        status, body, _ = http("POST", "/mcp", rpc,
                               {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        check("MCP initialize", status == 200 and json.loads(body)["result"]["serverInfo"]["name"] == "phone-crm-mcp")

        rpc = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
        status, body, _ = http("POST", "/mcp", rpc, {"Authorization": f"Bearer {TOKEN}",
                                                    "Content-Type": "application/json"})
        tools = [t["name"] for t in json.loads(body)["result"]["tools"]]
        check("MCP exposes the tool set", len(tools) >= 13, str(len(tools)))

        rpc = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "content_schedule", "arguments": {"id": post_id, "at": "2030-01-01T09:00:00+03:00"}}}).encode()
        status, body, _ = http("POST", "/mcp", rpc, {"Authorization": f"Bearer {TOKEN}",
                                                    "Content-Type": "application/json"})
        row = client.get_channel_post(post_id)
        check("agent proposal stays draft", row["status"] == "draft", row["status"])

        # --- human approval + publish through the outbox
        no_csrf = urllib.parse.urlencode({"id": post_id}).encode()
        status, _, _ = http("POST", "/ui/content/publish", no_csrf,
                            {"Authorization": auth, "Content-Type": "application/x-www-form-urlencoded"})
        check("POST without csrf rejected", status == 403, str(status))

        form = urllib.parse.urlencode({"id": post_id, "csrf": csrf}).encode()
        status, _, _ = http("POST", "/ui/content/publish", form,
                            {"Authorization": auth, "Content-Type": "application/x-www-form-urlencoded"})
        for _ in range(20):
            row = client.get_channel_post(post_id)
            if row["status"] in ("published", "failed"):
                break
            time.sleep(0.5)
        check("publish reached 'published'", row["status"] == "published", row["status"])
        check("GOWA received exactly one send", len(SENT) == 1, str(SENT)[:120])
        check("channel JID used as recipient", SENT and SENT[0].get("phone") == JID, str(SENT[:1])[:160])
        check("message_id stored", bool(row.get("message_id")), str(row.get("message_id")))

        # --- archive sync + counters
        time.sleep(2.5)
        archived = [p for p in client.list_posts("published") if p["message_id"] == "WAMSG1"]
        check("channel archive imported", len(archived) == 1, str(len(archived)))
        if archived:
            time.sleep(2.5)
            fresh = client.get_channel_post(archived[0]["id"])
            check("counters updated from feed", fresh["views"] >= 12,
                  f"views={fresh['views']} forwards={fresh['forwards']} reactions={fresh['reactions']}")
        store.close()
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ""
        fake.shutdown()

    print("\n".join(f"[{s}] {n} {('· ' + d) if d else ''}" for s, n, d in results))
    failures = [r for r in results if r[0] == "FAIL"]
    print(f"\n{len(results) - len(failures)}/{len(results)} checks passed")
    if failures:
        print("\n--- bridge log tail ---\n" + "\n".join(out.splitlines()[-25:]))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
