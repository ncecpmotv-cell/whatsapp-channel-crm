"""One idea in, a token-bounded execution pack out.

The expensive part of an agent turn is re-sending context, not the question. This module turns
"here is my idea" into a single payload: the numbers that matter, the angles already found, the
skill order, the exact next tool calls and the guards — so the model spends tokens deciding, not
collecting. Everything here is deterministic; no model is called.
"""
from __future__ import annotations

import glob
import json
import os

RULES: list[tuple[str, tuple[str, ...]]] = [
    ("reply", ("وارد", "رد على", "رسائل", "شكوى", "زعلان")),
    ("visibility", ("ظهور", "انتشار", "ينتشر", "ننتشر", "وصول", "متابعين", "مشتركين جدد",
                    "نمو", "خوارزم", "اكتشاف")),
    ("launch", ("إطلاق", "نطلق", "حملة", "منتج جديد", "افتتاح")),
    ("distribute", ("وزّع", "توزيع", "لينكدإن", "إكس ", "تيليجرام", "منصات")),
    ("analyze", ("تحليل", "فسّر", "أرقام", "مراجعة", "احتفاظ", "تسرّب", "تراجع")),
    ("plan", ("خطة", "أسبوع", "شهر", "جدول", "خطة محتوى")),
    ("write", ("اكتب", "مسودة", "منشور", "محتوى", "كاروسيل")),
]

PLAYBOOKS: dict[str, dict] = {
    "plan": {
        "skills": ["editorial-board", "strategic-plan"],
        "model_calls": 2,
        "steps": [
            {"tool": "crm_save_plan", "args": {"week_start": "<الاثنين القادم>", "items": "4-6 عناصر بلا نصوص"},
             "why": "الخطة ككائن حتى تُعتمد وتُقاس"},
            {"tool": "crm_lint_post", "args": {"id": "<بعد إنشاء المسودات>"},
             "why": "لا مسودة تُعتمد قبل الفحص"},
        ],
    },
    "write": {
        "skills": ["channel-brand", "hook-lab", "title-formulas", "carousel-builder"],
        "model_calls": 1,
        "steps": [
            {"tool": "crm_best_slot", "args": {"kind": "<نوع المحتوى>"}, "why": "الفتحة من البيانات لا من الذوق"},
            {"tool": "crm_visual_brief", "args": {"kind": "<image|video|audio>", "topic": "<الموضوع>"},
             "why": "المواصفات البصرية قبل أي وسائط"},
            {"tool": "crm_create_channel_post", "args": {"status": "draft", "visual_brief": "<كما هو>"},
             "why": "مسودة فقط — النشر بشري"},
            {"tool": "crm_lint_post", "args": {"id": "<المسودة>"}, "why": "الفحص قبل الاعتماد"},
        ],
    },
    "analyze": {
        "skills": ["insight-interpreter", "metrics-glossary", "weekly-review", "retention-audit"],
        "model_calls": 1,
        "steps": [
            {"tool": "crm_post_pack", "args": {"id": "<أفضل منشور>"}, "why": "قارن الأرقام لا الانطباع"},
            {"tool": "content_insights", "args": {"days": 30}, "why": "المتوسط والأنواع"},
        ],
    },
    "visibility": {
        "skills": ["visibility-plan", "audience-persona", "distribution-plan", "community-prompts"],
        "model_calls": 2,
        "steps": [
            {"tool": "crm_radar_scan", "args": {"summarize": True}, "why": "زوايا جديدة من خارج القناة"},
            {"tool": "crm_save_plan", "args": {"week_start": "<الاثنين القادم>", "items": "2-3 عناصر اكتشاف"},
             "why": "الظهور يحتاج خطة لا منشورًا"},
        ],
    },
    "launch": {
        "skills": ["launch-calendar", "strategic-plan"],
        "model_calls": 1,
        "steps": [
            {"tool": "crm_save_plan", "args": {"week_start": "<أسبوع الإطلاق>", "items": "6-8 عناصر"},
             "why": "الإطلاق سلسلة لا منشور"},
            {"tool": "crm_best_slot", "args": {"kind": "text"}, "why": "أفضل توقيت إعلان"},
        ],
    },
    "distribute": {
        "skills": ["distribution-plan", "crosspost-adapter"],
        "model_calls": 1,
        "steps": [
            {"tool": "crm_post_pack", "args": {"id": "<المنشور>"}, "why": "مصدر واحد لكل الصيغ"},
        ],
    },
    "reply": {
        "skills": ["reply-desk", "incident-comms"],
        "model_calls": 1,
        "steps": [
            {"tool": "crm_inbox", "args": {"limit": 10}, "why": "السياق في نداء واحد"},
            {"tool": "wa_send", "args": {"to": "<الهاتف>", "message": "<بعد موافقة صريحة>"},
             "why": "الإرسال لا يحدث تلقائيًا"},
        ],
    },
}

GUARDS = [
    "الاعتماد والجدولة والنشر بشرية (AGENT_TOKEN يُرفض).",
    "لا منشور وسائط بلا ملف ولا بلا visual_brief.",
    "سقف 40 استدعاء ذكاء يوميًا على الحافة، و20 رسالة/ساعة، و30 منشورًا/يوميًا.",
    "لا استبيانات في القنوات، ولا شعارات شخصية.",
]


def classify(idea: str) -> str:
    text = (idea or "").lower()
    for mode, words in RULES:
        if any(word in text for word in words):
            return mode
    return "plan"


def _compact_brief(crm, days: int = 30) -> dict:
    insights = crm.content_insights(days)
    total = insights.get("total") or {}
    posts = int(insights.get("posts") or 0)
    views = int(total.get("views") or 0)
    reactions = int(total.get("reactions") or 0)
    growth = crm.channel_growth(30)
    gaps = crm.content_gaps(max(days, 60)).get("opportunities") or []
    slots = crm.posting_times(90).get("best") or []
    brand = crm.get_brand()
    return {
        "posts": posts,
        "avg_views": round(views / posts, 1) if posts else 0,
        "engagement_pct": round(reactions / views * 100, 2) if views else 0,
        "cadence": insights.get("cadence_per_week"),
        "subscribers": growth.get("subscribers_now"),
        "delta_30d": growth.get("subscribers_delta"),
        "best_slot": (f"{slots[0]['weekday']} {int(slots[0]['hour']):02d}:00" if slots else None),
        "gaps": [gap.get("term") for gap in gaps[:3]],
        "brand_version": brand.get("version"),
        "limits": brand.get("limits"),
    }


def build(crm, idea: str, mode: str | None = None) -> dict:
    chosen = (mode or "").strip().lower() or classify(idea)
    if chosen not in PLAYBOOKS:
        chosen = "plan"
    playbook = PLAYBOOKS[chosen]
    plan = crm.get_plan() or {}
    angles = crm.list_angles("new", 3)
    run = crm.record_run(chosen, idea, len(playbook["steps"]))
    return {
        "ok": True,
        "run_id": run["id"],
        "idea": (idea or "")[:200],
        "mode": chosen,
        "skills": playbook["skills"],
        "brief": _compact_brief(crm),
        "angles": [{"id": row["id"], "title": (row["title"] or "")[:90],
                    "angle": (row.get("angle") or "")[:110]} for row in angles],
        "plan": {"week": plan.get("week_start"), "status": plan.get("status"),
                 "items": len(plan.get("items") or [])},
        "steps": playbook["steps"],
        "guards": GUARDS,
        "budget": {"model_calls": playbook["model_calls"], "tool_calls": len(playbook["steps"]) + 1},
        "note": "نفّذ الخطوات بالترتيب، ولا تعد قراءة ما في هذا الموجز.",
    }


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def capabilities(crm, picoclaw_home: str = "", tools_count: int = 0) -> dict:
    home = os.path.expanduser(picoclaw_home or "~/pico")
    skills = sorted({os.path.basename(os.path.dirname(path))
                     for path in glob.glob(os.path.join(home, "skills", "*", "SKILL.md"))
                     + glob.glob(os.path.join(home, "workspace", "skills", "*", "SKILL.md"))})
    config = _read_json(os.path.join(home, "config.json")) or {}
    servers = {}
    for name, server in ((config.get("tools") or {}).get("mcp") or {}).get("servers", {}).items():
        servers[name] = {"url": server.get("url"), "enabled": bool(server.get("enabled"))}
    cron_file = (_read_json(os.path.join(home, "workspace", "cron", "jobs.json"))
                 or _read_json(os.path.join(home, "workspace", "cron", "cron.json")) or {})
    jobs = [{"name": job.get("name"), "schedule": (job.get("schedule") or {}).get("expr"),
             "enabled": job.get("enabled")}
            for job in (cron_file.get("jobs") or [])]
    models = [{"name": entry.get("model_name"), "model": entry.get("model"),
               "base": entry.get("api_base"), "enabled": entry.get("enabled", True)}
              for entry in (config.get("model_list") or [])]
    current = ((config.get("agents") or {}).get("defaults") or {}).get("model_name")
    return {
        "skills": {"count": len(skills), "names": skills},
        "tools": {"count": tools_count},
        "models": {"current": current, "list": models},
        "mcp": servers,
        "cron": jobs,
        "guards": GUARDS,
        "runs": crm.list_runs(5),
        "cost": {"ai_daily_limit": 40, "media_cap_mb": 20, "backup_cap_mb": 64},
    }
