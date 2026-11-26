"""Server-rendered Arabic UI — one process, one port, zero JS build.

Pages: dashboard, content board, contacts, deals, metrics.
Every mutating action is a plain HTML form POST (works on any phone browser).
"""
from __future__ import annotations

import datetime as dt
import html
from urllib.parse import parse_qs

STAGES_AR = {
    "idea": "فكرة",
    "draft": "مسودة",
    "review": "مراجعة",
    "scheduled": "مجدول",
    "publishing": "جارٍ النشر",
    "published": "منشور",
    "failed": "فشل",
}
DEAL_STAGES_AR = {
    "new": "جديد",
    "contacted": "تواصل",
    "proposal": "عرض",
    "negotiation": "تفاوض",
    "won": "فاز",
    "lost": "خسر",
}

CSS = """
:root{--bg:#0f1512;--card:#18211c;--line:#2a3a31;--ink:#eef3ee;--muted:#9db0a3;
--gold:#c5a059;--sage:#3e4d42;--ok:#4caf7d;--warn:#d9a04a;--bad:#c85c5c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:"IBM Plex Sans Arabic",system-ui,-apple-system,"Segoe UI",sans-serif;font-size:15px}
header{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 16px;
border-bottom:1px solid var(--line);background:#0b110e;position:sticky;top:0;z-index:5}
header .brand{font-weight:700;color:var(--gold);margin-inline-end:auto}
a{color:var(--ink);text-decoration:none}
nav a{padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);font-size:13px}
nav a.on{background:var(--sage);border-color:var(--gold)}
main{padding:16px;max-width:1100px;margin:0 auto}
h1{font-size:20px;margin:6px 0 14px}
h2{font-size:16px;margin:18px 0 8px;color:var(--gold)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.stat b{display:block;font-size:22px;color:var(--gold)}
.stat span{font-size:12px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0}
.badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:999px;
border:1px solid var(--line);color:var(--muted)}
.badge.published{color:var(--ok);border-color:var(--ok)}
.badge.failed{color:var(--bad);border-color:var(--bad)}
.badge.scheduled{color:var(--warn);border-color:var(--warn)}
.badge.review{color:var(--gold);border-color:var(--gold)}
.muted{color:var(--muted);font-size:12px}
pre{white-space:pre-wrap;margin:6px 0;font-family:inherit}
form{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
input,select,textarea{background:#0d1411;border:1px solid var(--line);color:var(--ink);
border-radius:8px;padding:8px 10px;font-family:inherit;font-size:14px}
textarea{width:100%;min-height:90px}
button{background:var(--sage);color:var(--ink);border:1px solid var(--gold);border-radius:8px;
padding:8px 12px;font-family:inherit;font-size:14px;cursor:pointer}
button.ghost{background:transparent;border-color:var(--line)}
.row{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}
.stack{display:flex;flex-direction:column;gap:4px}
.chart{display:flex;align-items:flex-end;gap:4px;height:90px}
.chart .bar{flex:1;background:#0d1411;border-radius:4px;display:flex;align-items:flex-end;min-width:6px}
.chart .bar i{display:block;width:100%;background:linear-gradient(180deg,var(--gold),var(--sage));border-radius:4px}
table td{padding:6px 4px;border-bottom:1px solid var(--line);font-size:13px}
"""


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def fmt_ts(ts) -> str:
    if not ts:
        return "—"
    return dt.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")


def page(title: str, body: str, active: str = "") -> bytes:
    nav = [
        ("/ui", "اليوم", "today"),
        ("/ui/content", "المحتوى", "content"),
        ("/ui/contacts", "العملاء", "contacts"),
        ("/ui/deals", "الفرص", "deals"),
        ("/ui/channel", "القناة", "channel"),
    ]
    links = "".join(
        f'<a href="{href}" class="{"on" if key == active else ""}">{label}</a>'
        for href, label, key in nav
    )
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(title)} · CRM</title>
<meta name="theme-color" content="#0f1512">
<link rel="manifest" href="/ui/manifest.webmanifest">
<style>{CSS}</style></head>
<body><header><span class="brand">CRM · قناة واتساب</span><nav>{links}</nav></header>
<main>{body}</main></body></html>"""
    return doc.encode("utf-8")


def badge(status: str) -> str:
    return f'<span class="badge {esc(status)}">{esc(STAGES_AR.get(status, status))}</span>'


# ------------------------------------------------------------------ dashboard
def dashboard(stats: dict, scheduled: list[dict], followups: list[dict],
              unread: int, metrics: dict) -> bytes:
    cards = "".join(
        f'<div class="stat"><b>{esc(v)}</b><span>{esc(k)}</span></div>'
        for k, v in [
            ("منشور", stats.get("published", 0)),
            ("مجدول", stats.get("scheduled", 0)),
            ("عملاء", stats.get("contacts", 0)),
            ("فرص", stats.get("deals", 0)),
        ]
    )
    sched_rows = "".join(
        f'<div class="card"><div class="row"><div class="stack">'
        f'<b>{esc(p["title"] or (p["body"] or "")[:60])}</b>'
        f'<span class="muted">🕒 {fmt_ts(p["scheduled_at"])}</span></div>'
        f'{badge(p["status"])}</div></div>'
        for p in scheduled
    ) or '<p class="muted">لا شيء مجدول.</p>'
    follow_rows = "".join(
        f'<div class="card"><div class="row"><div class="stack">'
        f'<b>{esc(f["body"] or "متابعة")}</b>'
        f'<span class="muted">{esc(f.get("contact_name") or f.get("contact_phone") or "")} · {fmt_ts(f["due_at"])}</span>'
        f'</div><form method="post" action="/ui/followup/done">'
        f'<input type="hidden" name="id" value="{esc(f["id"])}">'
        f'<button class="ghost">تم</button></form></div></div>'
        for f in followups
    ) or '<p class="muted">لا متابعات مستحقة.</p>'
    total = metrics.get("total", {})
    body = f"""
<h1>لوحة اليوم</h1>
<div class="grid">{cards}</div>
<h2>أرقام القناة — {esc(total.get("posts", 0))} منشورًا</h2>
<div class="grid">
  <div class="stat"><b>{esc(total.get("views", 0))}</b><span>مشاهدات</span></div>
  <div class="stat"><b>{esc(total.get("forwards", 0))}</b><span>إعادة تمرير</span></div>
  <div class="stat"><b>{esc(total.get("reactions", 0))}</b><span>تفاعل</span></div>
  <div class="stat"><b>{esc(unread)}</b><span>رسائل غير مقروءة</span></div>
</div>
<h2>مجدول</h2>{sched_rows}
<h2>متابعات مستحقة</h2>{follow_rows}
"""
    return page("اليوم", body, "today")


# -------------------------------------------------------------------- content
def content_page(posts: list[dict], status: str = "") -> bytes:
    filters = "".join(
        f'<a href="/ui/content?status={key}" class="badge {"" if status != key else "scheduled"}">'
        f'{esc(label)}</a> '
        for key, label in STAGES_AR.items()
    )
    rows = []
    for p in posts:
        when = fmt_ts(p.get("scheduled_at") or p.get("published_at"))
        actions = ""
        if p["status"] in ("idea", "draft", "review"):
            actions = (
                f'<form method="post" action="/ui/content/schedule">'
                f'<input type="hidden" name="id" value="{esc(p["id"])}">'
                f'<input type="datetime-local" name="at" required>'
                f'<button>جدولة</button></form>'
                f'<form method="post" action="/ui/content/publish">'
                f'<input type="hidden" name="id" value="{esc(p["id"])}">'
                f'<button class="ghost">نشر الآن</button></form>'
            )
        rows.append(f"""
<div class="card">
  <div class="row">
    <div class="stack">
      <b><a href="/ui/post/{esc(p["id"])}">{esc(p["title"] or (p["body"] or "")[:70])}</a></b>
      <span class="muted">{when} · {esc(p.get("created_by"))} · 👁 {esc(p.get("views") or 0)} · ↪ {esc(p.get("forwards") or 0)}</span>
    </div>
    {badge(p["status"])}
  </div>
  <pre>{esc((p["body"] or "")[:400])}</pre>
  {"" if not p.get("last_error") else f'<p class="muted">خطأ: {esc(p["last_error"])}</p>'}
  <div class="row">{actions}</div>
</div>""")
    body = f"""
<h1>المحتوى</h1>
<p>{filters}</p>
<form method="post" action="/ui/content/new">
  <input name="title" placeholder="عنوان مختصر" style="flex:1 1 220px">
  <textarea name="body" placeholder="نص المنشور" required></textarea>
  <button>مسودة جديدة</button>
</form>
{''.join(rows) or '<p class="muted">لا عناصر.</p>'}
"""
    return page("المحتوى", body, "content")


# ------------------------------------------------------------------- contacts
def contacts_page(contacts: list[dict]) -> bytes:
    rows = "".join(f"""
<div class="card"><div class="row">
  <div class="stack"><b>{esc(c["name"] or c["phone"])}</b>
  <span class="muted">{esc(c["phone"])} · {esc(c.get("org") or "—")} · {esc(c.get("stage"))}</span></div>
  <span class="muted">{fmt_ts(c.get("last_inbound"))}</span>
</div></div>""" for c in contacts) or '<p class="muted">لا عملاء بعد.</p>'
    body = f"""
<h1>العملاء</h1>
<form method="post" action="/ui/contacts/new">
  <input name="phone" placeholder="+9665..." required>
  <input name="name" placeholder="الاسم">
  <input name="org" placeholder="الجهة">
  <button>إضافة</button>
</form>
{rows}
"""
    return page("العملاء", body, "contacts")


# ---------------------------------------------------------------------- deals
def deals_page(deals: list[dict]) -> bytes:
    rows = "".join(f"""
<div class="card"><div class="row">
  <div class="stack"><b>{esc(d["title"])}</b>
  <span class="muted">{esc(d.get("contact_name") or "—")} · {esc(d.get("value") or 0)} {esc(d.get("currency"))}</span></div>
  <span class="badge">{esc(DEAL_STAGES_AR.get(d["stage"], d["stage"]))}</span>
</div></div>""" for d in deals) or '<p class="muted">لا فرص بعد.</p>'
    options = "".join(f'<option value="{k}">{v}</option>' for k, v in DEAL_STAGES_AR.items())
    body = f"""
<h1>الفرص</h1>
<form method="post" action="/ui/deals/new">
  <input name="title" placeholder="اسم الفرصة" required>
  <input name="contact_phone" placeholder="+9665...">
  <input name="value" placeholder="القيمة" type="number" step="0.01">
  <select name="stage">{options}</select>
  <button>إضافة</button>
</form>
{rows}
"""
    return page("الفرص", body, "deals")


# -------------------------------------------------------------------- metrics
def metrics_page(metrics: dict) -> bytes:
    total = metrics.get("total", {})
    rows = "".join(f"""
<div class="card"><div class="row">
  <div class="stack"><b>{esc((p["body"] or "")[:80])}</b>
  <span class="muted">{fmt_ts(p.get("published_at"))}</span></div>
  <span class="muted">👁 {esc(p["views"])} · ↪ {esc(p["forwards"])} · ♥ {esc(p["reactions"])}</span>
</div></div>""" for p in metrics.get("posts", [])) or '<p class="muted">لا منشورات.</p>'
    body = f"""
<h1>القياسات — آخر {esc(metrics.get("days"))} يومًا</h1>
<div class="grid">
  <div class="stat"><b>{esc(total.get("views", 0))}</b><span>مشاهدات</span></div>
  <div class="stat"><b>{esc(total.get("forwards", 0))}</b><span>إعادة تمرير</span></div>
  <div class="stat"><b>{esc(total.get("reactions", 0))}</b><span>تفاعل</span></div>
</div>
{rows}
"""
    return page("القياسات", body, "metrics")


MANIFEST = {
    "name": "CRM قناة واتساب",
    "short_name": "CRM",
    "start_url": "/ui",
    "display": "standalone",
    "background_color": "#0f1512",
    "theme_color": "#0f1512",
    "dir": "rtl",
    "lang": "ar",
}


def parse_form(raw: bytes) -> dict:
    data = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    return {k: v[0] for k, v in data.items()}


def parse_local_datetime(value: str) -> int | None:
    """`datetime-local` input (no timezone) is interpreted as local time."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return int(parsed.timestamp())


# ---------------------------------------------------------------- post detail
def _bars(series: list[dict], key: str) -> str:
    if not series:
        return '<p class="muted">لا سجل يومي بعد — تُحفظ لقطة عند كل تحديث للقياسات.</p>'
    top = max((row.get(key) or 0) for row in series) or 1
    bars = "".join(
        f'<div class="bar" title="{esc(row["day"])}: {esc(row.get(key) or 0)}">'
        f'<i style="height:{(row.get(key) or 0) * 100 / top:.0f}%"></i></div>'
        for row in series
    )
    return f'<div class="chart">{bars}</div>'


def post_page(post: dict, history: list[dict], channel: dict | None) -> bytes:
    views = post.get("views") or 0
    forwards = post.get("forwards") or 0
    reactions = post.get("reactions") or 0
    engagement = round((forwards + reactions) * 100 / views, 2) if views else 0
    actions = ""
    if post["status"] in ("idea", "draft", "review"):
        actions = (
            f'<form method="post" action="/ui/content/schedule">'
            f'<input type="hidden" name="id" value="{esc(post["id"])}">'
            f'<input type="datetime-local" name="at" required><button>جدولة</button></form>'
            f'<form method="post" action="/ui/content/publish">'
            f'<input type="hidden" name="id" value="{esc(post["id"])}"><button class="ghost">نشر الآن</button></form>'
        )
    error = "" if not post.get("last_error") else (
        f'<div class="card" style="border-color:var(--bad)"><b style="color:var(--bad)">آخر خطأ</b>'
        f'<pre>{esc(post["last_error"])}</pre></div>')
    stats_rows = "".join(
        f'<tr><td>{esc(h["day"])}</td><td>{esc(h["views"])}</td><td>{esc(h["forwards"])}</td>'
        f'<td>{esc(h["reactions"])}</td></tr>'
        for h in reversed(history)
    ) or '<tr><td colspan="4" class="muted">لا لقطات بعد</td></tr>'
    body = f"""
<p><a href="/ui/content" class="muted">← المحتوى</a></p>
<h1>{esc(post["title"] or "بدون عنوان")}</h1>
<div class="row"><div>{badge(post["status"])} <span class="muted">· {esc(post.get("created_by"))}</span></div>
<span class="muted">{esc(channel.get("name") if channel else post.get("channel_jid"))}</span></div>
<div class="grid" style="margin-top:12px">
  <div class="stat"><b>{esc(views)}</b><span>مشاهدات</span></div>
  <div class="stat"><b>{esc(forwards)}</b><span>إعادة تمرير</span></div>
  <div class="stat"><b>{esc(reactions)}</b><span>تفاعل</span></div>
  <div class="stat"><b>{esc(engagement)}%</b><span>معدل التفاعل</span></div>
</div>
<div class="card">
  <div class="row"><span class="muted">مجدول: {fmt_ts(post.get("scheduled_at"))}</span>
  <span class="muted">نُشر: {fmt_ts(post.get("published_at"))}</span></div>
  <div class="row"><span class="muted">server_id: {esc(post.get("server_id") or "—")}</span>
  <span class="muted">message_id: {esc(post.get("message_id") or "—")}</span></div>
</div>
<h2>النص</h2>
<div class="card"><pre>{esc(post.get("body") or "")}</pre></div>
{error}
<h2>تطور التفاعل</h2>
<div class="card">{_bars(history, "views")}</div>
<div class="card"><table style="width:100%;border-collapse:collapse">
<tr class="muted"><td>اليوم</td><td>مشاهدات</td><td>تمرير</td><td>تفاعل</td></tr>
{stats_rows}
</table></div>
<div class="row">{actions}</div>
"""
    return page(post["title"] or "منشور", body, "content")


# --------------------------------------------------------------------- channel
def channel_page(info: dict | None, summary: dict, series: list[dict],
                 posts: list[dict]) -> bytes:
    name = (info or {}).get("name") or "قناة واتساب (لم تُقرأ بعد)"
    subs = (info or {}).get("subscribers")
    invite = (info or {}).get("invite") or ""
    fetched = fmt_ts((info or {}).get("fetched_at"))
    invite_html = f'<a href="{esc(invite)}" target="_blank">{esc(invite)}</a>' if invite else "—"
    top_rows = "".join(
        f'<div class="card"><div class="row"><div class="stack">'
        f'<b><a href="/ui/post/{esc(p["id"])}">{esc(p["title"] or (p["body"] or "")[:60])}</a></b>'
        f'<span class="muted">{fmt_ts(p.get("published_at"))}</span></div>'
        f'<span class="muted">👁 {esc(p["views"] or 0)} · ↪ {esc(p["forwards"] or 0)} · ♥ {esc(p["reactions"] or 0)}</span>'
        f'</div></div>' for p in summary.get("top", [])) or '<p class="muted">لا منشورات منشورة بعد.</p>'
    best = summary.get("best")
    best_html = ""
    if best:
        best_html = (f'<div class="card"><span class="muted">أفضل منشور</span><br>'
                     f'<b><a href="/ui/post/{esc(best["id"])}">{esc(best["title"] or (best["body"] or "")[:60])}</a></b>'
                     f' · 👁 {esc(best["views"] or 0)}</div>')
    body = f"""
<h1>{esc(name)}</h1>
<div class="row">
  <span class="muted">{esc((info or {}).get("jid") or "")}</span>
  <form method="post" action="/ui/channel/refresh"><button>تحديث بيانات القناة</button></form>
</div>
<div class="grid">
  <div class="stat"><b>{esc(subs if subs is not None else "—")}</b><span>مشتركون</span></div>
  <div class="stat"><b>{esc(summary.get("count", 0))}</b><span>منشور منشور</span></div>
  <div class="stat"><b>{esc(summary.get("views", 0))}</b><span>إجمالي المشاهدات</span></div>
  <div class="stat"><b>{esc(summary.get("avg_views", 0))}</b><span>متوسط المشاهدات/منشور</span></div>
  <div class="stat"><b>{esc(summary.get("forwards", 0))}</b><span>إعادة تمرير</span></div>
  <div class="stat"><b>{esc(summary.get("reactions", 0))}</b><span>تفاعل</span></div>
  <div class="stat"><b>{esc(summary.get("engagement_pct", 0))}%</b><span>معدل التفاعل</span></div>
  <div class="stat"><b>{esc(fetched)}</b><span>آخر قراءة من واتساب</span></div>
</div>
<div class="card"><span class="muted">رابط الدعوة: </span>{invite_html}</div>
{best_html}
<h2>التفاعل اليومي</h2>
<div class="card">{_bars(series, "views")}</div>
<h2>أفضل المنشورات</h2>
{top_rows}
"""
    return page("القناة", body, "channel")

