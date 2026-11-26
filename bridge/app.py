"""HTTP front door: GOWA webhook + MCP + Arabic UI on one port.

Endpoints
  POST /webhook/gowa     GOWA events, HMAC-verified (X-Hub-Signature-256)
  POST /mcp              MCP over JSON-RPC (bearer token)
  POST /hook/publish     queue an approved post (bearer token)
  GET  /ui...            server-rendered Arabic UI (basic auth)
  GET  /health           dependency + queue status
"""
from __future__ import annotations

import base64
import gzip
import hmac
import json
import logging
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ui
from config import Config
from gowa import verify_signature
from mcp import McpServer, new_session_id
from service import Bridge, to_epoch

log = logging.getLogger("bridge.http")
MAX_BODY = 1_048_576  # 1 MiB
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# Writable cache for generated assets (the code dir is mounted read-only).
CACHE_DIR = os.environ.get("STATIC_CACHE", "/var/crm/static")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PhoneCrm/2.0"
    bridge: Bridge
    mcp: McpServer

    # -- helpers -----------------------------------------------------------
    def _send_bytes(self, status: int, body: bytes, content_type: str,
                    headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send(self, status: int, payload, headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8", headers)

    def _send_html(self, status: int, body: bytes) -> None:
        self._send_bytes(status, body, "text/html; charset=utf-8")

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_no_content(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        if length <= 0 or length > MAX_BODY:
            return b""
        return self.rfile.read(length)

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def _bearer_ok(self) -> bool:
        token = self.bridge.cfg.bridge_token or ""
        supplied = self.headers.get("X-Bridge-Token") or ""
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        return bool(token) and hmac.compare_digest(token, supplied)

    def _basic_ok(self) -> bool:
        """UI auth: any username, password = BRIDGE_TOKEN (browser prompt)."""
        token = self.bridge.cfg.bridge_token or ""
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                _user, _, password = decoded.partition(":")
                if hmac.compare_digest(token, password):
                    return True
            except Exception:  # noqa: BLE001
                return False
        # A token query parameter keeps curl usage simple on a phone.
        query = parse_qs(urlparse(self.path).query)
        supplied = (query.get("token") or [""])[0]
        return bool(token) and hmac.compare_digest(token, supplied)

    def _require_basic(self) -> bool:
        if self._basic_ok():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="CRM"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _static(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name or ""):
            return self._send(404, {"error": "not found"})
        path = os.path.join(CACHE_DIR, name)
        if not os.path.isfile(path):
            path = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = "text/css; charset=utf-8" if name.endswith(".css") else "application/octet-stream"
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        gz_path = path + ".gz"
        headers = {"Cache-Control": "public, max-age=604800, immutable"}
        if accepts_gzip and os.path.exists(gz_path):
            with open(gz_path, "rb") as fh:
                data = fh.read()
            headers["Content-Encoding"] = "gzip"
        else:
            with open(path, "rb") as fh:
                data = fh.read()
        return self._send_bytes(200, data, ctype, headers)

    # -- GET ---------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health":
            return self._send(200, self.bridge.health())
        if path == "/status":
            return self._send(200, {"stats": self.bridge.stats,
                                    "queue": self.bridge.store.pending_count(),
                                    "crm": self.bridge.crm.stats(),
                                    "channels": list(self.bridge.cfg.newsletter_jids)})
        if path == "/mcp":
            return self._send(405, {"error": "use POST /mcp"}, {"Allow": "POST"})
        if path == "/":
            return self._redirect("/ui")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])

        if path.startswith("/ui"):
            if not self._require_basic():
                return None
            return self._ui_get(path, query)

        return self._send(404, {"error": "not found"})

    def _ui_get(self, path: str, query: dict):
        crm = self.bridge.crm
        ui.TZ_OFFSET = self.bridge.cfg.tz_offset
        ui.set_unread(crm.unread_notifications())
        if path in ("/ui", "/ui/"):
            scheduled = crm.list_posts("scheduled", 10) + crm.list_posts("review", 10)
            scheduled.sort(key=lambda p: p.get("scheduled_at") or 0)
            return self._send_html(200, ui.dashboard(
                stats=crm.stats(), scheduled=scheduled, followups=crm.followups(0),
                unread=crm.unread_count(), metrics=crm.channel_metrics(7)))
        if path == "/ui/notifications":
            return self._send_html(200, ui.notifications_page(crm.notifications(60)))
        if path == "/ui/content":
            status = (query.get("status") or [""])[0]
            return self._send_html(200, ui.content_page(crm.list_posts(status or None, 30), status))
        if path == "/ui/contacts":
            q = (query.get("q") or [""])[0]
            return self._send_html(200, ui.contacts_page(crm.list_contacts(q or None)))
        if path == "/ui/deals":
            return self._send_html(200, ui.deals_page(crm.list_deals()))
        if path.startswith("/ui/post/"):
            post_id = path.rsplit("/", 1)[-1]
            post = crm.get_channel_post(post_id)
            if not post:
                return self._send(404, {"error": "post not found"})
            channel = crm.get_channel_info(post["channel_jid"])
            return self._send_html(200, ui.post_page(post, crm.post_history(post_id, 30), channel))
        if path == "/ui/channel":
            jid = (self.bridge.cfg.newsletter_jids or ("",))[0]
            return self._send_html(200, ui.channel_page(
                crm.get_channel_info(jid), crm.channel_summary(30),
                crm.daily_series(14), crm.list_posts("published", 20)))
        if path == "/ui/metrics":
            days = int((query.get("days") or ["7"])[0] or 7)
            return self._send_html(200, ui.metrics_page(crm.channel_metrics(days)))
        if path == "/ui/manifest.webmanifest":
            return self._send_bytes(200, json.dumps(ui.MANIFEST, ensure_ascii=False).encode("utf-8"),
                                    "application/manifest+json")
        return self._send(404, {"error": "not found"})

    # -- POST --------------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        raw = self._read_body()

        if path == "/webhook/gowa":
            if not verify_signature(self.bridge.cfg.gowa_webhook_secret, raw,
                                    self.headers.get("X-Hub-Signature-256")):
                log.warning("rejected GOWA webhook: bad signature")
                return self._send(401, {"error": "invalid signature"})
            try:
                event = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid json"})
            try:
                result = self.bridge.handle_gowa_event(event)
            except Exception as exc:  # noqa: BLE001 - must not 500 into GOWA retries
                log.exception("gowa event failed")
                return self._send(200, {"ok": False, "error": str(exc)[:200]})
            return self._send(200, result)

        if path == "/mcp":
            if not self._bearer_ok():
                return self._send(401, {"error": "unauthorized"})
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "Parse error"}})
            headers = {}
            if isinstance(payload, dict) and payload.get("method") == "initialize":
                headers["Mcp-Session-Id"] = new_session_id()
            if isinstance(payload, list):
                responses = [r for r in (self.mcp.handle(item) for item in payload
                                         if isinstance(item, dict)) if r is not None]
                return self._send(200, responses, headers)
            if not isinstance(payload, dict):
                return self._send(400, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32600, "message": "Invalid Request"}})
            result = self.mcp.handle(payload)
            if result is None:
                return self._send_no_content(202)
            return self._send(200, result, headers)

        if path == "/hook/publish":
            if not self._bearer_ok():
                return self._send(401, {"error": "unauthorized"})
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid json"})
            post_id = body.get("postId") or body.get("id")
            if not post_id:
                return self._send(400, {"error": "postId required"})
            post = self.bridge.crm.get_channel_post(post_id)
            if not post:
                return self._send(404, {"error": "post not found"})
            at = to_epoch(body.get("at")) or int(time.time())
            self.bridge.crm.update_channel_post(
                post_id, {"status": "scheduled", "scheduled_at": at})
            queued = self.bridge.store.enqueue("publish", post_id, {"postId": post_id})
            self.bridge.drain_outbox()
            return self._send(200, {"ok": True, "queued": queued, "postId": post_id})

        if path.startswith("/ui"):
            if not self._require_basic():
                return None
            return self._ui_post(path, raw)

        return self._send(404, {"error": "not found"})

    def _ui_post(self, path: str, raw: bytes):
        crm = self.bridge.crm
        form = ui.parse_form(raw)
        if path == "/ui/content/new":
            crm.create_channel_post({
                "channel_jid": (self.bridge.cfg.newsletter_jids or ("",))[0],
                "title": form.get("title") or "",
                "body": form.get("body") or "",
                "status": "draft",
                "created_by": "human",
            })
            return self._redirect("/ui/content")
        if path == "/ui/content/schedule":
            at = ui.parse_local_datetime(form.get("at") or "")
            if form.get("id") and at:
                crm.schedule_post(form["id"], at, approved=True)
            return self._redirect("/ui/content")
        if path == "/ui/content/publish":
            post_id = form.get("id")
            if post_id:
                crm.update_channel_post(post_id, {"status": "scheduled", "scheduled_at": int(time.time())})
                self.bridge.store.enqueue("publish", post_id, {"postId": post_id})
                self.bridge.drain_outbox()
            return self._redirect("/ui/content")
        if path == "/ui/contacts/new":
            if form.get("phone"):
                crm.upsert_contact(form["phone"], name=form.get("name"), org=form.get("org"))
            return self._redirect("/ui/contacts")
        if path == "/ui/deals/new":
            contact_id = None
            if form.get("contact_phone"):
                contact = crm.find_contact_by_phone(form["contact_phone"])
                contact_id = contact["id"] if contact else None
            value = None
            try:
                value = float(form["value"]) if form.get("value") else None
            except ValueError:
                value = None
            if form.get("title"):
                crm.upsert_deal(form["title"], contact_id=contact_id, value=value,
                                stage=form.get("stage"))
            return self._redirect("/ui/deals")
        if path == "/ui/notifications/read":
            self.bridge.crm.mark_notifications_read()
            return self._redirect("/ui/notifications")
        if path == "/ui/channel/refresh":
            self.bridge.refresh_channel_info()
            return self._redirect("/ui/channel")
        if path == "/ui/followup/done":
            if form.get("id"):
                crm.complete_activity(form["id"])
            return self._redirect("/ui")
        return self._send(404, {"error": "not found"})


def make_server(cfg: Config, bridge: Bridge) -> ThreadingHTTPServer:
    mcp = McpServer(bridge.crm, bridge.gowa, bridge.store, bridge.health,
                    can_publish=cfg.agent_can_publish)
    handler = type("BoundHandler", (Handler,), {"bridge": bridge, "mcp": mcp})
    server = ThreadingHTTPServer((cfg.bridge_host, cfg.bridge_port), handler)
    server.daemon_threads = True
    return server


def main() -> int:
    cfg = Config.load()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    try:
        ui.write_stylesheet(CACHE_DIR)
    except OSError as exc:  # read-only FS: keep serving the vendored copy
        log.warning("stylesheet cache unavailable: %s", exc)
    bridge = Bridge(cfg)
    server = make_server(cfg, bridge)
    bridge.start_workers()
    log.info("crm listening on http://%s:%d (db=%s, channels=%d, agent_can_publish=%s)",
             cfg.bridge_host, cfg.bridge_port, cfg.db_path,
             len(cfg.newsletter_jids), cfg.agent_can_publish)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        bridge.stop()
        server.server_close()
        bridge.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
