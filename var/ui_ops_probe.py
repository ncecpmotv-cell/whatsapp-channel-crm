"""Exercise create/edit/delete through the real HTTP UI (run inside crm-app)."""
import base64
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request
import uuid

env = dict(line.split("=", 1) for line in open("/var/crm/node.env") if "=" in line)
auth = base64.b64encode(f"crm:{env['BRIDGE_TOKEN'].strip()}".encode()).decode()
BASE = "http://127.0.0.1:8086"


def post(path, fields, files=None):
    if files:
        boundary = "----t" + uuid.uuid4().hex
        body = b""
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        for k, (name, content) in files.items():
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{name}\"\r\n"
                     f"Content-Type: {ctype}\r\n\r\n").encode() + content + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        ctype_header = f"multipart/form-data; boundary={boundary}"
    else:
        body = urllib.parse.urlencode(fields).encode()
        ctype_header = "application/x-www-form-urlencoded"
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Authorization", "Basic " + auth)
    req.add_header("Content-Type", ctype_header)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.url
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:120]


with open("/var/crm/media/test-image.png", "rb") as fh:
    png = fh.read()

st, url = post("/ui/content/new", {"type": "image", "title": "اختبار صورة",
                                   "body": "رفع صورة عبر الواجهة"}, {"media": ("shot.png", png)})
print("create image:", st, url)
image_id = url.rsplit("/", 1)[-1]

st, url = post("/ui/content/new", {"type": "text", "title": "مسودة للحذف", "body": "x"})
draft_id = url.rsplit("/", 1)[-1]
st, _ = post("/ui/content/delete", {"id": draft_id})
print("delete draft:", st)

st, url = post("/ui/content/new", {"type": "link", "title": "رابط", "body": "موقعنا",
                                   "url": "https://example.com"})
link_id = url.rsplit("/", 1)[-1]
print("create link:", st, link_id)

st, body = post("/ui/content/new", {"type": "poll", "title": "استبيان", "options": "أ"})
print("poll without options:", st, body[:60])

st, body = post("/ui/content/delete", {"id": "000000000000"})
print("delete missing:", st)
print("image_id:", image_id)
