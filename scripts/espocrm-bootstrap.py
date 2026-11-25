#!/usr/bin/env python3
"""Create (idempotently) the EspoCRM API user, role and API key for the bridge.

EspoCRM 10 quirks this script encodes — all verified against 10.1.4:
  * an API user must have authMethod = "ApiKey", otherwise X-Api-Key returns 401
  * the API key is generated via POST /UserSecurity/apiKey/generate {"id": ...}
  * role.data wants "yes"/"no" strings, NOT booleans (booleans -> 400)
  * posting a Note requires the parent scope's "stream":"yes" permission
  * POST /{entity}/{id}/stream is a silent no-op; notes must go to POST /Note

Usage:
  python3 espocrm-bootstrap.py --admin-user admin --admin-pass 'secret'
Prints the generated API key on stdout (everything else goes to stderr).
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

SCOPES = ["Contact", "Lead", "Case", "Account", "WhatsAppChannelPost", "Note"]


def log(message: str) -> None:
    print(message, file=sys.stderr)


class Espo:
    def __init__(self, base: str, user: str, password: str):
        self.base = base.rstrip("/") + "/api/v1"
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()

    def call(self, method: str, path: str, body=None, api_key: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", "Basic " + self.auth)
        req.add_header("Accept", "application/json")
        if api_key:
            req.add_header("X-Api-Key", api_key)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()[:400]

    def find(self, entity: str, field: str, value: str):
        query = urllib.parse.urlencode({
            "maxSize": 20,
            "where[0][type]": "equals",
            "where[0][field]": field,
            "where[0][value]": value,
        })
        status, result = self.call("GET", f"/{entity}?{query}")
        if status != 200 or not isinstance(result, dict):
            return None
        return (result.get("list") or [None])[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-pass", required=True)
    parser.add_argument("--api-user", default="wa-bridge")
    parser.add_argument("--role-name", default="WhatsApp Bridge")
    args = parser.parse_args()

    espo = Espo(args.base_url, args.admin_user, args.admin_pass)

    status, _ = espo.call("GET", "/Contact?maxSize=1")
    if status != 200:
        log(f"ERROR: cannot authenticate to EspoCRM (status {status})")
        return 1

    user = espo.find("User", "userName", args.api_user)
    if user:
        user_id = user["id"]
        log(f"user {args.api_user} exists ({user_id})")
        status, _ = espo.call("PUT", f"/User/{user_id}", {"authMethod": "ApiKey", "isActive": True})
        log(f"ensured authMethod=ApiKey (status {status})")
    else:
        status, created = espo.call("POST", "/User", {
            "userName": args.api_user,
            "type": "api",
            "authMethod": "ApiKey",
            "lastName": "WhatsApp Bridge",
            "isActive": True,
        })
        if status != 200:
            log(f"ERROR: creating API user failed: {created}")
            return 1
        user_id = created["id"]
        log(f"created API user {args.api_user} ({user_id})")

    status, generated = espo.call("POST", "/UserSecurity/apiKey/generate", {"id": user_id})
    api_key = generated.get("apiKey") if isinstance(generated, dict) else None
    if status != 200 or not api_key:
        log(f"ERROR: API key generation failed (status {status})")
        return 1
    log("generated API key")

    data = {scope: {"create": "yes", "read": "all", "edit": "all",
                    "delete": "yes", "stream": "yes"} for scope in SCOPES}
    role = espo.find("Role", "name", args.role_name)
    if role:
        role_id = role["id"]
        status, _ = espo.call("PUT", f"/Role/{role_id}", {"name": args.role_name, "data": data})
        log(f"updated role {args.role_name} (status {status})")
    else:
        status, created = espo.call("POST", "/Role", {"name": args.role_name, "data": data})
        if status != 200:
            log(f"ERROR: creating role failed: {created}")
            return 1
        role_id = created["id"]
        log(f"created role {args.role_name}")

    status, _ = espo.call("PUT", f"/User/{user_id}", {"rolesIds": [role_id]})
    log(f"assigned role (status {status})")

    status, _ = espo.call("GET", "/WhatsAppChannelPost?maxSize=1", api_key=api_key)
    if status != 200:
        log(f"WARNING: API key cannot read WhatsAppChannelPost yet (status {status}).")
        log("         Re-run after deploying the entity metadata + rebuild.")
    else:
        log("verified: API key can read WhatsAppChannelPost")

    print(api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
