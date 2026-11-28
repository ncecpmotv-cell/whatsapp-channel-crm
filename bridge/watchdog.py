"""Watchdog: the failures that happen while nobody is looking.

Every few minutes: is WhatsApp still logged in, are publishes failing, is the disk filling,
is the channel snapshot stale. Each alert is deduplicated so a broken dependency produces one
notification per hour, not one per loop.
"""
from __future__ import annotations

import logging
import os
import shutil
import time

log = logging.getLogger("bridge.watchdog")

MIN_FREE_BYTES = 500 * 1024 * 1024
FAILED_WINDOW = 24 * 3600
FAILED_THRESHOLD = 3


def _alert(crm, code: str, title: str, body: str, now: float, cooldown: int = 3600) -> bool:
    key = f"watchdog:{code}:{int(now // cooldown)}"
    return bool(crm.notify("alert", title, body, "/ui", dedupe_key=key))


def check(crm, gowa, cfg, now: float | None = None) -> list[dict]:
    """Run every probe; return the alerts that fired (empty means healthy)."""
    now = time.time() if now is None else now
    fired: list[dict] = []

    try:
        status = gowa.device_status(timeout=4) or {}
        status = status.get("results") or status
        connected = bool(status.get("is_connected")) and bool(status.get("is_logged_in"))
        if not connected:
            if _alert(crm, "gowa", "واتساب غير متصل",
                      "البوابة لا ترى جلسة مسجّلة — افتح تطبيق واتساب وتأكد من الجهاز المرتبط.", now):
                fired.append({"code": "gowa", "detail": status})
    except Exception as exc:  # gateway down entirely
        if _alert(crm, "gowa-down", "بوابة واتساب لا تستجيب",
                  f"تعذّر الوصول إلى GOWA: {exc}", now):
            fired.append({"code": "gowa-down", "detail": str(exc)})

    failed = crm._one(
        "SELECT COUNT(*) AS n FROM crm_posts WHERE status='failed' AND updated_at >= ? "
        "AND COALESCE(last_error,'') NOT LIKE 'أُلغي%'", (now - FAILED_WINDOW,))
    count = int((failed or {}).get("n") or 0)
    if count >= FAILED_THRESHOLD:
        if _alert(crm, "publish-failures", "فشل نشر متكرر",
                  f"{count} محاولات فاشلة خلال 24 ساعة — راجع سجل المنشورات.", now):
            fired.append({"code": "publish-failures", "count": count})

    try:
        free = shutil.disk_usage(os.path.expanduser("~")).free
        if free < MIN_FREE_BYTES:
            if _alert(crm, "disk", "المساحة على وشك الانتهاء",
                      f"المتبقي {round(free / 1024 / 1024)}MB — احذف وسائط قديمة.", now):
                fired.append({"code": "disk", "free_bytes": free})
    except OSError:
        pass

    return fired


def start(crm, gowa, cfg) -> object:
    import threading

    interval = max(60, int(getattr(cfg, "watchdog_interval", 300)))

    def loop():
        from edge import from_config
        while True:
            try:
                fired = check(crm, gowa, cfg)
                client = from_config(cfg)
                if client.enabled():
                    try:
                        status = (gowa.device_status(timeout=4) or {}).get("results") or {}
                        sent = client.heartbeat({
                            "posts": crm.count_posts(),
                            "scheduled": crm.count_posts("scheduled"),
                            "gowa": bool(status.get("is_logged_in")),
                            "version": "4.0.0",
                            "backup": crm.store.get_meta("last_offsite_name") or "",
                        })
                        if sent:
                            crm.store.set_meta("last_heartbeat_at", str(int(time.time())))
                    except Exception as exc:
                        log.warning("heartbeat failed: %s", exc)
                if fired:
                    log.warning("watchdog alerts: %s", [a["code"] for a in fired])
                if getattr(cfg, "backup_enabled", True):
                    from backup import maybe_backup
                    maybe_backup(crm, cfg)
            except Exception as exc:  # never die
                log.warning("watchdog loop error: %s", exc)
            time.sleep(interval)

    thread = threading.Thread(target=loop, daemon=True, name="watchdog")
    thread.start()
    return thread
