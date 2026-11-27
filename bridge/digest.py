"""Weekly digest: the numbers and what to do next, delivered where the owner already looks.

Deterministic on purpose — no model call, so it costs nothing and never hallucinates.
Delivery uses the same Telegram bot PicoClaw already owns (token in `.security.yml`,
chat id in `config.json`), falling back to a Termux notification.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("bridge.digest")

WEEKDAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def telegram_creds(pico_home: str) -> tuple[str, str]:
    """(token, chat_id) from the PicoClaw home, or ('', '')."""
    config = os.path.join(pico_home, "config.json")
    security = os.path.join(pico_home, ".security.yml")
    token = chat = ""
    try:
        with open(security, encoding="utf-8") as fh:
            text = fh.read()
        block = re.search(r"telegram:\s*\n\s+settings:\s*\n\s+token:\s*(\S+)", text)
        if block:
            token = block.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    try:
        with open(config, encoding="utf-8") as fh:
            data = json.load(fh)
        channel = (data.get("channel_list") or {}).get("telegram") or {}
        allowed = channel.get("allow_from") or []
        chat = str(allowed[0]) if allowed else ""
    except (OSError, ValueError):
        pass
    return token, chat


def should_send(now: float, last_sent: float | None, weekday: int = 6, hour: int = 20,
                tz_offset: int = 3, grace_hours: int = 2) -> bool:
    """True once a week, inside a short window, and never twice for the same week."""
    local = dt.datetime.utcfromtimestamp(now) + dt.timedelta(hours=tz_offset)
    if local.weekday() != weekday:
        return False
    if not (hour <= local.hour < hour + grace_hours):
        return False
    if last_sent:
        elapsed = now - last_sent
        if elapsed < 6 * 86400:
            return False
    return True


def build_digest(crm, days: int = 7) -> str:
    metrics = crm.channel_metrics(days)
    total = metrics.get("total") or {}
    posts = int(total.get("posts") or 0)
    views = int(total.get("views") or 0)
    average = round(views / posts, 1) if posts else 0
    gaps = crm.content_gaps(90)
    plan = crm.get_plan()
    scheduled = crm.count_posts("scheduled")
    top_type = (gaps.get("per_type") or [{}])[0]
    opportunity = (gaps.get("opportunities") or [{}])[0]

    lines = [f"📊 تقرير الأسبوع — {dt.datetime.utcfromtimestamp(time.time()).strftime('%Y-%m-%d')}", ""]
    lines.append(f"• المنشورات: {posts} · المشاهدات: {views} · المتوسط: {average}")
    if top_type.get("type"):
        lines.append(f"• أفضل نوع: {top_type['type']} ({top_type.get('avg_views')} مشاهدة)")
    best = (crm.posting_times(90).get("best") or [{}])[0]
    if best.get("weekday"):
        lines.append(f"• أفضل وقت: {best['weekday']} {best.get('hour')}:00 ({best.get('avg_views')})")
    lines.append(f"• مجدول قادمًا: {scheduled}")
    if plan:
        state = "معتمدة" if plan.get("status") == "approved" else "مقترحة"
        lines.append(f"• خطة {plan['week_start']}: {state} ({len(plan.get('items') or [])} عناصر)")
    else:
        lines.append("• لا خطة للأسبوع القادم — اطلب: «خطة الأسبوع القادم»")
    if opportunity.get("term"):
        lines.append(f"• فرصة: «{opportunity['term']}» ({opportunity.get('posts')} منشورات، "
                     f"{opportunity.get('avg_views')} مشاهدة)")
    if posts < 10:
        lines.append("")
        lines.append("ملاحظة: عينة صغيرة — اقرأ الأرقام كمؤشر لا حكم.")
    return "\n".join(lines)


def send_telegram(token: str, chat: str, text: str, timeout: float = 8.0) -> bool:
    if not (token and chat):
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read()
        try:
            return bool(json.loads(body).get("ok"))
        except ValueError:
            # a truncated read used to fail here; a 2xx without parseable JSON is still a send
            return 200 <= getattr(response, "status", 200) < 300
    except Exception as exc:  # network / auth: never break the caller
        log.warning("telegram digest failed: %s", exc)
        return False


def termux_notify(title: str, body: str) -> bool:
    try:
        subprocess.run(["termux-notification", "--title", title, "--content", body],
                       check=False, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def deliver(crm, cfg, pico_home: str) -> dict:
    text = build_digest(crm)
    token, chat = telegram_creds(pico_home)
    sent = send_telegram(token, chat, text)
    if not sent:
        termux_notify("تقرير الأسبوع", text[:200])
    crm.notify("digest", "تقرير الأسبوع", text.splitlines()[2] if len(text.splitlines()) > 2 else "",
               "/ui")
    return {"sent": bool(sent), "telegram": bool(token and chat), "chars": len(text)}


def maybe_send(crm, cfg, pico_home: str, now: float | None = None) -> bool:
    """Called by the service loop; sends at most once per week."""
    now = time.time() if now is None else now
    last_raw = crm.store.get_meta("last_digest_at")
    last = float(last_raw) if last_raw else None
    weekday = int(getattr(cfg, "digest_weekday", 6))
    hour = int(getattr(cfg, "digest_hour", 20))
    if not should_send(now, last, weekday=weekday, hour=hour,
                       tz_offset=getattr(cfg, "tz_offset", 3)):
        return False
    result = deliver(crm, cfg, pico_home)
    crm.store.set_meta("last_digest_at", str(int(now)))
    log.info("weekly digest sent=%s chars=%s", result["sent"], result["chars"])
    return True


def start_scheduler(crm, cfg, pico_home: str, interval: int = 300) -> threading.Thread:
    def loop():
        while True:
            try:
                maybe_send(crm, cfg, pico_home)
            except Exception as exc:  # a digest must never kill the bridge
                log.warning("digest loop error: %s", exc)
            time.sleep(interval)

    thread = threading.Thread(target=loop, daemon=True, name="digest")
    thread.start()
    return thread
