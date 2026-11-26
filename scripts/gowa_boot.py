"""One-shot GOWA bootstrap inside the CRM node: register the device, print the QR link.

Usage: python3 /var/crm/gowa_boot.py <basic-auth-password> [qr-out-path]
"""
import base64
import json
import sys
import urllib.request

pw = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "/var/crm/qr.png"
auth = base64.b64encode(f"crm:{pw}".encode()).decode()


def call(path, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:3000" + path, data=data,
                                 method=method or ("POST" if data else "GET"))
    req.add_header("Authorization", "Basic " + auth)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Device-Id", "primary")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]


status, body = call("/devices", {"device_id": "primary"})
print("devices:", status, json.dumps(body, ensure_ascii=False)[:200])

status, body = call("/devices/primary/login")
print("login:", status, json.dumps(body, ensure_ascii=False)[:200])
link = (body.get("results") or {}).get("qr_link") if isinstance(body, dict) else None
if link:
    with urllib.request.urlopen(link, timeout=20) as resp:
        data = resp.read()
    with open(out, "wb") as fh:
        fh.write(data)
    print("qr saved:", out, len(data), "bytes")
