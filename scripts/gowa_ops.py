"""Small GOWA ops helper (run inside the CRM node).

Usage: python3 /var/crm/gowa_ops.py <password> status|channels|info <jid>
"""
import base64
import json
import sys
import urllib.request

pw = sys.argv[1]
cmd = sys.argv[2] if len(sys.argv) > 2 else "status"
arg = sys.argv[3] if len(sys.argv) > 3 else ""
auth = base64.b64encode(f"crm:{pw}".encode()).decode()


def call(path):
    req = urllib.request.Request("http://127.0.0.1:3000" + path)
    req.add_header("Authorization", "Basic " + auth)
    req.add_header("X-Device-Id", "primary")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]


if cmd == "status":
    print(json.dumps(call("/devices"), ensure_ascii=False, indent=1)[:1500])
elif cmd == "channels":
    print(json.dumps(call("/user/my/newsletters"), ensure_ascii=False, indent=1)[:3000])
elif cmd == "info":
    print(json.dumps(call(f"/newsletter/info?newsletter_id={urllib.parse.quote(arg)}"),
                     ensure_ascii=False, indent=1)[:2000])
