"""HTTP front door for the bridge (stdlib http.server).

Endpoints
  POST /webhook/gowa      GOWA events, HMAC-verified (X-Hub-Signature-256)
  POST /webhook/espocrm   EspoCRM hook, bearer-token authenticated
  GET  /health            dependency + queue status
  GET  /status            counters and monitored channels
"""
from __future__ import annotations

import hmac
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import Config
from gowa import verify_signature
from mcp import McpServer, new_session_id
from service import Bridge

log = logging.getLogger("bridge.http")
MAX_BODY = 1_048_576  # 1 MiB


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "GowaEspoBridge/1.0"
    bridge: Bridge  # injected by make_server
    mcp: McpServer  # injected by make_server

    # -- helpers -----------------------------------------------------------
    def _send(self, status: int, payload, headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

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

    def log_message(self, fmt, *args):  # quieter, structured-ish
        log.info("%s - %s", self.address_string(), fmt % args)

    def _token_ok(self) -> bool:
        token = self.bridge.cfg.bridge_token or ""
        supplied = self.headers.get("X-Bridge-Token") or ""
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        return bool(token) and hmac.compare_digest(token, supplied)

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            return self._send(200, self.bridge.health())
        if path == "/status":
            return self._send(200, {"stats": self.bridge.stats,
                                    "queue": self.bridge.store.pending_count(),
                                    "channels": list(self.bridge.cfg.newsletter_jids)})
        if path == "/mcp":
            # Streamable-HTTP servers that do not offer a GET/SSE stream must say so.
            return self._send(405, {"error": "use POST /mcp"}, {"Allow": "POST"})
        if path == "/":
            return self._send(200, {"service": "gowa-espocrm-bridge",
                                    "endpoints": ["/webhook/gowa", "/webhook/espocrm",
                                                  "/mcp", "/health"]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
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
            if not self._token_ok():
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
                responses = []
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    result = self.mcp.handle(item)
                    if result is not None:
                        responses.append(result)
                return self._send(200, responses, headers)
            if not isinstance(payload, dict):
                return self._send(400, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32600, "message": "Invalid Request"}})
            result = self.mcp.handle(payload)
            if result is None:
                return self._send_no_content(202)
            return self._send(200, result, headers)

        if path == "/admin/sync":
            if not self._token_ok():
                return self._send(401, {"error": "unauthorized"})
            try:
                channels = self.bridge.sync_channels()
                counters = self.bridge.sync_counters()
            except Exception as exc:  # noqa: BLE001
                log.exception("manual sync failed")
                return self._send(500, {"ok": False, "error": str(exc)[:200]})
            return self._send(200, {"ok": True, "newPosts": channels, "updatedCounters": counters})

        if path == "/webhook/espocrm":
            if not self._token_ok():
                return self._send(401, {"error": "unauthorized"})
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid json"})
            try:
                result = self.bridge.handle_espocrm_hook(body)
            except Exception as exc:  # noqa: BLE001
                log.exception("espocrm hook failed")
                return self._send(500, {"ok": False, "error": str(exc)[:200]})
            return self._send(200 if result.get("ok") else 400, result)

        return self._send(404, {"error": "not found"})


def make_server(cfg: Config, bridge: Bridge) -> ThreadingHTTPServer:
    mcp = McpServer(bridge.espo, bridge.gowa, bridge.store, bridge.health)
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
    bridge = Bridge(cfg)
    server = make_server(cfg, bridge)
    bridge.start_workers()
    log.info("bridge listening on http://%s:%d (device=%s, channels=%d)",
             cfg.bridge_host, cfg.bridge_port, "primary", len(cfg.newsletter_jids))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        bridge.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
