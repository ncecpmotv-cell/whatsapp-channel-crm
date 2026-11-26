import base64, json, sys, urllib.request, urllib.error
pw = sys.argv[1]
body = sys.argv[2]
auth = base64.b64encode(f"crm:{pw}".encode()).decode()
req = urllib.request.Request("http://127.0.0.1:3000/send/message",
    data=json.dumps({"phone": "120363409750144525@newsletter", "message": body}, ensure_ascii=False).encode(),
    method="POST")
req.add_header("Authorization", "Basic " + auth)
req.add_header("Content-Type", "application/json")
req.add_header("X-Device-Id", "primary")
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print("200", r.read().decode()[:200])
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode()[:300])
