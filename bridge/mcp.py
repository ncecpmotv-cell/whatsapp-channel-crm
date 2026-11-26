"""MCP (Model Context Protocol) server for the phone CRM + GOWA.

JSON-RPC 2.0 over HTTP: one POST, one JSON response, mounted at /mcp on the
bridge's own HTTP server — no extra process, no extra port.

Approval rule: an agent token can create drafts and propose a schedule, but it
cannot move a post into `scheduled`/`published` unless AGENT_CAN_PUBLISH=1.
That keeps publishing a human decision by default.
"""
from __future__ import annotations

import json
import logging
import uuid

from gowa import GowaError

log = logging.getLogger("bridge.mcp")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "phone-crm-mcp", "version": "2.0.0"}
INSTRUCTIONS = (
    "CRM قناة واتساب على الجوال: محتوى (idea → draft → review → scheduled → published)، "
    "جهات اتصال وصفقات ومتابعات، وقياسات القناة. "
    "أنشئ مسودة بـ crm_create_channel_post ثم اقترح وقتًا بـ content_schedule — "
    "النشر النهائي قرار بشري من الواجهة."
)

CRM_ENTITIES = ["Contact", "Deal", "WhatsAppChannelPost"]

TOOLS = [
    {
        "name": "crm_search",
        "description": "Search contacts, deals or channel posts. Filter by free text and/or exact phone.",
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
        "description": "Fetch one record by id (Contact / Deal / WhatsAppChannelPost).",
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
        "description": "Create a channel post draft. Returns the new id; nothing is published.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "short title"},
                "channelJid": {"type": "string", "description": "e.g. 1203630...@newsletter"},
                "body": {"type": "string"},
                "created_by": {"type": "string", "enum": ["agent", "human"], "default": "agent"},
            },
            "required": ["channelJid"],
        },
    },
    {
        "name": "crm_update_channel_post",
        "description": "Edit a draft (title/body). Status changes are refused unless the token may publish.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "body": {"type": "string"},
                "status": {"type": "string", "enum": ["idea", "draft", "review"]},
            },
            "required": ["id"],
        },
    },
    {
        "name": "content_schedule",
        "description": (
            "Propose a publish time (ISO-8601 or epoch). Without publish rights the post "
            "becomes 'review' with the proposed time, waiting for human approval."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "at": {"type": "string", "description": "ISO-8601, e.g. 2026-11-27T18:30:00+03:00"},
            },
            "required": ["id", "at"],
        },
    },
    {
        "name": "crm_list_ready_posts",
        "description": "List posts waiting in the queue (proposed or approved for publishing).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "channel_metrics",
        "description": "Channel numbers: views / forwards / reactions for the last N days.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 7}},
        },
    },
    {
        "name": "contact_upsert",
        "description": "Create or update a contact by phone (E.164).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "name": {"type": "string"},
                "org": {"type": "string"},
                "stage": {"type": "string", "enum": ["lead", "qualified", "customer", "partner", "cold"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
            "required": ["phone"],
        },
    },
    {
        "name": "deal_update",
        "description": "Create a deal or update its stage/value/next action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "contact_phone": {"type": "string"},
                "title": {"type": "string"},
                "value": {"type": "number"},
                "stage": {"type": "string", "enum": ["new", "contacted", "proposal", "negotiation", "won", "lost"]},
                "next_action_at": {"type": "string"},
                "notes": {"type": "string"},
            },
        },
    },
    {
        "name": "followups_due",
        "description": "Follow-ups due now or within N days.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 0, "maximum": 60, "default": 0}},
        },
    },
    {
        "name": "wa_send",
        "description": "Send a WhatsApp text to a phone number or a channel JID.",
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
        "description": "Dependency, queue and CRM health.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class McpError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class McpServer:
    def __init__(self, crm, gowa, store=None, health=None, can_publish: bool = False):
        self.crm = crm
        self.gowa = gowa
        self.store = store
        self._health = health
        self.can_publish = can_publish

    # -- JSON-RPC ----------------------------------------------------------
    def handle(self, request: dict):
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
                result = {"tools": self._tools()}
            elif method == "tools/call":
                result = self._call_tool(params)
            elif method in ("resources/list", "prompts/list"):
                result = {"resources": []} if method.startswith("resources") else {"prompts": []}
            else:
                raise McpError(-32601, f"Method not found: {method}")
        except McpError as exc:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:  # noqa: BLE001
            log.exception("mcp internal error")
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(exc)[:300]}}

        if req_id is None:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _tools(self):
        tools = list(TOOLS)
        if not self.can_publish:
            # Hide the ability to state a publishing transition at all.
            for tool in tools:
                if tool["name"] == "crm_update_channel_post":
                    tool = dict(tool)
                    props = dict(tool["inputSchema"]["properties"])
                    props.pop("status", None)
                    tool["inputSchema"] = {**tool["inputSchema"], "properties": props}
        return tools

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
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
        try:
            data = handler(args)
        except GowaError as exc:
            return {"content": [{"type": "text", "text": f"GowaError: {exc}"}], "isError": True}
        except (PermissionError, ValueError) as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
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
        return self.crm.search(self._entity(args), q=args.get("q"),
                               phone=args.get("phone"), limit=int(args.get("limit") or 10))

    def _tool_crm_get(self, args: dict) -> dict:
        if not args.get("id"):
            raise McpError(-32602, "id is required")
        return self.crm.get_record(self._entity(args), args["id"])

    def _tool_crm_create_channel_post(self, args: dict) -> dict:
        if not args.get("channelJid"):
            raise McpError(-32602, "channelJid is required")
        return self.crm.create_channel_post({
            "channel_jid": args["channelJid"],
            "title": args.get("name") or "",
            "body": args.get("body") or "",
            "status": "draft",
            "created_by": args.get("created_by") or "agent",
        })

    def _tool_crm_update_channel_post(self, args: dict) -> dict:
        if not args.get("id"):
            raise McpError(-32602, "id is required")
        fields = {k: args[k] for k in ("name", "body") if args.get(k) is not None}
        if self.can_publish and args.get("status"):
            fields["status"] = args["status"]
        elif args.get("status") not in (None, "", "idea", "draft", "review"):
            raise PermissionError("publishing status needs human approval in the UI")
        if not fields:
            raise McpError(-32602, "nothing to update")
        return self.crm.update_channel_post(args["id"], fields,
                                            allowed_statuses=None if self.can_publish else ("idea", "draft", "review"))

    def _tool_content_schedule(self, args: dict) -> dict:
        if not args.get("id") or not args.get("at"):
            raise McpError(-32602, "id and at are required")
        from service import to_epoch
        at = to_epoch(args["at"])
        if not at:
            raise McpError(-32602, "at must be ISO-8601 or epoch seconds")
        return self.crm.schedule_post(args["id"], at, approved=self.can_publish)

    def _tool_crm_list_ready_posts(self, args: dict) -> dict:
        posts = self.crm.list_posts("review", 50) + self.crm.list_posts("scheduled", 50)
        posts.sort(key=lambda p: p.get("scheduled_at") or 0)
        return {"count": len(posts), "list": posts}

    def _tool_channel_metrics(self, args: dict) -> dict:
        return self.crm.channel_metrics(int(args.get("days") or 7))

    def _tool_contact_upsert(self, args: dict) -> dict:
        if not args.get("phone"):
            raise McpError(-32602, "phone is required")
        return self.crm.upsert_contact(args["phone"], name=args.get("name"), org=args.get("org"),
                                      stage=args.get("stage"), tags=args.get("tags"),
                                      notes=args.get("notes"))

    def _tool_deal_update(self, args: dict) -> dict:
        from service import to_epoch
        contact_id = None
        if args.get("contact_phone"):
            contact = self.crm.find_contact_by_phone(args["contact_phone"])
            if not contact:
                raise ValueError("contact not found; call contact_upsert first")
            contact_id = contact["id"]
        if not args.get("id") and not args.get("title"):
            raise McpError(-32602, "title is required to create a deal")
        return self.crm.upsert_deal(
            title=args.get("title") or "",
            contact_id=contact_id,
            value=args.get("value"),
            stage=args.get("stage"),
            next_action_at=to_epoch(args.get("next_action_at")) if args.get("next_action_at") else None,
            notes=args.get("notes"),
            deal_id=args.get("id"),
        )

    def _tool_followups_due(self, args: dict) -> dict:
        items = self.crm.followups(int(args.get("days") or 0))
        return {"count": len(items), "items": items}

    def _tool_wa_send(self, args: dict) -> dict:
        if not args.get("to") or not args.get("message"):
            raise McpError(-32602, "to and message are required")
        response = self.gowa.send_message(args["to"], args["message"])
        if not args["to"].endswith("@newsletter"):
            phone = args["to"]
            contact = self.crm.find_contact_by_phone(phone)
            self.crm.add_message(contact["id"] if contact else None, "out", args["message"], read=True)
        return response

    def _tool_wa_channel_messages(self, args: dict) -> dict:
        if not args.get("channelJid"):
            raise McpError(-32602, "channelJid is required")
        count = int(args.get("count") or 20)
        return self.gowa.newsletter_messages(args["channelJid"], count=max(1, min(count, 100)))

    def _tool_bridge_health(self, args: dict) -> dict:
        if self._health:
            return self._health()
        payload = {"crm": self.crm.ping()}
        if self.store is not None:
            payload["queue"] = self.store.pending_count()
        return payload


def new_session_id() -> str:
    return uuid.uuid4().hex
