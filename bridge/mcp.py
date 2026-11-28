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
import threading
import uuid

from gowa import GowaError

log = logging.getLogger("bridge.mcp")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "phone-crm-mcp", "version": "2.0.0"}
INSTRUCTIONS = (
    "CRM قناة واتساب على الجوال: محتوى (draft → معتمد/مجدول → published)، "
    "جهات اتصال وصفقات ومتابعات، وقياسات القناة. "
    "للتحليل استخدم content_gaps وcontent_insights وposting_times قبل اقتراح أي خطة. "
    "قبل اختراع زاوية جديدة، ابحث في الأرشيف بـsemantic_search وأعد استخدام ما نجح. "
    "لخطة أسبوع: احفظها بـcrm_save_plan ثم اعرضها؛ لا تستدعِ crm_approve_plan إلا بعد موافقة صريحة. "
    "قبل أي جدولة: crm_lint_post، واختر الوقت بـcrm_best_slot. "
    "إذا أرسل المستخدم صورة أو فيديو: crm_attach_media(path=المسار المحلي). "
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
                "status": {"type": "string", "enum": ["draft", "scheduled"]},
            },
            "required": ["id"],
        },
    },
    {
        "name": "content_schedule",
        "description": (
            "Propose a publish time (ISO-8601 or epoch). Without publish rights the post "
            "becomes 'scheduled' with the proposed time; publishing stays a human decision."
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
        "name": "channel_info",
        "description": "WhatsApp channel profile (name, subscribers, invite) + summary stats.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 30}},
        },
    },
    {
        "name": "content_insights",
        "description": "What worked in the last N days: totals, per-type averages, engagement "
                       "rate, cadence per week, the top 5 posts and the weakest 3.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30}},
        },
    },
    {
        "name": "posting_times",
        "description": "Best weekday/hour pairs by average views (local time), plus the weakest "
                       "buckets — use it to choose publishing slots.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 7, "maximum": 365, "default": 90},
                "tz_offset": {"type": "integer", "minimum": -12, "maximum": 14,
                              "description": "hours from UTC; defaults to TZ_OFFSET"},
            },
        },
    },
    {
        "name": "content_gaps",
        "description": "Topic-level diagnosis: terms with high views but few posts (opportunities), "
                       "terms that are saturated, per-type averages, cadence and gaps in publishing.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 7, "maximum": 365, "default": 90}},
        },
    },
    {
        "name": "semantic_search",
        "description": "Find past posts similar to a phrase (BM25 over titles and bodies). Offline, "
                       "no embeddings — use it to reuse a winner instead of inventing a new angle.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "two or more meaningful words"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "crm_save_plan",
        "description": "Save (or replace) the proposed content plan for a week. Each item: title, "
                       "body, kind (text/image/video/audio/file/link), goal, slot_at 'YYYY-MM-DD HH:MM'. "
                       "Nothing is published or scheduled until crm_approve_plan is called by a human.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "week_start": {"type": "string", "description": "YYYY-MM-DD (any day of that week)"},
                "title": {"type": "string"},
                "notes": {"type": "string"},
                "items": {
                    "type": "array", "minItems": 1, "maxItems": 14,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                            "kind": {"type": "string",
                                     "enum": ["text", "image", "video", "audio", "file", "link"]},
                            "goal": {"type": "string",
                                     "enum": ["awareness", "engagement", "conversion"]},
                            "slot_at": {"type": "string", "description": "local 'YYYY-MM-DD HH:MM'"},
                        },
                        "required": ["title"],
                    },
                },
            },
            "required": ["week_start", "items"],
        },
    },
    {
        "name": "crm_transcribe_audio",
        "description": "Transcribe a local audio file (the voice note PicoClaw downloaded) using "
                       "Workers AI on the edge; returns Arabic/English text.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "absolute path"}},
            "required": ["path"],
        },
    },
    {
        "name": "crm_caption_image",
        "description": "Describe a local image and suggest hashtags (Workers AI vision).",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "crm_orchestrate",
        "description": "Give it one idea about the channel and it returns a token-bounded execution "
                       "pack: the numbers, the angles already found, the skill order, the exact next "
                       "tool calls and the guards. Call this FIRST for any 'here is my idea' request "
                       "instead of collecting context yourself.",
        "inputSchema": {
            "type": "object",
            "properties": {"idea": {"type": "string"},
                           "mode": {"type": "string",
                                    "enum": ["plan", "write", "analyze", "visibility", "launch",
                                             "distribute", "reply"]}},
            "required": ["idea"],
        },
    },
    {
        "name": "crm_capabilities",
        "description": "What the agent can use right now: skills installed, MCP servers, cron jobs, "
                       "guards, cost caps and the last orchestration runs.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "crm_inbox",
        "description": "Unread inbound DMs with contact name, phone and stage — one call instead of "
                       "searching contacts and messages separately.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 12},
                           "all": {"type": "boolean", "default": False}},
        },
    },
    {
        "name": "crm_post_pack",
        "description": "One post with everything needed to rewrite or measure it: body, metrics, "
                       "lint issues, plan slot, visual brief and the closest archived posts.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                        "required": ["id"]},
    },
    {
        "name": "crm_visual_brief",
        "description": "The exact visual rules for a media post: format, background/text/accent hex, "
                       "fonts, logo policy and the never-list. Call this before creating any image, "
                       "video or audio post and pass the result back as visual_brief.",
        "inputSchema": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["image", "video", "audio", "story"]},
                           "topic": {"type": "string"}},
        },
    },
    {
        "name": "crm_editorial_brief",
        "description": "One compact briefing for planning: channel numbers, best slots, content "
                       "gaps, radar angles, current plan state and the brand limits. Call this "
                       "first instead of five separate tools.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 30}},
        },
    },
    {
        "name": "crm_radar_scan",
        "description": "Fetch the radar batch and keep the headlines that are new to this channel. "
                       "Set summarize=true (costs one AI call) to get a suggested Arabic angle.",
        "inputSchema": {
            "type": "object",
            "properties": {"summarize": {"type": "boolean", "default": False}},
        },
    },
    {
        "name": "crm_angles",
        "description": "List radar angles waiting for a decision (new by default).",
        "inputSchema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["new", "used", "dismissed", "all"],
                                      "default": "new"}},
        },
    },
    {
        "name": "crm_angle_use",
        "description": "Turn an angle into a draft post for the channel (never publishes).",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                        "required": ["id"]},
    },
    {
        "name": "crm_angle_dismiss",
        "description": "Discard an angle so the radar stops showing it.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                        "required": ["id"]},
    },
    {
        "name": "crm_get_brand",
        "description": "The channel's brand kit: palette, fonts, tone, do/don't lists and posting "
                       "limits. Read it before writing any copy.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "crm_set_brand",
        "description": "Update part of the brand kit (deep-merged). Use it when the owner refines "
                       "the palette, tone or limits.",
        "inputSchema": {
            "type": "object",
            "properties": {"patch": {"type": "object", "description": "keys to merge"}},
            "required": ["patch"],
        },
    },
    {
        "name": "crm_edge_status",
        "description": "Edge health, off-site backup state and last heartbeat age.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "channel_growth",
        "description": "Subscriber and view history per day, with the delta over the window.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 7, "maximum": 365, "default": 90}},
        },
    },
    {
        "name": "crm_create_variant",
        "description": "Create an A/B sibling draft of a post (max 3 variants). Both are normal "
                       "posts with their own metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "label": {"type": "string", "description": "B, C …"},
            },
            "required": ["post_id"],
        },
    },
    {
        "name": "crm_variant_results",
        "description": "Compare a post with its variants by views and name the current winner.",
        "inputSchema": {
            "type": "object",
            "properties": {"post_id": {"type": "string"}},
            "required": ["post_id"],
        },
    },
    {
        "name": "crm_attach_media",
        "description": "Attach a local file (the path PicoClaw downloaded for a Telegram photo/"
                       "video) to a post. Schedules it at the plan slot when one exists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "path": {"type": "string", "description": "absolute path of the downloaded file"},
                "kind": {"type": "string", "enum": ["image", "video", "audio", "file"]},
                "at": {"type": "string", "description": "optional 'YYYY-MM-DD HH:MM'"},
            },
            "required": ["post_id", "path"],
        },
    },
    {
        "name": "crm_lint_post",
        "description": "Pre-publish checks: empty content, missing media, duplicate of an earlier "
                       "post, slot collision. Run it before scheduling or approving.",
        "inputSchema": {
            "type": "object",
            "properties": {"post_id": {"type": "string"}},
            "required": ["post_id"],
        },
    },
    {
        "name": "crm_best_slot",
        "description": "Best weekday/hour for a content type from the channel's own history, "
                       "returning the next free slot ('YYYY-MM-DD HH:MM' + epoch).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["text", "image", "video", "audio", "file", "link"]},
                "days": {"type": "integer", "minimum": 7, "maximum": 365, "default": 90},
            },
        },
    },
    {
        "name": "crm_get_plan",
        "description": "Read a weekly plan with its items and status (latest when no id/week given).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "week_start": {"type": "string", "description": "YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "crm_approve_plan",
        "description": "HUMAN ONLY: turn every plan item into a draft (scheduled at its slot) and "
                       "mark the plan approved. Call it only after the owner explicitly approves.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "channelJid": {"type": "string", "description": "defaults to the configured channel"},
            },
            "required": ["plan_id"],
        },
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
    def __init__(self, crm, gowa, store=None, health=None, can_publish: bool = False, cfg=None):
        self.crm = crm
        self.gowa = gowa
        self.cfg = cfg
        self.store = store
        self._health = health
        self.can_publish = can_publish
        self._local = threading.local()

    @property
    def caller(self) -> str:
        return getattr(self._local, "caller", "human")

    def _human_only(self, action: str) -> None:
        """An agent token may draft; it may never approve, schedule or publish.

        Enforced here rather than in the prompt: the same server serves the UI (human) and
        PicoClaw (agent), and only the token tells them apart.
        """
        if self.caller == "agent":
            raise McpError(-32003, f"{action} is human-only: use the CRM UI")

    # -- JSON-RPC ----------------------------------------------------------
    def handle(self, request: dict, caller: str = "human"):
        self._local.caller = caller
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
        fields = {
            "channel_jid": args["channelJid"],
            "title": args.get("name") or "",
            "body": args.get("body") or "",
            "status": "draft",
            "created_by": args.get("created_by") or "agent",
        }
        if args.get("media_type"):
            fields["media_type"] = args["media_type"]
        brief = args.get("visual_brief")
        if brief:
            if not isinstance(brief, dict):
                raise McpError(-32602, "visual_brief must be an object from crm_visual_brief")
            fields["meta"] = json.dumps({"visual_brief": brief}, ensure_ascii=False)
        return self.crm.create_channel_post(fields)

    def _tool_crm_update_channel_post(self, args: dict) -> dict:
        if not args.get("id"):
            raise McpError(-32602, "id is required")
        fields = {k: args[k] for k in ("name", "body") if args.get(k) is not None}
        if isinstance(args.get("meta"), dict):
            # merge, never replace: visual_brief and angle_id must survive a metadata write
            current = self.crm.get_channel_post(args["id"]) or {}
            try:
                existing = json.loads(current.get("meta") or "{}")
            except ValueError:
                existing = {}
            existing.update(args["meta"])
            fields["meta"] = json.dumps(existing, ensure_ascii=False)
        requested = args.get("status")
        if requested in ("scheduled", "published") and self.caller == "agent":
            self._human_only("scheduling or publishing")
        if self.can_publish and requested:
            fields["status"] = requested
        elif requested not in (None, "", "draft"):
            raise PermissionError("publishing status needs human approval in the UI")
        if not fields:
            raise McpError(-32602, "nothing to update")
        return self.crm.update_channel_post(args["id"], fields,
                                            allowed_statuses=None if self.can_publish else ("draft",))

    def _tool_content_schedule(self, args: dict) -> dict:
        self._human_only("scheduling")
        if not args.get("id") or not args.get("at"):
            raise McpError(-32602, "id and at are required")
        from service import to_epoch
        at = to_epoch(args["at"])
        if not at:
            raise McpError(-32602, "at must be ISO-8601 or epoch seconds")
        return self.crm.schedule_post(args["id"], at, approved=self.can_publish)

    def _tool_crm_list_ready_posts(self, args: dict) -> dict:
        posts = self.crm.list_posts("scheduled", 50)
        posts.sort(key=lambda p: p.get("scheduled_at") or 0)
        return {"count": len(posts), "list": posts}

    def _tool_channel_info(self, args: dict) -> dict:
        days = int(args.get("days") or 30)
        summary = self.crm.channel_summary(days)
        jid = None
        try:
            rows = self.crm._all("SELECT jid FROM crm_posts ORDER BY updated_at DESC LIMIT 1")
            jid = rows[0]["jid"] if rows else None
        except Exception:  # noqa: BLE001
            jid = None
        info = self.crm.get_channel_info(jid) if jid else None
        return {"profile": info, "summary": {k: v for k, v in summary.items() if k != "posts"},
                "series": self.crm.daily_series(14)}

    def _tool_channel_metrics(self, args: dict) -> dict:
        return self.crm.channel_metrics(int(args.get("days") or 7))

    def _tool_content_insights(self, args: dict) -> dict:
        return self.crm.content_insights(int(args.get("days") or 30))

    def _tool_crm_save_plan(self, args: dict) -> dict:
        return self.crm.save_plan(
            week_start=args.get("week_start") or "",
            items=args.get("items") or [],
            title=args.get("title") or "",
            notes=args.get("notes") or "")

    def _edge(self):
        from edge import from_config  # local import keeps mcp usable without a config
        return from_config(self.cfg) if self.cfg else None

    def _tool_crm_orchestrate(self, args: dict) -> dict:
        import orchestrator
        return orchestrator.build(self.crm, args.get("idea") or "", args.get("mode"))

    def _tool_crm_capabilities(self, args: dict) -> dict:
        import orchestrator
        home = getattr(self.cfg, "picoclaw_home", "") if self.cfg else ""
        return orchestrator.capabilities(self.crm, home, len(TOOLS))

    def _tool_crm_inbox(self, args: dict) -> dict:
        rows = self.crm.inbox(int(args.get("limit") or 12), unread_only=not args.get("all"))
        return {"count": len(rows), "messages": rows}

    def _tool_crm_post_pack(self, args: dict) -> dict:
        if not args.get("id"):
            raise McpError(-32602, "id is required")
        return self.crm.post_pack(args["id"])

    def _tool_crm_visual_brief(self, args: dict) -> dict:
        kind = (args.get("kind") or "image").lower()
        if kind not in ("image", "video", "audio", "story"):
            kind = "image"
        return self.crm.visual_spec(kind, (args.get("topic") or "")[:120])

    def _tool_crm_editorial_brief(self, args: dict) -> dict:
        days = max(7, min(180, int(args.get("days") or 30)))
        insights = self.crm.content_insights(days)
        total = insights.get("total") or {}
        posts = int(insights.get("posts") or 0)
        views = int(total.get("views") or 0)
        reactions = int(total.get("reactions") or 0)
        growth = self.crm.channel_growth(30)
        gaps = self.crm.content_gaps(max(days, 60)).get("opportunities") or []
        slots = self.crm.posting_times(90).get("best") or []
        plan = self.crm.get_plan() or {}
        brand = self.crm.get_brand()
        return {
            "window_days": days,
            "channel": {
                "posts": posts,
                "views": views,
                "avg_views": round(views / posts, 1) if posts else 0,
                "engagement_pct": round(reactions / views * 100, 2) if views else 0,
                "cadence_per_week": insights.get("cadence_per_week"),
                "subscribers": growth.get("subscribers_now"),
                "subscribers_delta_30d": growth.get("subscribers_delta"),
            },
            "types": {kind: {"posts": row.get("posts"), "avg_views": row.get("avg_views")}
                      for kind, row in (insights.get("by_type") or {}).items()},
            "best_slots": [{"when": f"{slot.get('weekday')} {int(slot.get('hour') or 0):02d}:00",
                            "avg_views": slot.get("avg_views"), "posts": slot.get("posts")}
                           for slot in slots[:3]],
            "opportunities": [{"theme": gap.get("term"), "avg_views": gap.get("avg_views"),
                               "posts": gap.get("posts")} for gap in gaps[:4]],
            "angles": [{"id": row["id"], "title": (row["title"] or "")[:120],
                        "angle": (row.get("angle") or "")[:160]}
                       for row in self.crm.list_angles("new", 5)],
            "plan": {"week": plan.get("week_start"), "status": plan.get("status"),
                     "items": len(plan.get("items") or [])},
            "brand": {"version": brand.get("version"), "tone": brand.get("tone"),
                      "donts": brand.get("donts"), "limits": brand.get("limits"),
                      "visual": brand.get("visual")},
            "note": ("عينة صغيرة: اقرأ الأرقام كمؤشر لا حكم" if posts < 20 else ""),
        }

    def _tool_crm_radar_scan(self, args: dict) -> dict:
        from radar import scan as radar_scan
        if self.cfg is None:
            raise McpError(-32000, "config is not available")
        return radar_scan(self.crm, self.cfg, summarize=bool(args.get("summarize")),
                          notify=True)

    def _tool_crm_angles(self, args: dict) -> dict:
        status = args.get("status") or "new"
        rows = self.crm.list_angles("" if status == "all" else status, 30)
        return {"status": status, "count": len(rows), "angles": rows}

    def _tool_crm_angle_use(self, args: dict) -> dict:
        angle = self.crm.angle(args.get("id") or "")
        if not angle:
            raise McpError(-32602, "angle not found")
        channel = (self.cfg.newsletter_jids or ("",))[0] if self.cfg else ""
        post = self.crm.create_channel_post({
            "channel_jid": channel,
            "title": (angle.get("angle") or angle.get("title") or "")[:120],
            "body": f"{angle.get('angle') or ''}\n\nالمصدر: {angle.get('url') or ''}".strip(),
            "status": "draft",
            "media_type": "text",
            "meta": json.dumps({"angle_id": angle["id"], "source_url": angle.get("url")}),
            "created_by": "agent",
        })
        self.crm.set_angle_status(angle["id"], "used", post["id"])
        return {"ok": True, "angle_id": angle["id"], "post_id": post["id"],
                "status": post["status"]}

    def _tool_crm_angle_dismiss(self, args: dict) -> dict:
        row = self.crm.set_angle_status(args.get("id") or "", "dismissed")
        if not row:
            raise McpError(-32602, "angle not found")
        return {"ok": True, "id": row["id"], "status": row["status"]}

    def _tool_crm_get_brand(self, args: dict) -> dict:
        return self.crm.get_brand()

    def _tool_crm_set_brand(self, args: dict) -> dict:
        patch = args.get("patch") or {}
        if not isinstance(patch, dict):
            raise McpError(-32602, "patch must be an object")
        return self.crm.set_brand(patch)

    def _tool_crm_transcribe_audio(self, args: dict) -> dict:
        client = self._edge()
        if client is None or not client.enabled():
            raise McpError(-32000, "edge is not configured (EDGE_URL/EDGE_TOKEN)")
        return client.transcribe(args.get("path") or "")

    def _tool_crm_caption_image(self, args: dict) -> dict:
        client = self._edge()
        if client is None or not client.enabled():
            raise McpError(-32000, "edge is not configured (EDGE_URL/EDGE_TOKEN)")
        return client.caption(args.get("path") or "")

    def _tool_crm_edge_status(self, args: dict) -> dict:
        client = self._edge()
        if client is None or not client.enabled():
            return {"enabled": False}
        state = client.health()
        state["last_heartbeat_at"] = self.crm.store.get_meta("last_heartbeat_at")
        state["last_offsite_at"] = self.crm.store.get_meta("last_offsite_at")
        state["last_offsite_name"] = self.crm.store.get_meta("last_offsite_name")
        state["offsite_backups"] = len(client.backups())
        return state

    def _tool_channel_growth(self, args: dict) -> dict:
        return self.crm.channel_growth(int(args.get("days") or 90))

    def _tool_crm_create_variant(self, args: dict) -> dict:
        if not args.get("post_id"):
            raise McpError(-32602, "post_id is required")
        return self.crm.create_variant(args["post_id"], title=args.get("title"),
                                       body=args.get("body"), label=args.get("label"))

    def _tool_crm_variant_results(self, args: dict) -> dict:
        return self.crm.variant_results(args.get("post_id") or "")

    def _tool_crm_attach_media(self, args: dict) -> dict:
        if not args.get("post_id") or not args.get("path"):
            raise McpError(-32602, "post_id and path are required")
        return self.crm.attach_media(args["post_id"], args["path"],
                                     kind=args.get("kind"), at=args.get("at"))

    def _tool_crm_lint_post(self, args: dict) -> dict:
        return self.crm.lint_post(args.get("post_id") or "")

    def _tool_crm_best_slot(self, args: dict) -> dict:
        return self.crm.best_slot(args.get("kind"), int(args.get("days") or 90))

    def _tool_crm_get_plan(self, args: dict) -> dict:
        plan = self.crm.get_plan(plan_id=args.get("plan_id"), week_start=args.get("week_start"))
        return plan or {"plan": None}

    def _tool_crm_approve_plan(self, args: dict) -> dict:
        self._human_only("plan approval")
        plan_id = args.get("plan_id") or ""
        if not plan_id:
            raise McpError(-32602, "plan_id is required")
        channel = args.get("channelJid") or self.crm.default_channel()
        if not channel:
            raise McpError(-32602, "no channel configured")
        return self.crm.approve_plan(plan_id, channel)

    def _tool_content_gaps(self, args: dict) -> dict:
        return self.crm.content_gaps(int(args.get("days") or 90))

    def _tool_semantic_search(self, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            raise McpError(-32602, "query is required")
        return self.crm.semantic_search(query, int(args.get("limit") or 5))

    def _tool_posting_times(self, args: dict) -> dict:
        offset = args.get("tz_offset")
        return self.crm.posting_times(int(args.get("days") or 90),
                                      None if offset is None else int(offset))

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
