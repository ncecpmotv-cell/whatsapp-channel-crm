"""GOWA REST client + webhook signature verification (stdlib only)."""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request


class GowaError(Exception):
    def __init__(self, status: int, body: str, path: str = ""):
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"GOWA {status} on {path}: {body[:300]}")


class GowaClient:
    def __init__(self, base_url: str, device_id: str = "primary", timeout: int = 25):
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.timeout = timeout

    def _call(self, method: str, path: str, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("X-Device-Id", self.device_id)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise GowaError(exc.code, exc.read().decode("utf-8", "replace"), path) from exc
        except urllib.error.URLError as exc:
            raise GowaError(0, str(exc.reason), path) from exc
        try:
            parsed = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        code = str(parsed.get("code", "")).upper()
        if code not in ("", "SUCCESS"):
            raise GowaError(200, json.dumps(parsed)[:400], path)
        return parsed

    # -- messaging ---------------------------------------------------------
    def send_message(self, phone: str, message: str):
        """Send text. `phone` may be a phone number or a channel JID (@newsletter)."""
        return self._call("POST", "/send/message", {"phone": phone, "message": message})

    # -- newsletters -------------------------------------------------------
    def subscribe_live_updates(self, newsletter_id: str):
        return self._call("POST", "/newsletter/live-updates", {"newsletter_id": newsletter_id})

    def list_live_updates(self):
        return self._call("GET", "/newsletter/live-updates")

    def newsletter_messages(self, newsletter_id: str, count: int = 20):
        return self._call(
            "GET",
            f"/newsletter/messages?newsletter_id={urllib.parse.quote(newsletter_id)}&count={count}",
        )

    def newsletter_message_updates(self, newsletter_id: str, after: int = 1, count: int = 100):
        return self._call(
            "GET",
            f"/newsletter/message-updates?newsletter_id={urllib.parse.quote(newsletter_id)}"
            f"&after={after}&count={count}",
        )

    def device_status(self):
        return self._call("GET", f"/devices/{self.device_id}/status")


def verify_signature(secret: str, raw_body: bytes, header_value: str | None) -> bool:
    """Verify GOWA's X-Hub-Signature-256 header (sha256=<hex>)."""
    if not secret or not header_value:
        return False
    received = header_value.strip()
    if received.startswith("sha256="):
        received = received[len("sha256="):]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received.strip().lower())
