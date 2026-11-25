"""Minimal EspoCRM REST client (stdlib only).

Auth uses an API user + X-Api-Key header so the bridge never holds an
administrator password. Every call raises EspoError with the HTTP status
and the response body so failures surface in logs instead of being silent.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class EspoError(Exception):
    def __init__(self, status: int, body: str, path: str = ""):
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"EspoCRM {status} on {path}: {body[:300]}")


class EspoClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # -- transport ---------------------------------------------------------
    def _call(self, method: str, path: str, payload=None, params=None):
        url = f"{self.base_url}/api/v1{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-Api-Key", self.api_key)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            raise EspoError(exc.code, exc.read().decode("utf-8", "replace"), path) from exc
        except urllib.error.URLError as exc:
            raise EspoError(0, str(exc.reason), path) from exc

    @staticmethod
    def _where(field: str, value, kind: str = "equals") -> dict:
        return {
            "where[0][type]": kind,
            "where[0][field]": field,
            "where[0][value]": value,
        }

    # -- contacts ----------------------------------------------------------
    def find_contact_by_phone(self, phone: str):
        params = {"maxSize": 1, **self._where("phoneNumber", phone)}
        result = self._call("GET", "/Contact", params=params)
        items = result.get("list") or []
        return items[0] if items else None

    @staticmethod
    def split_name(display_name: str, fallback: str) -> tuple[str, str]:
        """EspoCRM requires a non-empty lastName, so never send it blank."""
        name = (display_name or "").strip()
        parts = name.split()
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:])
        if len(parts) == 1:
            return "", parts[0]
        return "", fallback

    def create_contact(self, phone: str, first_name: str = "", last_name: str = ""):
        if last_name.strip():
            first, last = (first_name or "").strip(), last_name.strip()
        else:
            first, last = self.split_name(first_name, phone)
        payload = {
            "firstName": first,
            "lastName": last,
            "phoneNumber": phone,
            "description": "Created automatically by the GOWA-EspoCRM bridge",
        }
        return self._call("POST", "/Contact", payload)

    def add_stream_note(self, entity_type: str, entity_id: str, text: str):
        """Append a timeline post.

        EspoCRM 10 silently ignores `POST /{entity}/{id}/stream` (returns false),
        so the Note entity is used instead — verified against 10.1.4.
        """
        return self._call("POST", "/Note", {
            "type": "Post",
            "parentType": entity_type,
            "parentId": entity_id,
            "post": text,
        })

    # -- WhatsAppChannelPost ----------------------------------------------
    def create_channel_post(self, fields: dict):
        return self._call("POST", "/WhatsAppChannelPost", fields)

    def find_channel_post_by_message(self, message_id: str):
        params = {"maxSize": 1, **self._where("messageId", message_id)}
        result = self._call("GET", "/WhatsAppChannelPost", params=params)
        items = result.get("list") or []
        return items[0] if items else None

    def get_channel_post(self, post_id: str):
        return self._call("GET", f"/WhatsAppChannelPost/{post_id}")

    def update_channel_post(self, post_id: str, fields: dict):
        return self._call("PUT", f"/WhatsAppChannelPost/{post_id}", fields)

    def list_ready_to_publish(self, limit: int = 10):
        params = {"maxSize": limit}
        params.update(self._where("status", "Ready to Publish"))
        result = self._call("GET", "/WhatsAppChannelPost", params=params)
        return result.get("list") or []

    def ping(self) -> bool:
        try:
            self._call("GET", "/Contact", params={"maxSize": 1})
            return True
        except EspoError:
            return False
