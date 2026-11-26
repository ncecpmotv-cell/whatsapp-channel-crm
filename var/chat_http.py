import base64, sys, time, urllib.parse, urllib.request
token = sys.argv[1]; question = sys.argv[2]
auth = base64.b64encode(f"crm:{token}".encode()).decode()
data = urllib.parse.urlencode({"message": question}).encode()
req = urllib.request.Request("http://127.0.0.1:8086/ui/chat", data=data, method="POST")
req.add_header("Authorization", "Basic " + auth)
req.add_header("Content-Type", "application/x-www-form-urlencoded")
start = time.time()
with urllib.request.urlopen(req, timeout=180) as resp:
    print("status:", resp.status, "in", round(time.time() - start, 1), "s")
