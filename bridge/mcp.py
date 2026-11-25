"""MCP (Model Context Protocol) server for EspoCRM + GOWA.

Implements JSON-RPC 2.0 over HTTP (streamable-HTTP style: one POST, one JSON
response). Mounted at /mcp on the bridge's existing HTTP server, so it adds no
process and no measurable memory.

Exposed tools cover the two things an assistant needs against this stack:
read/write CRM records, and read/send WhatsApp — including Channel posts.
"""
from __future__ import annotations

import json
import logging
import uuid

from espocrm import EspoError
from gowa import GowaError

log = logging.getLogger("bridge.mcp")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "gowa-espocrm-mcp", "version": "1.0.0"}
INSTRUCTIONS = (
    "EspoCRM + WhatsApp control plane. Use crm_search to find contacts or channel "
    "posts, crm_create_channel_post + status='Ready to Publish' to schedule a post, "
    "and wa_channel_messages to read a channel. Publishing requires the linked "
    "WhatsApp account to be an admin of the channel."
)

CRM_ENTITIES = ["Contact", "Lead", "Case", "Account", "WhatsAppChannelPost"]

TOOLS = [
    {
        "name": "crm_search",
        "description": "Search EspoCRM records. Filter by free text and/or exact phone number.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": CRM_ENTITIES},
                "q": {"type": "string", "description": "free-text search"},
                "phone": {"type": "string", "description": "exact phone, e.g. +9665..."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "crm_get",
        "description": "Fetch one EspoCRM record by id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": CRM_ENTITIES},
                "id": {"type": "string"},
            },
            "required": ["entity", "id"],
        },
    },
    {
        "name": "crm_create_channel_post",
        "description": (
            "Create a WhatsAppChannelPost. Use status='Ready to Publish' to publish it "
            "immediately to the channel; 'New' stores it as a draft."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "channelJid": {"type": "string", "description": "e.g. 1203630...@newsletter"},
                "body": {"type": "string"},
                "status": {"type": "string", "enum": ["New", "Ready to Publish"], "default": "New"},
            },
            "required": ["name", "channelJid"],
        },
    },
    {
        "name": "crm_update_channel_post",
        "description": "Update a channel post (publish it by setting status='Ready to Publish').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string", "enum": ["New", "Ready to Publish", "Failed"]},
                "name": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "crm_list_ready_posts",
        "description": "List channel posts waiting to be published.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "wa_send",
        "description": "Send a WhatsApp text message to a phone number or a channel JID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "phone (+9665...) or 1203630...@newsletter"},
                "message": {"type": "string"},
            },
            "required": ["to", "message"],
        },
    },
    {
        "name": "wa_channel_messages",
        "description": "Read the latest messages of a WhatsApp Channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channelJid": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "required": ["channelJid"],
        },
    },
    {
        "name": "bridge_health",
        "description": "Dependency and queue health of the bridge.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class McpError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class McpServer:
    def __init__(self, espo, gowa, store=None, health=None):
        self.espo = espo
        self.gowa = gowa
        self.store = store
        self._health = health

    # -- JSON-RPC ----------------------------------------------------------
    def handle(self, request: dict):
        """Return a response dict, or None for notifications."""
        method = request.get("method")
        params = request.get("params") or {}
        req_id = request.get("id")

        try:
            if method == "initialize":
                result = self._initialize(params)
            elif method == "notifications/initialized":
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call_tool(params)
            elif method in ("resources/list", "prompts/list"):
                result = {"resources": []} if method.startswith("resources") else {"prompts": []}
            else:
                raise McpError(-32601, f"Method not found: {method}")
        except McpError as exc:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:  # noqa: BLE001
            log.exception("mcp internal error")
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32603, "message": str(exc)[:300]}}

        if req_id is None:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }

    # -- tools -------------------------------------------------------------
    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise McpError(-32602, "arguments must be an object")
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                    "isError": True}
        try:
            data = handler(args)
        except (EspoError, GowaError) as exc:
            return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                    "isError": True}
        except McpError as exc:
            return {"content": [{"type": "text", "text": exc.message}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
                "isError": False}

    @staticmethod
    def _entity(args: dict) -> str:
        entity = args.get("entity")
        if entity not in CRM_ENTITIES:
            raise McpError(-32602, f"entity must be one of {CRM_ENTITIES}")
        return entity

    def _tool_crm_search(self, args: dict) -> dict:
        entity = self._entity(args)
        limit = int(args.get("limit") or 10)
        params = {"maxSize": max(1, min(limit, 50))}
        if args.get("phone"):
            params.update({
                "where[0][type]": "equals",
                "where[0][field]": "phoneNumber",
                "where[0][value]": args["phone"],
            })
        elif args.get("q"):
            params["textFilter"] = args["q"]
        result = self.espo._call("GET", f"/{entity}", params=params)
        items = result.get("list") or []
        return {"total": result.get("total", len(items)), "list": items}

    def _tool_crm_get(self, args: dict) -> dict:
        entity = self._entity(args)
        if not args.get("id"):
            raise McpError(-32602, "id is required")
        return self.espo._call("GET", f"/{entity}/{args['id']}")

    def _tool_crm_create_channel_post(self, args: dict) -> dict:
        if not args.get("name") or not args.get("channelJid"):
            raise McpError(-32602, "name and channelJid are required")
        payload = {
            "name": args["name"],
            "channelJid": args["channelJid"],
            "body": args.get("body") or "",
            "status": args.get("status") or "New",
        }
        return self.espo.create_channel_post(payload)

    def _tool_crm_update_channel_post(self, args: dict) -> dict:
        if not args.get("id"):
            raise McpError(-32602, "id is required")
        fields = {k: args[k] for k in ("status", "name", "body") if args.get(k) is not None}
        if not fields:
            raise McpError(-32602, "nothing to update")
        return self.espo.update_channel_post(args["id"], fields)

    def _tool_crm_list_ready_posts(self, args: dict) -> dict:
        posts = self.espo.list_ready_to_publish()
        return {"count": len(posts), "list": posts}

    def _tool_wa_send(self, args: dict) -> dict:
        if not args.get("to") or not args.get("message"):
            raise McpError(-32602, "to and message are required")
        return self.gowa.send_message(args["to"], args["message"])

    def _tool_wa_channel_messages(self, args: dict) -> dict:
        if not args.get("channelJid"):
            raise McpError(-32602, "channelJid is required")
        count = int(args.get("count") or 20)
        return self.gowa.newsletter_messages(args["channelJid"], count=max(1, min(count, 100)))

    def _tool_bridge_health(self, args: dict) -> dict:
        if self._health:
            return self._health()
        payload = {"espocrm": self.espo.ping()}
        if self.store is not None:
            payload["queue"] = self.store.pending_count()
        return payload


def new_session_id() -> str:
    return uuid.uuid4().hex
