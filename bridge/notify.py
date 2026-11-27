"""Push notifications: Telegram bot and Termux:API, best-effort and off the hot path.

The bell inside the app is a record; this module is what reaches a locked phone.
It never raises: a push failure must not roll back a delete or a publish.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request

log = logging.getLogger("bridge.push")

DEFAULT_EVENTS = "publish,failed"


def _post(url: str, payload: dict, timeout: float = 6.0) -> bool:
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed host)
        body = resp.read(400)
    try:
        return bool(json.loads(body).get("ok"))
    except Exception:
        return True


class PushNotifier:
    """Sends a notification to every configured channel; channels are independent."""

    def __init__(self, cfg, sender=None):
        self.token = getattr(cfg, "telegram_bot_token", "") or ""
        self.chat_id = getattr(cfg, "telegram_chat_id", "") or ""
        self.events = {
            e.strip() for e in (getattr(cfg, "push_events", "") or DEFAULT_EVENTS).split(",")
            if e.strip()
        }
        self.base_url = (getattr(cfg, "public_base_url", "") or "").rstrip("/")
        self._sender = sender or _post

    # -- channels ---------------------------------------------------------
    def telegram_ready(self) -> bool:
        return bool(self.token and self.chat_id)

    def termux_ready(self) -> bool:
        return shutil.which("termux-notification") is not None

    def enabled(self) -> bool:
        return bool(self.events) and (self.telegram_ready() or self.termux_ready())

    def wants(self, kind: str) -> bool:
        # "content" (drafts lifecycle) and "publish" are the two kinds we emit today
        return kind in self.events or "all" in self.events

    # -- public API -------------------------------------------------------
    def send(self, kind: str, title: str, body: str = "", link: str = "") -> None:
        if not self.enabled() or not self.wants(kind):
            return
        url = f"{self.base_url}{link}" if link.startswith("/") and self.base_url else link
        threading.Thread(
            target=self._send_safely, args=(kind, title, body, url),
            daemon=True, name="push",
        ).start()

    def _send_safely(self, kind: str, title: str, body: str, url: str) -> None:
        for channel in self._channels():
            try:
                channel(title, body, url)
            except Exception as exc:  # never propagate
                log.warning("push via %s failed: %s", getattr(channel, "__name__", "?"), exc)

    def _channels(self):
        if self.telegram_ready():
            yield self._telegram
        if self.termux_ready():
            yield self._termux

    def _telegram(self, title: str, body: str, url: str) -> None:
        text = f"*{title}*\n{body}" + (f"\n{url}" if url else "")
        ok = self._sender(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown",
             "disable_web_page_preview": "true"},
        )
        if not ok:
            log.warning("telegram rejected the message (check chat id / bot rights)")

    def _termux(self, title: str, body: str, url: str) -> None:
        args = ["termux-notification", "--title", title, "--content", body or title]
        if url:
            args += ["--url", url]
        subprocess.run(args, check=False, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def describe(cfg) -> dict:
    """What the UI/health can report without leaking secrets."""
    n = PushNotifier(cfg)
    return {
        "telegram": n.telegram_ready(),
        "termux": n.termux_ready(),
        "events": sorted(n.events),
        "enabled": n.enabled(),
    }
