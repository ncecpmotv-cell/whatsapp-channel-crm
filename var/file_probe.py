import base64, json, os, sys, urllib.request, urllib.error, uuid
pw = sys.argv[1]; path = "/var/crm/media/test-file.pdf"
auth = base64.b64encode(f"crm:{pw}".encode()).decode()
boundary = "----probe" + uuid.uuid4().hex
content = open(path, "rb").read()
def part(name, value):
    return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
body = part("phone", "120363409750144525@newsletter") + part("caption", "اختبار ملف") 
body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test.pdf\"\r\n"
         f"Content-Type: application/pdf\r\n\r\n").encode() + content + b"\r\n"
body += f"--{boundary}--\r\n".encode()
req = urllib.request.Request("http://127.0.0.1:3000/send/file", data=body, method="POST")
req.add_header("Authorization", "Basic " + auth)
req.add_header("X-Device-Id", "primary")
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
try:
    with urllib.request.urlopen(req, timeout=60) as r: print("file:", r.status, r.read().decode()[:160])
except urllib.error.HTTPError as e: print("file:", e.code, e.read().decode()[:200])
