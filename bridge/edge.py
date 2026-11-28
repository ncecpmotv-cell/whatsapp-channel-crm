"""Phone → edge-mcp: off-device backups, heartbeat, and Workers AI helpers.

Every call is optional: when EDGE_URL/EDGE_TOKEN are empty the CRM behaves exactly as before.
Failures are logged, never raised into a request path.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("bridge.edge")

MAX_UPLOAD = 25 * 1024 * 1024

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif", ".heic": "image/heic",
         ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg",
         ".m4a": "audio/mp4", ".wav": "audio/wav", ".aac": "audio/aac"}


def _content_type(path: str) -> str:
    return _MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


class EdgeClient:
    def __init__(self, base_url: str = "", token: str = "", timeout: float = 30.0):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = timeout

    def enabled(self) -> bool:
        return bool(self.base_url and self.token)

    def _request(self, method: str, path: str, body: bytes | None = None,
                 headers: dict | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(f"{self.base_url}{path}", data=body, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        # Cloudflare's bot rules answer bare urllib with 1010; a real UA is enough.
        request.add_header("User-Agent", "phone-crm-edge/1.0 (+https://github.com/ncecpmotv-cell/whatsapp-channel-crm)")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except Exception as exc:  # network down, DNS, timeout
            return 0, str(exc).encode()

    def health(self) -> dict:
        if not self.enabled():
            return {"enabled": False}
        status, body = self._request("GET", "/health")
        data: dict[str, Any]
        try:
            data = json.loads(body)
        except ValueError:
            data = {"raw": body[:120].decode(errors="replace")}
        data["status"] = status
        return data

    def heartbeat(self, payload: dict) -> bool:
        if not self.enabled():
            return False
        status, _ = self._request("POST", "/heartbeat", json.dumps(payload).encode(),
                                  {"content-type": "application/json"})
        return status == 200

    def upload_backup(self, path: str) -> dict:
        if not self.enabled():
            return {"ok": False, "error": "edge is not configured"}
        size = os.path.getsize(path)
        if size > MAX_UPLOAD:
            return {"ok": False, "error": f"archive {size} bytes exceeds {MAX_UPLOAD}"}
        with open(path, "rb") as fh:
            body = fh.read()
        name = os.path.basename(path)
        query = urllib.parse.urlencode({"name": name})
        status, response = self._request("POST", f"/backup?{query}", body,
                                         {"content-type": "application/gzip"})
        data: dict[str, Any]
        try:
            data = json.loads(response)
        except ValueError:
            data = {"raw": response[:120].decode(errors="replace")}
        data["ok"] = status == 200 and bool(data.get("ok"))
        data["status"] = status
        return data

    def backups(self) -> list[dict]:
        if not self.enabled():
            return []
        status, body = self._request("GET", "/backup")
        if status != 200:
            return []
        try:
            return json.loads(body).get("backups") or []
        except ValueError:
            return []

    def usage(self) -> dict:
        if not self.enabled():
            return {}
        status, body = self._request("GET", "/usage")
        if status != 200:
            return {}
        try:
            return json.loads(body)
        except ValueError:
            return {}

    def transcribe(self, path: str) -> dict:
        return self._blob("/ai/transcribe", path, 8 * 1024 * 1024)

    def caption(self, path: str) -> dict:
        return self._blob("/ai/caption", path, 6 * 1024 * 1024)

    def _blob(self, endpoint: str, path: str, cap: int) -> dict:
        if not self.enabled():
            return {"ok": False, "error": "edge is not configured"}
        full = os.path.abspath(os.path.expanduser(path or ""))
        if not os.path.isfile(full):
            return {"ok": False, "error": "file not found"}
        if os.path.getsize(full) > cap:
            return {"ok": False, "error": f"file exceeds {cap // (1024 * 1024)}MB"}
        with open(full, "rb") as fh:
            body = fh.read()
        status, response = self._request("POST", endpoint, body,
                                         {"content-type": _content_type(full)})
        data: dict[str, Any]
        try:
            data = json.loads(response)
        except ValueError:
            data = {"raw": response[:200].decode(errors="replace")}
        data.setdefault("ok", status == 200)
        data["status"] = status
        return data


def from_config(cfg) -> EdgeClient:
    return EdgeClient(getattr(cfg, "edge_url", ""), getattr(cfg, "edge_token", ""))
