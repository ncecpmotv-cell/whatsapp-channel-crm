import base64, json, os, sys, urllib.request, urllib.error
pw = sys.argv[1]
auth = base64.b64encode(f"crm:{pw}".encode()).decode()
def post(path, payload):
    req = urllib.request.Request("http://127.0.0.1:3000" + path, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", "Basic " + auth)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Device-Id", "primary")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
phone = "966502369637@s.whatsapp.net"
print("poll->self:", post("/send/poll", {"phone": phone, "question": "اختبار استبيان", "options": ["أ", "ب", "ج"], "max_answer": 1}))
