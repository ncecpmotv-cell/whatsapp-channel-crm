"""GOWA REST client + webhook signature verification (stdlib only)."""
from __future__ import annotations

import hashlib
import hmac
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid


class GowaError(Exception):
    def __init__(self, status: int, body: str, path: str = ""):
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"GOWA {status} on {path}: {body[:300]}")


class GowaClient:
    def __init__(self, base_url: str, device_id: str = "primary", timeout: int = 25,
                 user: str = "", password: str = ""):
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.timeout = timeout
        self.user = user
        self.password = password

    def _call(self, method: str, path: str, payload=None, timeout: int | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("X-Device-Id", self.device_id)
        req.add_header("Accept", "application/json")
        if self.user:
            token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            req.add_header("Authorization", "Basic " + token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
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
    def _post_multipart(self, path: str, fields: dict, files: dict, timeout: int = 120):
        boundary = "----crm" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
            )
        for field, (filename, content, ctype) in files.items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode()
            )
            chunks.append(content)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)

        req = urllib.request.Request(self.base_url + path, data=body, method="POST")
        req.add_header("X-Device-Id", self.device_id)
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        if self.user:
            token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            req.add_header("Authorization", "Basic " + token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise GowaError(exc.code, exc.read().decode("utf-8", "replace"), path) from exc
        except urllib.error.URLError as exc:
            raise GowaError(0, str(exc.reason), path) from exc
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        if str(parsed.get("code", "")).upper() not in ("", "SUCCESS"):
            raise GowaError(200, json.dumps(parsed)[:400], path)
        return parsed

    def send_media(self, kind: str, phone: str, file_path: str, caption: str = ""):
        """kind: image | video | audio | file"""
        with open(file_path, "rb") as fh:
            content = fh.read()
        name = os.path.basename(file_path)
        ctype = {
            "image": "image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else "image/png",
            "video": "video/mp4",
            "audio": "audio/mpeg" if name.lower().endswith(".mp3") else "audio/ogg",
            "file": "application/octet-stream",
        }[kind]
        fields = {"phone": phone}
        if caption:
            fields["caption"] = caption
        return self._post_multipart(f"/send/{kind}", fields, {kind: (name, content, ctype)})

    def send_poll(self, phone: str, question: str, options: list[str], max_answer: int = 1):
        return self._call("POST", "/send/poll", {
            "phone": phone, "question": question, "options": options,
            "max_answer": max(1, min(int(max_answer or 1), len(options))),
        })

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

    def newsletter_info(self, newsletter_id: str):
        return self._call(
            "GET",
            f"/newsletter/info?newsletter_id={urllib.parse.quote(newsletter_id)}",
        )

    def newsletter_message_updates(self, newsletter_id: str, after: int = 1, count: int = 100):
        return self._call(
            "GET",
            f"/newsletter/message-updates?newsletter_id={urllib.parse.quote(newsletter_id)}"
            f"&after={after}&count={count}",
        )

    def device_status(self, timeout: int | None = 3):
        return self._call("GET", f"/devices/{self.device_id}/status", timeout=timeout)


def verify_signature(secret: str, raw_body: bytes, header_value: str | None) -> bool:
    """Verify GOWA's X-Hub-Signature-256 header (sha256=<hex>)."""
    if not secret or not header_value:
        return False
    received = header_value.strip()
    if received.startswith("sha256="):
        received = received[len("sha256="):]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received.strip().lower())
