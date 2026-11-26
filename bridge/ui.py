"""Server-rendered Arabic UI — one process, one port, zero JS build.

Pages: dashboard, content board, contacts, deals, metrics.
Every mutating action is a plain HTML form POST (works on any phone browser).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import os
import threading
import json
from urllib.parse import parse_qs

STAGES_AR = {
    "draft": "مسودة",
    "scheduled": "معتمد ومجدول",
    "publishing": "جارٍ النشر",
    "published": "منشور",
    "failed": "ملغى",
}
TYPE_AR = {
    "text": "نص", "image": "صورة", "video": "فيديو", "audio": "صوت",
    "file": "ملف", "link": "رابط", "poll": "استبيان", "none": "نص",
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
/* ---- tokens ---------------------------------------------------------- */
:root{
  --pico-font-family:"IBM Plex Sans Arabic",system-ui,-apple-system,"Segoe UI",sans-serif;
  --surface-0:#0f1512; --surface-1:#18211c; --surface-2:#0b110e;
  --line:#2a3a31; --ink:#eef3ee; --ink-2:#9db0a3;
  --accent:#c5a059; --accent-ink:#10160f; --ok:#4caf7d; --warn:#d9a04a; --bad:#d97474;
  --fs-1:13px; --fs-2:15px; --fs-3:17px; --fs-4:20px; --fs-5:22px;
  --sp-1:6px; --sp-2:10px; --sp-3:14px; --sp-4:20px;
  --r-1:10px; --r-2:14px;

  /* Pico mapping: one accent for every interactive element */
  --pico-primary:var(--accent); --pico-primary-hover:#d8b56f;
  --pico-primary-focus:rgba(197,160,89,.25);
  --pico-primary-background:var(--accent); --pico-primary-border:var(--accent);
  --pico-primary-hover-background:#d8b56f; --pico-primary-hover-border:#d8b56f;
  --pico-primary-inverse:var(--accent-ink);
  --pico-background-color:var(--surface-0); --pico-card-background-color:var(--surface-1);
  --pico-card-border-color:var(--line); --pico-border-color:var(--line);
  --pico-color:var(--ink); --pico-muted-color:var(--ink-2);
  --pico-form-element-background-color:#0d1411; --pico-form-element-border-color:var(--line);
  --pico-form-element-color:var(--ink); --pico-form-element-focus-color:var(--accent);
  --pico-h1-color:var(--ink); --pico-h2-color:var(--ink); --pico-h3-color:var(--ink);
  --pico-border-radius:var(--r-1); --pico-spacing:12px;
}
/* ---- base ------------------------------------------------------------ */
html{font-size:100%}
body{background:var(--surface-0);font-size:var(--fs-3);line-height:1.6;
  -webkit-text-size-adjust:100%;text-size-adjust:100%}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:var(--r-1)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
h1{font-size:var(--fs-5);line-height:1.35;margin:4px 0 var(--sp-3)}
h2{font-size:var(--fs-2);font-weight:700;color:var(--ink);display:flex;align-items:center;
  gap:8px;margin:var(--sp-4) 0 var(--sp-2);text-align:start}
h2::before{content:"";width:3px;height:16px;border-radius:2px;background:var(--accent);flex:0 0 3px}
/* ---- header ---------------------------------------------------------- */
header.top{display:flex;gap:var(--sp-2);align-items:center;flex-wrap:wrap;
  padding:10px 16px;border-bottom:1px solid var(--line);background:var(--surface-2);
  position:sticky;top:0;z-index:30}
header.top .brand{font-weight:700;color:var(--accent);margin-inline-end:auto;font-size:var(--fs-2)}
header.top nav{display:flex;gap:6px;flex-wrap:wrap}
header.top nav a{display:inline-flex;align-items:center;gap:6px;padding:8px 10px;
  border-radius:var(--r-1);border:1px solid var(--line);background:var(--surface-1);
  font-size:var(--fs-1);color:var(--ink-2);text-decoration:none;min-height:44px}
header.top nav a.on{color:var(--ink);border-color:var(--accent)}
header.top nav a svg{width:16px;height:16px;flex:0 0 16px}
.bell{display:inline-flex;align-items:center;justify-content:center;gap:4px;
  min-width:44px;min-height:44px;border-radius:var(--r-1);border:1px solid var(--line);
  background:var(--surface-1);color:var(--ink-2);font-size:var(--fs-1);text-decoration:none}
.bell.hot{color:var(--accent);border-color:var(--accent);font-weight:700}
/* ---- structure ------------------------------------------------------- */
main{padding-bottom:var(--sp-4)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:var(--sp-2);margin:var(--sp-2) 0}
.stat{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r-2);
  padding:var(--sp-3);display:flex;flex-direction:column;gap:2px;min-height:78px;justify-content:center}
.stat.zero b{color:var(--ink-2)}
.stat b{font-size:var(--fs-4);line-height:1.2;color:var(--accent);
  font-variant-numeric:tabular-nums;font-feature-settings:"tnum";font-weight:700}
.stat span{font-size:var(--fs-1);color:var(--ink-2);line-height:1.4}
.card{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r-2);
  padding:var(--sp-3);margin:var(--sp-2) 0}
.card pre{white-space:pre-wrap;margin:6px 0;font-family:inherit;font-size:var(--fs-2);color:var(--ink)}
.badge{display:inline-block;font-size:var(--fs-1);line-height:1.6;padding:2px 10px;
  border-radius:999px;border:1px solid var(--line);color:var(--ink-2);white-space:nowrap}
.badge.published{color:var(--ok);border-color:var(--ok)}
.badge.failed{color:var(--bad);border-color:var(--bad)}
.badge.scheduled{color:var(--warn);border-color:var(--warn)}
.badge.review{color:var(--accent);border-color:var(--accent)}
.muted{color:var(--ink-2);font-size:var(--fs-1);font-variant-numeric:tabular-nums}
.row{display:flex;justify-content:space-between;gap:var(--sp-2);align-items:flex-start;flex-wrap:wrap}
.stack{display:flex;flex-direction:column;gap:4px;min-width:0}
.chart{display:flex;align-items:flex-end;gap:4px;height:90px;margin-top:6px}
.chart .bar{flex:1;background:#0d1411;border-radius:4px;display:flex;align-items:flex-end;min-width:6px}
.chart .bar i{display:block;width:100%;background:linear-gradient(180deg,var(--accent),#3e4d42);border-radius:4px}
.notif{display:flex;gap:10px;align-items:flex-start}
.notif .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);margin-top:8px;flex:0 0 8px}
.notif.read{opacity:.6}
table{width:100%}
table td{padding:8px 4px;border-bottom:1px solid var(--line);font-size:var(--fs-1)}
button,input,select,textarea{font-size:var(--fs-2)}
button{min-height:44px;padding-inline:16px;font-weight:600}
/* ---- compact screens ------------------------------------------------- */
@media (max-width:640px){
  header.top{padding:8px 12px}
  header.top .brand{font-size:var(--fs-1);color:var(--ink-2);font-weight:600}
  header.top nav{position:fixed;inset-inline:0;bottom:0;display:flex;justify-content:space-between;
    background:var(--surface-2);border-top:1px solid var(--line);padding:2px 4px;
    padding-bottom:calc(2px + env(safe-area-inset-bottom));z-index:40;gap:0}
  header.top nav a{flex:1;flex-direction:column;gap:1px;border:none;background:transparent;
    font-size:9.5px;color:var(--ink-2);padding:2px 1px;min-height:42px;justify-content:center;
    border-top:2px solid transparent;border-radius:0}
  header.top nav a svg{width:16px;height:16px;flex:0 0 16px}
  header.top nav a.on{color:var(--accent);border-top-color:var(--accent);font-weight:700}
  main{padding-bottom:calc(150px + env(safe-area-inset-bottom)) !important}
  h1{font-size:var(--fs-4)}
  .grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .stat{min-height:74px;padding:10px 12px}
  .card{padding:12px}
  .row{flex-direction:column;align-items:flex-start}
  form{flex-direction:column;align-items:stretch}
  form button{width:100%}
  .row form{flex-direction:row}
  .row form button{width:auto}
}
/* ---- progressive disclosure ------------------------------------------ */
details.panel{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r-2);
  margin:var(--sp-2) 0;overflow:hidden}
details.panel>summary{list-style:none;cursor:pointer;padding:14px;display:flex;align-items:center;
  gap:8px;font-size:var(--fs-2);font-weight:600;min-height:52px}
details.panel>summary::-webkit-details-marker{display:none}
details.panel>summary::after{content:"›";margin-inline-start:auto;color:var(--ink-2);
  transition:transform .18s ease;display:inline-block;font-size:20px;line-height:1}
details.panel[open]>summary::after{transform:rotate(90deg)}
details.panel>.body{padding:0 14px 14px}
details.panel[open]>summary{border-bottom:1px solid var(--line)}
/* ---- filter chips ----------------------------------------------------- */
.chips{display:flex;flex-wrap:wrap;gap:8px;padding:2px 0 10px}
.chips a{display:inline-flex;align-items:center;min-height:29px;padding:0 9px;
  border-radius:999px;border:1px solid var(--line);background:var(--surface-1);color:var(--ink-2);
  font-size:11.5px;text-decoration:none;white-space:nowrap;
  transition:background .15s ease,color .15s ease,border-color .15s ease,transform .12s ease}
.chips a.on{background:rgba(197,160,89,.12);border-color:var(--accent);color:var(--accent);font-weight:700}
.chips a:active{transform:scale(.97)}
/* ---- header primary action (replaces the floating button) --------------- */
.head-act{display:none;align-items:center;justify-content:center;width:44px;height:44px;
  border-radius:12px;border:1px solid var(--accent);color:var(--accent);
  font-size:24px;line-height:1;text-decoration:none;background:rgba(197,160,89,.10);
  padding:0 0 2px}
.head-act:hover{background:rgba(197,160,89,.18)}
@media (max-width:640px){.head-act{display:inline-flex}}
@media (min-width:641px){.head-act{display:inline-flex;width:40px;height:40px;font-size:22px}}
/* ---- toast ------------------------------------------------------------ */
.toast{position:fixed;inset-inline:12px;bottom:calc(132px + env(safe-area-inset-bottom));z-index:60;
  display:flex;align-items:center;gap:10px;max-width:520px;margin-inline:auto;padding:12px 14px;
  border-radius:var(--r-2);background:#1d2a23;border:1px solid var(--accent);color:var(--ink);
  font-size:var(--fs-2);box-shadow:0 10px 30px rgba(0,0,0,.5);
  transition:opacity .2s ease,transform .2s ease}
.toast.out{opacity:0;transform:translateY(8px)}
@media (min-width:641px){.toast{bottom:24px}}
/* ---- skeleton --------------------------------------------------------- */
.skel{position:fixed;inset:0;z-index:70;background:rgba(11,17,14,.94);padding:76px 16px 16px;
  display:flex;flex-direction:column;gap:10px}
.skel .bar{height:14px;border-radius:8px;background:linear-gradient(90deg,#1b2620 25%,#24332b 37%,#1b2620 63%);
  background-size:400% 100%;animation:sh 1.2s ease-in-out infinite}
.skel .card-s{height:86px;border-radius:var(--r-2);border:1px solid var(--line);
  background:linear-gradient(90deg,#1b2620 25%,#24332b 37%,#1b2620 63%);
  background-size:400% 100%;animation:sh 1.2s ease-in-out infinite}
@keyframes sh{0%{background-position:100% 0}100%{background-position:0 0}}
/* ---- pull to refresh -------------------------------------------------- */
.ptr{position:fixed;top:0;inset-inline:0;height:var(--pull,0px);overflow:hidden;display:flex;
  align-items:center;justify-content:center;background:var(--surface-2);color:var(--accent);
  z-index:50;transition:height .1s linear;font-size:18px}
.ptr.on{transition:none}
/* ---- empty state ------------------------------------------------------ */
.empty{text-align:center;padding:28px 16px;border:1px dashed var(--line);
  border-radius:var(--r-2);color:var(--ink-2)}
.empty b{display:block;color:var(--ink);font-size:var(--fs-3);margin-bottom:6px}
.empty [role=button]{margin-top:12px}
/* ---- content card ----------------------------------------------------- */
.post{display:flex;flex-direction:column;gap:0}
.post-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:4px}
.post-head .badge{flex:0 0 auto;margin-top:2px;order:2}
.post-title{flex:1;min-width:0;font-size:var(--fs-2);font-weight:700;color:var(--ink);
  text-decoration:none;line-height:1.5}
.post-title:hover{color:var(--accent)}
.post .meta{margin:0 0 6px;padding-inline-start:0}
.post-body{margin:0 0 10px;font-size:var(--fs-2);line-height:1.6;color:var(--ink-2);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.post-error{margin:0 0 8px;font-size:var(--fs-1);color:var(--bad)}
.post-actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(86px,1fr));
  gap:8px;margin-top:2px}
.post-actions form{display:flex;flex-direction:column;gap:6px;margin:0;min-width:0}
.post-schedule{display:flex;flex-direction:row;gap:8px;align-items:center;margin:0 0 8px}
.post-schedule input[type=datetime-local]{flex:1;min-width:0;font-size:12px;min-height:38px;
  padding:4px 8px;margin:0}
.post-schedule input[type=datetime-local]{width:auto}
.post-schedule button{flex:0 0 auto;width:auto;min-height:38px;padding-inline:14px;font-size:12.5px}
.post-actions button{width:100%;font-size:12px;padding-inline:4px;min-height:38px;white-space:nowrap}
/* ---- buttons ---------------------------------------------------------- */
button.ghost,a.ghost{background:transparent;border:1px solid var(--line);color:var(--ink)}
button.ghost:hover,a.ghost:hover{background:var(--surface-2);border-color:var(--accent)}
button.subtle,a.subtle{background:transparent;border:1px solid var(--line);color:var(--ink-2);font-weight:500}
button.subtle:hover{color:var(--ink);border-color:var(--ink-2)}
button.subtle.danger{color:#c98b8b;border-color:#4a2f2f}
button.subtle.danger:hover{color:#e8a0a0;border-color:#7a4444}
/* ---- editor (post detail) -------------------------------------------- */
.notice{border-color:var(--accent);background:rgba(197,160,89,.08);margin-bottom:10px}
.notice b{color:var(--accent);font-size:var(--fs-2)}
.editor label{display:block;margin:0 0 10px}
.editor input,.editor textarea{width:100%;margin:0}
.editor textarea{min-height:140px;line-height:1.6}
.editor > button,.editor button[type=submit]{width:100%}
/* ---- pagination ------------------------------------------------------- */
.pager{display:flex;align-items:center;justify-content:center;gap:6px;flex-wrap:wrap;
  margin:18px 0 6px}
.pager .pg{min-width:38px;height:38px;display:inline-flex;align-items:center;justify-content:center;
  border:1px solid var(--line);border-radius:11px;color:var(--ink-2);text-decoration:none;
  font-size:14px;font-variant-numeric:tabular-nums;background:var(--surface-1)}
.pager a.pg,.pager a.pg:link,.pager a.pg:visited{color:var(--ink-2);text-decoration:none}
.pager span.pg.on{border-color:var(--accent);color:var(--accent);background:rgba(197,160,89,.14);font-weight:700}
.pager a.pg:hover{border-color:var(--accent);color:var(--ink)}
.pager .pg.on{background:rgba(197,160,89,.14);border-color:var(--accent);color:var(--accent);font-weight:700}
.pager .pg.nav{font-size:20px;line-height:1}
.pager .pg.off{opacity:.35}
.pager .pg.gap{border:none;background:transparent;min-width:20px;color:var(--ink-2)}
.pager-info{text-align:center;margin:0 0 var(--sp-2)}
/* ---- micro-interactions ----------------------------------------------- */
.card,header.top nav a,.stat,button{transition:border-color .15s ease,transform .15s ease,opacity .15s ease}
.card:active{transform:scale(.997)}
button[disabled]{opacity:.6}
"""


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


TZ_OFFSET = 3  # hours; app.py sets this from config at startup


def fmt_ts(ts) -> str:
    if not ts:
        return "—"
    local = dt.datetime.utcfromtimestamp(int(ts)) + dt.timedelta(hours=TZ_OFFSET)
    return local.strftime("%Y-%m-%d %H:%M")


def write_stylesheet(directory: str) -> str:
    """Publish the CSS as a cacheable static file (and its .gz twin)."""
    import gzip
    import os

    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "app.css")
    data = CSS.encode("utf-8")
    current = b""
    if os.path.exists(path):
        with open(path, "rb") as fh:
            current = fh.read()
    if current != data:
        with open(path, "wb") as fh:
            fh.write(data)
        with open(path + ".gz", "wb") as fh:
            fh.write(gzip.compress(data, 9))
    return path


_UNREAD = 0
_FLASH = threading.local()
_JS_VERSION: str | None = None


def css_version() -> str:
    return hashlib.sha1(CSS.encode("utf-8")).hexdigest()[:8]


def js_version() -> str:
    global _JS_VERSION
    if _JS_VERSION is None:
        try:
            with open(os.path.join(os.path.dirname(__file__), "static", "app.js"), "rb") as fh:
                _JS_VERSION = hashlib.sha1(fh.read()).hexdigest()[:8]
        except OSError:
            _JS_VERSION = "0"
    return _JS_VERSION


def set_flash(message: str) -> None:
    _FLASH.msg = message


def flash_text() -> str:
    return getattr(_FLASH, "msg", "")


_HEADER = threading.local()


def set_header_action(markup: str) -> None:
    _HEADER.action = markup


def header_action() -> str:
    return getattr(_HEADER, "action", "")


def set_unread(count: int) -> None:
    global _UNREAD
    _UNREAD = max(0, int(count or 0))


def page(title: str, body: str, active: str = "") -> bytes:
    icons = {
        "today": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18"/></svg>',
        "content": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/><path d="M10 13h6M10 17h6"/></svg>',
        "contacts": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="8" r="3.2"/><path d="M5 20c1.5-3.5 4-5 7-5s5.5 1.5 7 5"/></svg>',
        "deals": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.4"/><path d="M12 4v3M12 17v3M4 12h3M17 12h3"/></svg>',
        "channel": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 10v4a2 2 0 0 0 2 2h2l6 4V4L8 8H6a2 2 0 0 0-2 2z"/><path d="M18 9a4 4 0 0 1 0 6"/></svg>',
    }
    nav = [
        ("/ui", "اليوم", "today"),
        ("/ui/content", "المحتوى", "content"),
        ("/ui/contacts", "العملاء", "contacts"),
        ("/ui/deals", "الفرص", "deals"),
        ("/ui/channel", "القناة", "channel"),
    ]
    links = "".join(
        f'<a href="{href}" class="{"on" if key == active else ""}"'
        f'{" aria-current=\"page\"" if key == active else ""}>'
        f'{icons.get(key, "")}<span>{label}</span></a>'
        for href, label, key in nav
    )
    bell = (f'<a class="bell{" hot" if _UNREAD else ""}" href="/ui/notifications" '
            f'aria-label="🔔 الإشعارات {_UNREAD if _UNREAD else ""}">🔔'
            f'{_UNREAD if _UNREAD else ""}</a>')
    flash = flash_text()
    head_act = header_action()
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(title)} · CRM</title>
<meta name="theme-color" content="#0f1512">
<meta name="description" content="إدارة محتوى قناة واتساب والعملاء والفرص من الجوال: مسودة → معتمد ومجدول → منشور، مع قياسات القناة.">
<link rel="manifest" href="/ui/manifest.webmanifest">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%230f1512'/%3E%3Ccircle cx='16' cy='16' r='7' fill='none' stroke='%23c5a059' stroke-width='2.5'/%3E%3C/svg%3E">
<link rel="stylesheet" href="/static/pico.min.css">
<link rel="stylesheet" href="/static/app.css?v={css_version()}"></head>
<body dir="rtl">
<div class="ptr" id="ptr" aria-hidden="true">↻</div>
<div class="toast" id="toast" role="status" aria-live="polite" data-msg="{esc(flash)}"{" hidden" if not flash else ""}>
  <span aria-hidden="true">✓</span><span>{esc(flash)}</span></div>
<div class="skel" id="skel" hidden aria-hidden="true">
  <div class="bar" style="width:45%"></div><div class="card-s"></div><div class="card-s"></div><div class="card-s"></div>
  <div class="bar" style="width:65%"></div><div class="bar" style="width:35%"></div>
</div>
<header class="top"><span class="brand">CRM · قناة واتساب</span>{head_act}{bell}<nav>{links}</nav></header>
<main class="container">{body}</main>
<script src="/static/app.js?v={js_version()}" defer></script></body></html>"""
    return doc.encode("utf-8")


def badge(status: str) -> str:
    return f'<span class="badge {esc(status)}">{esc(STAGES_AR.get(status, status))}</span>'


# ------------------------------------------------------------------ dashboard
def dashboard(stats: dict, scheduled: list[dict], followups: list[dict],
              unread: int, metrics: dict) -> bytes:
    def stat(k, v) -> str:
        zero = " zero" if str(v) in ("0", "") else ""
        return f'<div class="stat{zero}"><b>{esc(v)}</b><span>{esc(k)}</span></div>'

    cards = "".join(
        stat(k, v)
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
  {stat("مشاهدات", total.get("views", 0))}
  {stat("إعادة تمرير", total.get("forwards", 0))}
  {stat("تفاعل", total.get("reactions", 0))}
  {stat("رسائل غير مقروءة", unread)}
</div>
<details class="panel"{' open' if scheduled else ''}>
  <summary>مجدول <span class="badge scheduled">{len(scheduled)}</span></summary>
  <div class="body">{sched_rows}</div>
</details>
<details class="panel"{' open' if followups else ''}>
  <summary>متابعات مستحقة <span class="badge review">{len(followups)}</span></summary>
  <div class="body">{follow_rows}</div>
</details>
"""
    return page("اليوم", body, "today")


# -------------------------------------------------------------------- content
def content_page(posts: list[dict], status: str = "", error: str = "",
                 page_no: int = 1, pages: int = 1) -> bytes:
    set_header_action('<a class="head-act" href="#newContent" data-composer '
                      'aria-label="محتوى جديد" aria-controls="newContent">+</a>')
    query = f"status={status}&" if status else ""
    chip_items = [("", "الكل")] + [(k, v) for k, v in STAGES_AR.items() if k != "publishing"]
    filters = "".join(
        f'<a href="/ui/content{"?status=" + key if key else ""}" class="{"on" if status == key else ""}"'
        f'{" aria-current=\"true\"" if status == key else ""}>{esc(label)}</a>'
        for key, label in chip_items
    )
    errors = {
        "poll_options": "الاستبيان يحتاج سؤالًا وخيارين على الأقل (سطر لكل خيار).",
        "link": "أدخل رابطًا يبدأ بـ http:// أو https://",
        "media_required": "اختر ملفًا للنوع المحدد.",
        "media_too_big": "الملف أكبر من 20 ميغابايت.",
        "media_type": "نوع الملف غير مدعوم لهذا النوع (صور: jpg/png/webp · فيديو: mp4/mov · صوت: mp3/ogg · ملفات: pdf/office/zip).",
    }
    banner = ""
    if error:
        banner = (f'<div class="card" style="border-color:var(--bad)">'
                  f'<b style="color:var(--bad)">تعذّر الإنشاء</b>'
                  f'<p class="muted">{esc(errors.get(error, error))}</p></div>')

    rows = []
    for p in posts:
        pid = esc(p["id"])
        when = fmt_ts(p.get("scheduled_at") or p.get("published_at"))
        kind = p.get("media_type") or "text"
        st = p["status"]
        text = (p.get("body") or "").strip()
        actions = []
        schedule_html = ""
        if st == "draft":
            schedule_html = (
                f'<form method="post" action="/ui/content/schedule" class="post-schedule">'
                f'<input type="hidden" name="id" value="{pid}">'
                f'<input type="datetime-local" name="at" required aria-label="موعد النشر">'
                f'<button class="ghost">جدولة</button></form>')
        if st in ("draft", "scheduled"):
            actions.append(
                f'<form method="post" action="/ui/content/publish" '
                f"onsubmit=\"return confirm('النشر إلى القناة لا يمكن التراجع عنه. أرسِل الآن؟')\">"
                f'<input type="hidden" name="id" value="{pid}">'
                f'<button aria-label="نشر الآن">نشر</button></form>')
        if st == "scheduled":
            actions.append(
                f'<form method="post" action="/ui/content/status">'
                f'<input type="hidden" name="id" value="{pid}">'
                f'<input type="hidden" name="status" value="draft">'
                f'<button class="ghost" aria-label="إرجاع إلى مسودة">لمسودة</button></form>')
        if st in ("draft", "scheduled", "publishing"):
            actions.append(
                f'<form method="post" action="/ui/content/cancel" '
                f'data-confirm="إلغاء هذا العنصر؟ سيبقى في الأرشيف بحالة ملغى.">'
                f'<input type="hidden" name="id" value="{pid}">'
                f'<button class="subtle">إلغاء</button></form>')
        if st == "failed":
            actions.append(
                f'<form method="post" action="/ui/content/restore">'
                f'<input type="hidden" name="id" value="{pid}">'
                f'<button class="ghost">استعادة كمسودة</button></form>')
            actions.append(
                f'<form method="post" action="/ui/content/delete" '
                f'data-confirm="حذف نهائي؟ لا يمكن التراجع.">'
                f'<input type="hidden" name="id" value="{pid}">'
                f'<button class="subtle danger">حذف نهائي</button></form>')
        actions_html = ("" if not actions
                        else '<div class="post-actions">' + "".join(actions) + "</div>")
        rows.append(f"""
<article class="card post">
  <div class="post-head">
    <a class="post-title" href="/ui/post/{pid}">{esc(p["title"] or text[:70] or "بدون عنوان")}</a>
    {badge(st)}
  </div>
  <p class="muted meta">{esc(TYPE_AR.get(kind, kind))} · {'🕒 يُنشر ' if st == 'scheduled' else ''}{when}</p>
  {"" if not text else f'<p class="post-body">{esc(text[:160])}</p>'}
  {schedule_html}
  {"" if not p.get("last_error") else f'<p class="post-error">{esc(p["last_error"])}</p>'}
  {actions_html}
</article>""")

    def page_link(n: int) -> str:
        if n == page_no:
            return f'<span class="pg on" aria-current="page">{n}</span>'
        return f'<a class="pg" href="/ui/content?{query}page={n}">{n}</a>'

    pager = ""
    if pages > 1:
        nums, last = [], 0
        for n in sorted({1, pages, *range(max(1, page_no - 2), min(pages, page_no + 2) + 1)}):
            if n - last > 1:
                nums.append('<span class="pg gap">…</span>')
            nums.append(page_link(n))
            last = n
        prev_a = (f'<a class="pg nav" href="/ui/content?{query}page={page_no - 1}" aria-label="الصفحة السابقة">›</a>'
                  if page_no > 1 else '<span class="pg nav off" aria-hidden="true">›</span>')
        next_a = (f'<a class="pg nav" href="/ui/content?{query}page={page_no + 1}" aria-label="الصفحة التالية">‹</a>'
                  if page_no < pages else '<span class="pg nav off" aria-hidden="true">‹</span>')
        pager = (f'<p class="muted pager-info">صفحة {page_no} من {pages}</p>'
                 f'<nav class="pager" aria-label="ترقيم الصفحات">{prev_a}{"".join(nums)}{next_a}</nav>')

    empty_state = ('<div class="empty"><b>لا محتوى بعد</b>'
                   '<p>ابدأ بأول فكرة أو مسودة، وسيظهر هنا.</p>'
                   '<a role="button" href="#newContent" data-composer>إنشاء محتوى</a></div>')
    body = f"""
<h1>المحتوى</h1>
{banner}
<div class="chips" role="navigation" aria-label="تصفية حسب الحالة">{filters}</div>
<details class="panel" id="newContent">
<summary>محتوى جديد</summary>
<div class="body">
<form method="post" action="/ui/content/new" enctype="multipart/form-data" class="composer">
  <label>النوع
    <select name="type" id="ctype">
      <option value="text">نص</option>
      <option value="image">صورة</option>
      <option value="video">فيديو</option>
      <option value="audio">صوت</option>
      <option value="file">ملف</option>
      <option value="link">رابط</option>
      <option value="poll">استبيان (غير مدعوم في القنوات)</option>
    </select>
  </label>
  <label>عنوان <input name="title" placeholder="عنوان مختصر"></label>
  <label>النص <textarea name="body" placeholder="نص المنشور"></textarea></label>
  <label id="mediaRow" hidden>الملف <input type="file" name="media" accept="image/*,video/*,audio/*,application/pdf"></label>
  <label id="linkRow" hidden>الرابط <input name="url" inputmode="url" placeholder="https://..."></label>
  <label id="pollRow" hidden>خيارات الاستبيان <textarea name="options" placeholder="سطر لكل خيار"></textarea></label>
  <label>موعد النشر (اختياري) <input type="datetime-local" name="at"></label>
  <button>إنشاء</button>
</form>
</div>
</details>
<p class="muted">النشر النهائي قرار بشري: «نشر الآن» أو «جدولة». الاستبيانات لا تدعمها قنوات واتساب (خطأ 479) وتُرسل في المحادثات فقط.</p>
<h2>العناصر <span class="muted">— صفحة {page_no}</span></h2>
{''.join(rows) or empty_state}
{pager}
"""
    return page("المحتوى", body, "content")

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
    """`datetime-local` input is wall-clock time in the owner's timezone (UTC+3)."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return int(parsed.timestamp())
    utc_naive = parsed - dt.timedelta(hours=TZ_OFFSET)
    return int(utc_naive.replace(tzinfo=dt.timezone.utc).timestamp())


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


def post_page(post: dict, history: list[dict], channel: dict | None, notice: str = "") -> bytes:
    views = post.get("views") or 0
    forwards = post.get("forwards") or 0
    reactions = post.get("reactions") or 0
    engagement = round((forwards + reactions) * 100 / views, 2) if views else 0
    pid = esc(post["id"])
    actions = ""
    if post["status"] in ("draft", "scheduled"):
        publish_class = "" if post["status"] == "scheduled" else "ghost"
        actions += (
            f'<form method="post" action="/ui/content/publish" '
            f"onsubmit=\"return confirm('النشر إلى القناة لا يمكن التراجع عنه. أرسِل الآن؟')\">"
            f'<input type="hidden" name="id" value="{pid}">'
            f'<button class="{publish_class}">نشر الآن</button></form>')
    if post["status"] == "scheduled":
        actions += (
            f'<form method="post" action="/ui/content/status">'
            f'<input type="hidden" name="id" value="{pid}">'
            f'<input type="hidden" name="status" value="draft">'
            f'<button class="subtle">إرجاع لمسودة</button></form>')
    if post["status"] in ("draft", "scheduled", "publishing"):
        actions += (
            f'<form method="post" action="/ui/content/cancel" '
            f'data-confirm="إلغاء هذا العنصر؟ سيبقى في الأرشيف بحالة ملغى.">'
            f'<input type="hidden" name="id" value="{pid}">'
            f'<button class="subtle">إلغاء</button></form>')
    if post["status"] == "failed":
        actions += (
            f'<form method="post" action="/ui/content/restore">'
            f'<input type="hidden" name="id" value="{pid}">'
            f'<button class="subtle">استعادة كمسودة</button></form>')
    error = "" if not post.get("last_error") else (
        f'<div class="card" style="border-color:var(--bad)"><b style="color:var(--bad)">آخر خطأ</b>'
        f'<pre>{esc(post["last_error"])}</pre></div>')
    kind = post.get("media_type") or "text"
    poll_block = ""
    if kind == "poll":
        try:
            options = json.loads(post.get("meta") or "{}").get("options") or []
        except Exception:  # noqa: BLE001
            options = []
        poll_block = ('<div class="card"><b>خيارات الاستبيان</b><ul class="muted">'
                      + "".join(f"<li>{esc(o)}</li>" for o in options) + "</ul>"
                      '<p class="muted">قنوات واتساب لا تدعم الاستبيانات (خطأ 479).</p></div>')
    delete_block = ""
    edit_block = ""
    if post["status"] == "failed":
        delete_block = (
            f'<form method="post" action="/ui/content/delete" '
            f'data-confirm="حذف نهائي؟ لا يمكن التراجع.">'
            f'<input type="hidden" name="id" value="{pid}">'
            f'<button class="subtle danger">حذف نهائي</button></form>'
        )
    if post["status"] in ("draft", "scheduled"):
        edit_block = f"""
<h2>تعديل</h2>
<form method="post" action="/ui/content/edit">
  <input type="hidden" name="id" value="{esc(post["id"])}">
  <label>العنوان <input name="title" value="{esc(post.get("title") or "")}"></label>
  <label>النص <textarea name="body">{esc(post.get("body") or "")}</textarea></label>
  <label>إعادة جدولة إلى <input type="datetime-local" name="at"></label>
  <button>حفظ التعديل</button>
</form>
"""
    editable = post["status"] in ("draft", "scheduled")
    when = post.get("scheduled_at")
    when_value = ""
    if when:
        local = dt.datetime.utcfromtimestamp(int(when)) + dt.timedelta(hours=TZ_OFFSET)
        when_value = local.strftime("%Y-%m-%dT%H:%M")
    type_label = TYPE_AR.get(post.get("media_type") or "text", "نص")
    channel_label = esc((channel or {}).get("name") or "")

    author = esc(post.get("created_by") or "")
    meta = [type_label, f"بواسطة {author}" if author else "", channel_label]
    meta_line = " · ".join(m for m in meta if m)
    when_line = ""
    if post["status"] == "scheduled" and when:
        when_line = f'<p class="muted meta">🕒 يُنشر {fmt_ts(when)}</p>'
    elif post.get("published_at"):
        when_line = f'<p class="muted meta">✅ نُشر {fmt_ts(post["published_at"])}</p>'

    editor = ""
    if editable:
        schedule_label = "إعادة الجدولة إلى" if post["status"] == "scheduled" else "جدولة إلى (اختياري)"
        save_class = "ghost" if post["status"] == "scheduled" else ""
        save_hint = ("حفظ يحدّث الموعد إن غيّرته." if post["status"] == "scheduled"
                     else "أضف موعدًا ليُجدول تلقائيًا، أو اتركه فارغًا ليبقى مسودة.")
        editor = f"""
<h2>محتوى المنشور</h2>
<form method="post" action="/ui/content/edit" class="editor">
  <input type="hidden" name="id" value="{esc(post["id"])}">
  <label>العنوان
    <input name="title" value="{esc(post.get("title") or "")}" placeholder="عنوان مختصر"></label>
  <label>النص
    <textarea name="body" rows="7" placeholder="نص المنشور">{esc(post.get("body") or "")}</textarea></label>
  <label>{schedule_label}
    <input type="datetime-local" name="at" value="{when_value}"></label>
  <button class="{save_class}">حفظ التعديل</button>
  <p class="muted" style="margin:6px 0 0">{save_hint}</p>
</form>"""

    metrics = ""
    if post["status"] == "published" or views:
        stats_rows = "".join(
            f'<tr><td>{esc(h["day"])}</td><td>{esc(h["views"])}</td><td>{esc(h["forwards"])}</td>'
            f'<td>{esc(h["reactions"])}</td></tr>'
            for h in reversed(history)
        ) or '<tr><td colspan="4" class="muted">لا لقطات بعد</td></tr>'
        metrics = f"""
<h2>الأداء</h2>
<div class="grid">
  <div class="stat"><b>{esc(views)}</b><span>مشاهدات</span></div>
  <div class="stat"><b>{esc(forwards)}</b><span>إعادة تمرير</span></div>
  <div class="stat"><b>{esc(reactions)}</b><span>تفاعل</span></div>
  <div class="stat"><b>{esc(engagement)}%</b><span>معدل التفاعل</span></div>
</div>
<div class="card">{_bars(history, "views")}</div>
<div class="card"><table style="width:100%;border-collapse:collapse">
<tr class="muted"><td>اليوم</td><td>مشاهدات</td><td>تمرير</td><td>تفاعل</td></tr>
{stats_rows}
</table></div>"""

    ids = ""
    if post.get("server_id") or post.get("message_id"):
        ids = (f'<p class="muted meta">server_id {esc(post.get("server_id") or "—")} · '
               f'message_id {esc(post.get("message_id") or "—")}</p>')

    body_html = f"""
<p><a href="/ui/content" class="muted">← المحتوى</a></p>
<div class="post-head" style="margin-bottom:8px">
  <h1 style="margin:0;font-size:var(--fs-4);line-height:1.35">{esc(post["title"] or "بدون عنوان")}</h1>
  {badge(post["status"])}
</div>
<p class="muted meta">{meta_line}</p>
{when_line}
{"" if not notice else f'<div class="card notice"><b>{esc(notice)}</b></div>'}
{editor}
{"" if editable else f'<h2>النص</h2><div class="card"><pre>{esc(post.get("body") or "")}</pre></div>'}
{error}
{poll_block}
{metrics}
{ids}
{"" if not actions and not delete_block else '<div class="post-actions" style="margin-top:12px">' + actions + delete_block + "</div>"}
"""
    return page(post["title"] or "منشور", body_html, "content")


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
  <form method="post" action="/ui/channel/sync"><button>مزامنة أرشيف القناة</button></form>
  <form method="post" action="/ui/channel/refresh"><button class="ghost">تحديث بيانات القناة</button></form>
</div>
<div class="grid">
  <div class="stat"><b>{esc(subs if subs is not None else "—")}</b><span>{"مشترك" if subs == 1 else "مشتركون"}</span></div>
  <div class="stat"><b>{esc(summary.get("count", 0))}</b><span>منشور</span></div>
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




# ----------------------------------------------------------------- notifications
def notifications_page(items: list[dict]) -> bytes:
    cards = []
    for n in items:
        classes = "card notif" + ("" if not n["read"] else " read")
        dot = "" if n["read"] else '<span class="dot"></span>'
        body = f'<span class="muted">{esc(n["body"])}</span>' if n.get("body") else ""
        link = f'<a class="muted" href="{esc(n["link"])}">فتح ←</a>' if n.get("link") else ""
        cards.append(
            f'<div class="{classes}">{dot}<div class="stack" style="flex:1">'
            f'<b>{esc(n["title"])}</b>{body}'
            f'<span class="muted">{fmt_ts(n["at"])}</span>{link}</div></div>'
        )
    rows = "".join(cards) or '<p class="muted">لا إشعارات بعد.</p>'
    body_html = f"""
<h1>الإشعارات</h1>
<form method="post" action="/ui/notifications/read"><button class="ghost">تحديد الكل كمقروء</button></form>
{rows}
"""
    return page("الإشعارات", body_html, "")