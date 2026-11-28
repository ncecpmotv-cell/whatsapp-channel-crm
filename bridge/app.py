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
import hashlib
import hmac
import ipaddress
import json
import logging
import mimetypes
import os
import re
import struct
import sys
import threading
import time
import time as _time
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ui
from config import Config
from gowa import verify_signature
from mcp import McpServer, new_session_id
from service import Bridge, to_epoch

log = logging.getLogger("bridge.http")
MAX_BODY = 26 * 1024 * 1024  # 26 MiB: 20 MiB media + multipart overhead
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# Writable cache for generated assets (the code dir is mounted read-only).
CACHE_DIR = os.environ.get("STATIC_CACHE", "/var/crm/static")
MEDIA_DIR = os.environ.get("MEDIA_DIR", "/var/crm/media")


def _host_key(value: str) -> str:
    """normalise a host/Origin to host[:port], dropping default ports and schemes"""
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        parsed = urlparse(value)
        host, port = parsed.hostname or "", parsed.port
    else:
        host, _, raw_port = value.partition("/")[0].partition(":")
        try:
            port = int(raw_port) if raw_port else None
        except ValueError:
            port = None
    if not host:
        return ""
    if port in (None, 80, 443):
        return host
    return f"{host}:{port}"


def origin_allowed(headers, env=None) -> bool:
    """Same-origin check that survives reverse proxies (tailscale serve, tunnels).

    The browser sends Origin for POSTs, but the proxy decides which Host the app
    sees, so the two disagree by design. Accept every host we are reachable on:
    Host, X-Forwarded-Host, PUBLIC_BASE_URL and TRUSTED_ORIGINS.
    """
    env = os.environ if env is None else env
    site = (headers.get("Sec-Fetch-Site") or "").lower()
    if site and site not in ("same-origin", "same-site", "none"):
        return False
    origin = (headers.get("Origin") or "").strip()
    if not origin or origin.lower() == "null":
        # ``Origin: null`` is what WebViews (Telegram, some Android browsers) send
        # for same-origin form posts. Treat it like a missing Origin: the CSRF
        # token check still runs, and Sec-Fetch-Site was already validated above.
        return True
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    wanted = _host_key(parsed.netloc)
    candidates = {
        _host_key(headers.get("Host") or ""),
        _host_key(headers.get("X-Forwarded-Host") or ""),
    }
    for key in ("PUBLIC_BASE_URL", "TRUSTED_ORIGINS"):
        for item in (env.get(key) or "").split(","):
            candidates.add(_host_key(item))
    candidates.discard("")
    if wanted in candidates:
        return True
    # MagicDNS names in the same tailnet (smartp, pot-lx1af, …): the owner may
    # open the UI under any of them, and the proxy rewrites Host either way.
    hostname = wanted.rsplit(":", 1)[0]
    if hostname == "localhost":
        return True
    domain = (env.get("ALLOW_TAILNET_DOMAIN") or "").strip().lower().lstrip(".")
    if domain and (hostname == domain or hostname.endswith("." + domain)):
        return True
    # The same UI is reachable by tailscale IP and by loopback in a browser on
    # the phone itself; both are inside the tailnet, so accept them.
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read width/height from PNG/GIF/JPEG headers so the page reserves space (CLS)."""
    if len(data) < 24:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            i += 2 + seg_len
    return None


MEDIA_NAME_RE = re.compile(
    r"[a-f0-9]{8,32}\.(jpg|jpeg|png|webp|gif|mp4|mov|webm|mp3|ogg|m4a|opus|wav|pdf|doc|docx|xls|xlsx|ppt|pptx|txt|csv|zip)",
    re.IGNORECASE)
_AUTH_FAILS: dict[str, list[float]] = {}
_AUTH_LOCK = threading.Lock()
AUTH_MAX_FAILS = 10
AUTH_WINDOW = 300.0

ALLOWED_EXT = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "video": {".mp4", ".mov", ".webm"},
    "audio": {".mp3", ".ogg", ".m4a", ".opus", ".wav"},
    "file": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".zip"},
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PhoneCrm/2.0"
    bridge: Bridge
    mcp: McpServer

    # -- helpers -----------------------------------------------------------
    def _send_bytes(self, status: int, body: bytes, content_type: str,
                    headers: dict | None = None, compress: bool = True,
                    validators: bool = True) -> None:
        extra = dict(headers or {})
        etag = None
        if validators and status == 200 and self.command == "GET" and body:
            etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
            extra.setdefault("ETag", etag)
            extra.setdefault("Cache-Control", "no-cache")
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                for key, value in extra.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if compress and accepts_gzip and len(body) >= 1024 and "Content-Encoding" not in extra:
            body = gzip.compress(body, 6)
            extra["Content-Encoding"] = "gzip"
            extra.setdefault("Vary", "Accept-Encoding")
        extra.setdefault("X-Content-Type-Options", "nosniff")
        extra.setdefault("Referrer-Policy", "no-referrer")
        extra.setdefault("X-Frame-Options", "DENY")
        extra.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        if content_type.startswith("text/html"):
            extra.setdefault("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in extra.items():
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

    def _parse_multipart(self, raw: bytes) -> tuple[dict, dict]:
        ctype = self.headers.get("Content-Type") or ""
        message = BytesParser(policy=email_policy).parsebytes(
            b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
        fields: dict[str, str] = {}
        files: dict[str, tuple] = {}
        for part in message.iter_parts():
            raw_name = part.get_param("name", header="content-disposition")
            name = raw_name if isinstance(raw_name, str) else None
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                files[name] = (filename, payload, part.get_content_type())
            else:
                fields[name] = payload.decode("utf-8", "replace")
        return fields, files

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        if length <= 0 or length > MAX_BODY:
            return b""
        return self.rfile.read(length)

    def _too_large(self) -> bool:
        try:
            return int(self.headers.get("Content-Length") or 0) > MAX_BODY
        except ValueError:
            return False

    def _same_origin(self) -> bool:
        """Blocks cross-site form posts (Basic credentials ride along)."""
        cfg = self.bridge.cfg
        return origin_allowed(self.headers, {
            "PUBLIC_BASE_URL": cfg.public_base_url,
            "TRUSTED_ORIGINS": cfg.trusted_origins,
            "ALLOW_TAILNET_DOMAIN": cfg.allow_tailnet_domain,
        })

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def _bearer_token(self) -> str:
        supplied = self.headers.get("X-Bridge-Token") or ""
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        return supplied

    def _bearer_ok(self) -> bool:
        """The human token and the agent token are both valid — but not equally trusted."""
        cfg = self.bridge.cfg
        supplied = self._bearer_token()
        token = cfg.bridge_token or ""
        if token and supplied and hmac.compare_digest(token, supplied):
            return True
        agent = getattr(cfg, "agent_token", "") or ""
        return bool(agent and supplied) and hmac.compare_digest(agent, supplied)

    def _caller(self) -> str:
        agent = getattr(self.bridge.cfg, "agent_token", "") or ""
        supplied = self._bearer_token()
        if agent and supplied and hmac.compare_digest(agent, supplied):
            return "agent"
        return "human"

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
        return False

    def _csrf_token(self) -> str:
        token = self.bridge.cfg.bridge_token or ""
        return hashlib.sha256((token + "|crm-csrf-v1").encode()).hexdigest()[:32] if token else ""

    def _csrf_ok(self, raw: bytes) -> bool:
        expected = self._csrf_token()
        if not expected:
            return True
        supplied = self.headers.get("X-CSRF-Token") or ""
        if not supplied and raw:
            try:
                if (self.headers.get("Content-Type") or "").startswith("multipart/form-data"):
                    supplied = (self._parse_multipart(raw)[0].get("csrf") or "")
                else:
                    supplied = (self._form(raw)[0].get("csrf") or "")
            except Exception:  # noqa: BLE001 - malformed body -> no token
                supplied = ""
        return bool(supplied) and hmac.compare_digest(expected, supplied)

    def _auth_throttled(self) -> bool:
        ip = self.client_address[0]
        now = _time.time()
        with _AUTH_LOCK:
            hits = [t for t in _AUTH_FAILS.get(ip, []) if now - t < AUTH_WINDOW]
            _AUTH_FAILS[ip] = hits
            return len(hits) >= AUTH_MAX_FAILS

    def _note_auth_failure(self) -> None:
        ip = self.client_address[0]
        with _AUTH_LOCK:
            _AUTH_FAILS.setdefault(ip, []).append(_time.time())

    def _require_basic(self) -> bool:
        if self._auth_throttled():
            self.send_response(429)
            self.send_header("Retry-After", "300")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if self._basic_ok():
            with _AUTH_LOCK:
                _AUTH_FAILS.pop(self.client_address[0], None)
            return True
        self._note_auth_failure()
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="CRM"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _media(self, name: str):
        if not MEDIA_NAME_RE.fullmatch(name or ""):
            return self._send(404, {"error": "not found"})
        path = os.path.join(MEDIA_DIR, name)
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            data = fh.read()
        return self._send_bytes(200, data, ctype,
                                {"Cache-Control": "private, max-age=86400"},
                                compress=False, validators=False)

    def _static(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name or ""):
            return self._send(404, {"error": "not found"})
        path = os.path.join(CACHE_DIR, name)
        if not os.path.isfile(path):
            path = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = ("text/css; charset=utf-8" if name.endswith(".css")
                 else "text/javascript; charset=utf-8" if name.endswith(".js")
                 else "application/octet-stream")
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        gz_path = path + ".gz"
        headers = {"Cache-Control": "public, max-age=604800, immutable"}
        with open(path, "rb") as fh:
            data = fh.read()
        if accepts_gzip and os.path.exists(gz_path):
            with open(gz_path, "rb") as fh:
                data = fh.read()
            headers["Content-Encoding"] = "gzip"
        elif accepts_gzip and len(data) >= 1024:
            data = gzip.compress(data, 9)
            headers["Content-Encoding"] = "gzip"
            headers["Vary"] = "Accept-Encoding"
        return self._send_bytes(200, data, ctype, headers, compress=False, validators=False)

    # -- GET ---------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health":
            cfg = self.bridge.cfg
            # Booleans only: enough to debug the origin guard through a proxy.
            guard = {"public_url": bool(cfg.public_base_url),
                     "trusted": bool(cfg.trusted_origins),
                     "tailnet": bool(cfg.allow_tailnet_domain)}
            try:
                from notify import describe as push_state
                push = push_state(cfg)
            except Exception:
                push = {"enabled": False}
            return self._send(200, {"ok": self.bridge.crm.ping(),
                                    "crm": self.bridge.crm.ping(),
                                    "origin_guard": guard,
                                    "push": push})
        if path == "/status":
            if not self._bearer_ok():
                return self._send(401, {"error": "unauthorized"})
            return self._send(200, {"stats": self.bridge.stats,
                                    "queue": self.bridge.store.pending_count(),
                                    "crm": self.bridge.crm.stats(),
                                    "channels": list(self.bridge.cfg.newsletter_jids)})
        if path == "/mcp":
            return self._send(405, {"error": "use POST /mcp"}, {"Allow": "POST"})
        if path == "/":
            return self._redirect("/ui")
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Cache-Control", "public, max-age=604800, immutable")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])

        if path.startswith("/ui"):
            if not self._require_basic():
                return None
            if path.startswith("/ui/media/"):
                return self._media(path[len("/ui/media/"):])
            return self._ui_get(path, query)

        return self._send(404, {"error": "not found"})

    FLASH = {
        "created": "أُنشئ المحتوى — أضف موعدًا أو انشره من بطاقته.",
        "updated": "حُدِّث المحتوى.",
        "deleted": "حُذف العنصر.",
        "published": "تم النشر إلى القناة.",
        "scheduled": "تمت الجدولة.",
        "synced": "تمت مزامنة أرشيف القناة.",
        "refreshed": "حُدِّثت بيانات القناة.",
        "contact_added": "أُضيف العميل.",
        "deal_added": "أُضيفت الفرصة.",
        "done": "أُنجزت المتابعة.",
        "read": "قُرئت الإشعارات.",
        "cancelled": "أُلغي العنصر — بقي في الأرشيف بحالة ملغى.",
        "restored": "أُعيد العنصر كمسودة.",
        "status": "حُدِّثت الحالة.",
        "plan_approved": "اعتُمدت الخطة — أُنشئت المسودات وأُجيدلت مواعيدها.",
    }

    def _ui_get(self, path: str, query: dict):
        ui.set_flash(self.FLASH.get((query.get("ok") or [""])[0], ""))
        ui.set_header_action("")
        ui.set_csrf(self._csrf_token())
        crm = self.bridge.crm
        ui.TZ_OFFSET = self.bridge.cfg.tz_offset
        ui.set_unread(crm.unread_notifications())
        if path in ("/ui", "/ui/"):
            scheduled = crm.list_posts("scheduled", 10)
            scheduled.sort(key=lambda p: p.get("scheduled_at") or 0)
            insights = crm.content_insights(30)
            stats = crm.stats()
            reports = {
                "insights": insights,
                "times": (crm.posting_times(90).get("best") or [])[:3],
                "gaps": (crm.content_gaps(60).get("opportunities") or [])[:3],
                "growth": crm.channel_growth(30),
                "angles": crm.list_angles("new", 3),
                "angle_count": crm.count_angles(),
                "ops": {
                    "failed": crm.count_posts("failed"),
                    "drafts": crm.count_posts("draft"),
                    "backup": ui.fmt_ts(crm.store.get_meta("last_backup_at")),
                    "heartbeat": ui.fmt_ts(crm.store.get_meta("last_heartbeat_at")),
                },
            }
            return self._send_html(200, ui.dashboard(
                stats=stats, scheduled=scheduled, followups=crm.followups(0),
                unread=crm.unread_count(), metrics=crm.channel_metrics(7),
                plan=crm.get_plan(), reports=reports))
        if path == "/ui/capabilities":
            import orchestrator
            from mcp import TOOLS as MCP_TOOLS
            caps = orchestrator.capabilities(crm, getattr(self.bridge.cfg, "picoclaw_home", ""),
                                             tools_count=len(MCP_TOOLS))
            return self._send_html(200, ui.capabilities_page(caps))
        if path == "/ui/radar":
            last = crm.store.get_meta("last_radar_scan") or ""
            notice = (query.get("ok") or [""])[0]
            return self._send_html(200, ui.radar_page(
                crm.list_angles("new", 30),
                f"آخر مسح: {ui.fmt_ts(last)}" if last else "لم يُمسح بعد",
                notice))
        if path == "/ui/brand":
            notice = {"saved": "حُفظت الهوية — الوكيل سيرى النسخة الجديدة فورًا.",
                      "invalid": "قيمة غير صالحة: تحقق من الألوان والمقاسات.",
                      "nothing": "لا تغييرات للحفظ."}.get((query.get("ok") or [""])[0], "")
            return self._send_html(200, ui.brand_page(crm.get_brand(), notice))
        if path == "/ui/edge":
            state = {"enabled": False}
            try:
                from edge import from_config
                client = from_config(self.bridge.cfg)
                if client.enabled():
                    state = client.health()
                    state["last_heartbeat_at"] = crm.store.get_meta("last_heartbeat_at")
                    state["last_offsite_at"] = crm.store.get_meta("last_offsite_at")
                    state["last_offsite_name"] = crm.store.get_meta("last_offsite_name")
                    listing = client.backups()
                    state["offsite_backups"] = len(listing)
                    state["usage"] = client.usage()
            except Exception:
                pass
            return self._send_html(200, ui.edge_page(state))
        if path == "/ui/search":
            term = (query.get("q") or [""])[0].strip()
            results = crm.semantic_search(term, 20)["results"] if term else []
            return self._send_html(200, ui.search_page(term, results))
        if path == "/ui/media":
            files = []
            usage: dict[str, list[str]] = {}
            for post in crm._all("SELECT title, media_path FROM crm_posts "
                                 "WHERE COALESCE(media_path,'') != ''"):
                usage.setdefault(os.path.basename(post["media_path"]), []).append(
                    (post["title"] or "")[:24])
            if os.path.isdir(MEDIA_DIR):
                for name in sorted(os.listdir(MEDIA_DIR)):
                    full = os.path.join(MEDIA_DIR, name)
                    if not os.path.isfile(full):
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    kind = next((k for k, exts in ALLOWED_EXT.items() if ext in exts), "file")
                    files.append({"name": name, "kind": kind,
                                  "kb": round(os.path.getsize(full) / 1024),
                                  "titles": usage.get(name, [])})
            return self._send_html(200, ui.media_page(files))
        if path == "/ui/plan":
            drafts = {p["id"] for p in crm.list_posts("draft", 200)}
            return self._send_html(200, ui.plan_page(crm.get_plan(), draft_ids=drafts))
        if path == "/ui/notifications":
            return self._send_html(200, ui.notifications_page(crm.notifications(60)))
        if path == "/ui/content":
            status = (query.get("status") or [""])[0]
            error = (query.get("error") or [""])[0]
            try:
                page = max(1, int((query.get("page") or ["1"])[0]))
            except ValueError:
                page = 1
            per_page = 15
            total = crm.count_posts(status or None)
            pages = max(1, (total + per_page - 1) // per_page)
            page = min(page, pages)
            rows = crm.list_posts(status or None, per_page, (page - 1) * per_page)
            return self._send_html(200, ui.content_page(rows, status, error, page, pages))
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
            notice = {"no_date": "أدخل موعد النشر أولًا ثم اضغط «جدولة».",
                      "published": "لا يمكن تعديل منشور منشور على القناة.",
                      "not_editable": "هذه الحالة لا تسمح بالتعديل."}.get(
                          (query.get("error") or [""])[0], "")
            return self._send_html(200, ui.post_page(post, crm.post_history(post_id, 30), channel, notice))
        if path == "/ui/channel":
            jid = (self.bridge.cfg.newsletter_jids or ("",))[0]
            return self._send_html(200, ui.channel_page(
                crm.get_channel_info(jid), crm.channel_summary(30),
                crm.daily_series(14), crm.list_posts("published", 20),
                growth=crm.channel_growth(90)))
        if path == "/ui/metrics":
            try:
                days = int((query.get("days") or ["7"])[0] or 7)
            except ValueError:
                days = 7
            days = max(1, min(days, 365))
            return self._send_html(200, ui.metrics_page(crm.channel_metrics(days)))
        if path == "/ui/manifest.webmanifest":
            return self._send_bytes(200, json.dumps(ui.MANIFEST, ensure_ascii=False).encode("utf-8"),
                                    "application/manifest+json")
        return self._send(404, {"error": "not found"})

    # -- POST --------------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        if self._too_large():
            return self._send(413, {"error": "payload too large (max 20 MiB media)"})
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
            caller = self._caller()
            if isinstance(payload, list):
                responses = [r for r in (self.mcp.handle(item, caller=caller) for item in payload
                                         if isinstance(item, dict)) if r is not None]
                return self._send(200, responses, headers)
            if not isinstance(payload, dict):
                return self._send(400, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32600, "message": "Invalid Request"}})
            result = self.mcp.handle(payload, caller=caller)
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
            if not self._same_origin():
                detail = {
                    "origin": self.headers.get("Origin"),
                    "host": self.headers.get("Host"),
                    "forwarded_host": self.headers.get("X-Forwarded-Host"),
                    "site": self.headers.get("Sec-Fetch-Site"),
                }
                log.warning("origin rejected: path=%s %s", path, detail)
                return self._send(403, {"error": "cross-site request rejected",
                                        "detail": {k: v for k, v in detail.items() if v}})
            if not self._csrf_ok(raw):
                return self._send(403, {"error": "invalid csrf token"})
            return self._ui_post(path, raw)

        return self._send(404, {"error": "not found"})

    def _form(self, raw: bytes) -> tuple[dict, dict]:
        ctype = self.headers.get("Content-Type") or ""
        if ctype.startswith("multipart/form-data"):
            return self._parse_multipart(raw)
        return ui.parse_form(raw), {}

    def _create_content(self, crm, raw: bytes):
        fields, files = self._form(raw)
        kind = (fields.get("type") or "text").strip().lower()
        title = (fields.get("title") or "").strip()
        body = (fields.get("body") or "").strip()
        url = (fields.get("url") or "").strip()
        at = ui.parse_local_datetime(fields.get("at") or "")
        meta = None
        media_path = None

        if kind == "poll":
            options = [line.strip() for line in (fields.get("options") or "").splitlines() if line.strip()]
            if len(options) < 2:
                return self._redirect("/ui/content?error=poll_options")
            meta = json.dumps({"options": options}, ensure_ascii=False)
            body = body or title
        elif kind == "link":
            if not url.lower().startswith(("http://", "https://")):
                return self._redirect("/ui/content?error=link")
            body = (body + "\n" + url).strip()
        elif kind in ("image", "video", "audio", "file"):
            upload = files.get("media")
            if not upload or not upload[1]:
                return self._redirect("/ui/content?error=media_required")
            filename, payload, _mime = upload
            if len(payload) > 20 * 1024 * 1024:
                return self._redirect("/ui/content?error=media_too_big")
            ext = os.path.splitext(filename or "")[1].lower()
            if ext not in ALLOWED_EXT.get(kind, set()):
                return self._redirect("/ui/content?error=media_type")
            os.makedirs(MEDIA_DIR, exist_ok=True)
            media_path = os.path.join(MEDIA_DIR, uuid.uuid4().hex[:12] + ext)
            with open(media_path, "wb") as fh:
                fh.write(payload)
            if kind == "image":
                dims = image_dimensions(payload)
                if dims:
                    try:
                        payload_meta = json.loads(meta or "{}")
                    except json.JSONDecodeError:
                        payload_meta = {}
                    payload_meta.update(width=dims[0], height=dims[1])
                    meta = json.dumps(payload_meta, ensure_ascii=False)
        elif kind not in ("text",):
            kind = "text"

        post = crm.create_channel_post({
            "channel_jid": (self.bridge.cfg.newsletter_jids or ("",))[0],
            "title": title,
            "body": body,
            "status": "draft",
            "media_type": kind,
            "media_path": media_path,
            "meta": meta,
            "created_by": "human",
        })
        if at:
            crm.schedule_post(post["id"], at, approved=True)
        return self._redirect(f"/ui/post/{post['id']}?ok=created")

    def _edit_content(self, crm, raw: bytes):
        fields, _ = self._form(raw)
        post_id = fields.get("id")
        if not post_id:
            return self._redirect("/ui/content")
        try:
            crm.update_channel_post(post_id, {
                "title": (fields.get("title") or "").strip() or None,
                "body": (fields.get("body") or "").strip() or None,
            }, allowed_statuses=("draft", "scheduled"))
            at = ui.parse_local_datetime(fields.get("at") or "")
            if at:
                crm.schedule_post(post_id, at, approved=True)
        except (ValueError, PermissionError):
            return self._redirect(f"/ui/post/{post_id}?error=not_editable")
        return self._redirect(f"/ui/post/{post_id}?ok=updated")

    def _cancel_content(self, crm, raw: bytes):
        fields, _ = self._form(raw)
        post_id = fields.get("id")
        if not post_id:
            return self._redirect("/ui/content")
        try:
            crm.cancel_post(post_id)
            return self._redirect("/ui/content?ok=cancelled")
        except (ValueError, PermissionError):
            return self._redirect(f"/ui/post/{post_id}?error=published")

    def _restore_content(self, crm, raw: bytes):
        fields, _ = self._form(raw)
        post_id = fields.get("id")
        if not post_id:
            return self._redirect("/ui/content")
        try:
            crm.restore_post(post_id)
            return self._redirect("/ui/content?ok=restored")
        except (ValueError, PermissionError):
            return self._redirect("/ui/content")

    def _set_content_status(self, crm, raw: bytes):
        fields, _ = self._form(raw)
        post_id = fields.get("id")
        target = (fields.get("status") or "").strip()
        if not post_id:
            return self._redirect("/ui/content")
        try:
            if target == "draft":
                crm.update_channel_post(
                    post_id, {"status": "draft", "scheduled_at": None},
                    allowed_statuses=("draft", "scheduled"))
                return self._redirect("/ui/content?ok=status")
        except (ValueError, PermissionError):
            pass
        return self._redirect("/ui/content")

    def _delete_content(self, crm, raw: bytes):
        fields, _ = self._form(raw)
        post_id = fields.get("id")
        if not post_id:
            return self._redirect("/ui/content")
        try:
            crm.delete_post(post_id)
            return self._redirect("/ui/content?ok=deleted")
        except ValueError:
            return self._redirect("/ui/content?error=not_found")
        except PermissionError as exc:
            reason = "published" if "منشور" in str(exc) else "cancel_first"
            return self._redirect(f"/ui/post/{post_id}?error={reason}")

    def _ui_post(self, path: str, raw: bytes):
        crm = self.bridge.crm
        if (self.headers.get("Content-Type") or "").startswith("multipart/form-data"):
            form, _files = self._parse_multipart(raw)
        else:
            form = ui.parse_form(raw)
        if path == "/ui/content/new":
            return self._create_content(crm, raw)
        if path == "/ui/content/edit":
            return self._edit_content(crm, raw)
        if path == "/ui/content/cancel":
            return self._cancel_content(self.bridge.crm, raw)
        if path == "/ui/content/restore":
            return self._restore_content(self.bridge.crm, raw)
        if path == "/ui/content/status":
            return self._set_content_status(self.bridge.crm, raw)
        if path == "/ui/content/delete":
            return self._delete_content(crm, raw)
        if path == "/ui/content/schedule":
            at = ui.parse_local_datetime(form.get("at") or "")
            post_id = form.get("id")
            if post_id and at:
                crm.schedule_post(post_id, at, approved=True)
                return self._redirect(f"/ui/post/{post_id}?ok=scheduled")
            if post_id:
                return self._redirect(f"/ui/post/{post_id}?error=no_date")
            return self._redirect("/ui/content")
        if path == "/ui/content/publish":
            post_id = form.get("id")
            if post_id:
                crm.update_channel_post(post_id, {"status": "scheduled", "scheduled_at": int(time.time())})
                self.bridge.store.enqueue("publish", post_id, {"postId": post_id})
                self.bridge.drain_outbox()
                return self._redirect(f"/ui/post/{post_id}?ok=published")
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
        if path == "/ui/plan/approve":
            form = ui.parse_form(raw)
            plan_id = form.get("id") or ""
            try:
                crm.approve_plan(plan_id, crm.default_channel())
                return self._redirect("/ui/plan?ok=plan_approved")
            except (ValueError, PermissionError):
                return self._redirect("/ui/plan?error=plan")
        if path == "/ui/notifications/read":
            self.bridge.crm.mark_notifications_read()
            return self._redirect("/ui/notifications")
        if path == "/ui/channel/sync":
            self.bridge.sync_channels(count=100)
            self.bridge.sync_counters()
            return self._redirect("/ui/channel")
        if path == "/ui/channel/refresh":
            self.bridge.refresh_channel_info()
            return self._redirect("/ui/channel")
        if path == "/ui/brand/save":
            patch_data, problem = _brand_patch(form)
            if problem:
                return self._redirect(f"/ui/brand?ok={problem}")
            if not patch_data:
                return self._redirect("/ui/brand?ok=nothing")
            crm.set_brand(patch_data)
            return self._redirect("/ui/brand?ok=saved")
        if path == "/ui/radar/scan":
            from radar import scan as radar_scan
            try:
                result = radar_scan(crm, self.bridge.cfg, summarize=True)
                crm.store.set_meta("last_radar_scan", str(int(time.time())))
                code = "radar_ok" if result.get("ok") else "radar_empty"
                log.info("radar scan: %s", {k: result.get(k) for k in ("ok", "scanned", "stored")})
            except Exception:
                log.exception("radar scan failed")
                code = "radar_failed"
            return self._redirect(f"/ui/radar?ok={code}")
        if path == "/ui/radar/use":
            angle = crm.angle(form.get("id", ""))
            if angle:
                post = crm.create_channel_post({
                    "channel_jid": (self.bridge.cfg.newsletter_jids or ("",))[0],
                    "title": (angle.get("angle") or angle.get("title") or "")[:120],
                    "body": f"{angle.get('angle') or ''}\n\nالمصدر: {angle.get('url') or ''}".strip(),
                    "status": "draft",
                    "media_type": "text",
                    "meta": json.dumps({"angle_id": angle["id"], "source_url": angle.get("url")}),
                    "created_by": "human",
                })
                crm.set_angle_status(angle["id"], "used", post["id"])
                return self._redirect(f"/ui/post/{post['id']}?ok=created")
            return self._redirect("/ui/radar?ok=missing")
        if path == "/ui/radar/dismiss":
            crm.set_angle_status(form.get("id", ""), "dismissed")
            return self._redirect("/ui/radar")
        if path == "/ui/followup/done":
            if form.get("id"):
                crm.complete_activity(form["id"])
            return self._redirect("/ui")
        return self._send(404, {"error": "not found"})


HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
FORMAT = re.compile(r"^[0-9]{3,4}x[0-9]{3,4}$")


def _lines(value: str | None, cap: int = 12, length: int = 140) -> list[str]:
    return [row.strip()[:length] for row in (value or "").splitlines() if row.strip()][:cap]


def _number(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(str(value).strip())))
    except (TypeError, ValueError):
        return default


def _brand_patch(form: dict) -> tuple[dict, str]:
    """Validate what the owner typed. Returns (patch, problem-code); problem != '' means reject."""
    current_limits = {"max_chars": 1024, "media_mb": 20, "per_day": 30}
    patch: dict = {}
    palette = {}
    for key in ("deep", "sage", "gold", "beige"):
        raw = (form.get(f"palette_{key}") or "").strip()
        if not raw:
            continue
        if not HEX_COLOR.match(raw):
            return {}, "invalid"
        palette[key] = raw.upper()
    if palette:
        patch["palette"] = palette

    name = (form.get("name") or "").strip()[:80]
    tagline = (form.get("tagline") or "").strip()[:120]
    tone = (form.get("tone") or "").strip()[:400]
    if name or tagline or tone:
        patch.update({k: v for k, v in (("name", name), ("tagline", tagline), ("tone", tone)) if v})

    fonts = {"display": (form.get("font_display") or "").strip()[:40],
             "body": (form.get("font_body") or "").strip()[:40]}
    fonts = {k: v for k, v in fonts.items() if v}
    if fonts:
        patch["fonts"] = fonts

    dos, donts = _lines(form.get("dos")), _lines(form.get("donts"))
    if dos:
        patch["dos"] = dos
    if donts:
        patch["donts"] = donts

    formats = {}
    for kind in ("image", "video"):
        raw = (form.get(f"format_{kind}") or "").strip()
        if not raw:
            continue
        if not FORMAT.match(raw):
            return {}, "invalid"
        formats[kind] = raw
    visual = {}
    if formats:
        visual["formats"] = formats
    mode = (form.get("logo_mode") or "").strip()
    fallback = (form.get("logo_fallback") or "").strip()
    logo = {}
    if mode in ("official_icon", "text_name_only"):
        logo["mode"] = mode
    if fallback in ("text_name", "none"):
        logo["fallback"] = fallback
    never = _lines(form.get("visual_never"))
    if never:
        logo["never"] = never
    if logo:
        visual["logo"] = logo
    text_rules = {}
    if form.get("text_max_words"):
        text_rules["max_words"] = _number(form["text_max_words"], 7, 1, 30)
    if form.get("text_contrast"):
        try:
            text_rules["contrast_min"] = max(3.0, min(21.0, float(form["text_contrast"])))
        except ValueError:
            return {}, "invalid"
    if text_rules:
        visual["text_on_image"] = text_rules
    if visual:
        patch["visual"] = visual

    limits = {}
    if form.get("limit_chars"):
        limits["max_chars"] = _number(form["limit_chars"], current_limits["max_chars"], 200, 4096)
    if form.get("limit_media_mb"):
        limits["media_mb"] = _number(form["limit_media_mb"], current_limits["media_mb"], 1, 20)
    if form.get("limit_per_day"):
        limits["per_day"] = _number(form["limit_per_day"], current_limits["per_day"], 1, 30)
    if limits:
        patch["limits"] = limits
    return patch, ""


def make_server(cfg: Config, bridge: Bridge) -> ThreadingHTTPServer:
    mcp = McpServer(bridge.crm, bridge.gowa, bridge.store, bridge.health,
                    can_publish=cfg.agent_can_publish, cfg=cfg)
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
