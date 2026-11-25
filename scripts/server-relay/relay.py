#!/usr/bin/env python3
"""Tiny authenticated reverse proxy: 0.0.0.0:18082 -> 127.0.0.1:18081.

Sits between a Cloudflare quick tunnel and the phone's EspoCRM vhost so the
public URL is useless without the HTTP Basic credentials. EspoCRM's own login
is a second layer.
"""
import base64
import hmac
import http.client
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = ("127.0.0.1", int(os.environ.get("RELAY_UPSTREAM_PORT", "18081")))
USER = os.environ["RELAY_USER"]
PASS = os.environ["RELAY_PASS"]
PORT = int(os.environ.get("RELAY_PORT", "18082"))
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
       "te", "trailers", "transfer-encoding", "upgrade", "host", "authorization"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            user, _, password = base64.b64decode(header[6:]).decode().partition(":")
        except Exception:
            return False
        return hmac.compare_digest(user, USER) and hmac.compare_digest(password, PASS)

    def _proxy(self):
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="CRM", charset="UTF-8"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        try:
            conn = http.client.HTTPConnection(*UPSTREAM, timeout=90)
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except Exception as exc:  # noqa: BLE001
            msg = f"upstream error: {exc}".encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        self.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() not in HOP:
                self.send_header(key, value)
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        conn.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _proxy

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
