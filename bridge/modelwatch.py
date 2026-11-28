"""Model failover without a third-party gateway.

FreeRide's value is failover + rotation. On this phone `pip` is broken (Termux's libexpat is older
than Python 3.14 expects) so a local gateway would need a full OS upgrade. This module gives the
same outcome with zero dependencies: probe the primary provider's /models endpoint (no tokens
spent), switch the agent to the fallback when it fails, switch back when it recovers, and notify.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

log = logging.getLogger("bridge.modelwatch")

PROBE_TIMEOUT = 8.0


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def read_models(home: str) -> list[dict]:
    home = os.path.expanduser(home or "~/pico")
    config = _read(os.path.join(home, "config.json")) or {}
    keys = read_keys(os.path.join(home, ".security.yml"))
    models = []
    for entry in config.get("model_list") or []:
        name = entry.get("model_name")
        models.append({
            "name": name,
            "base": (entry.get("api_base") or "").rstrip("/"),
            "model": entry.get("model"),
            "key": keys.get(name) or "",
            "enabled": entry.get("enabled", True),
        })
    return models


def read_keys(security_path: str) -> dict[str, str]:
    """Minimal parser for the one shape PicoClaw writes:
        model_list:
          <name>:0:
            api_keys:
              - <key>
    """
    try:
        text = open(security_path, encoding="utf-8").read()
    except OSError:
        return {}
    keys: dict[str, str] = {}
    for match in re.finditer(r"^  ([A-Za-z0-9_.-]+):0:\s*\n\s+api_keys:\s*\n\s+- (\S+)", text, re.M):
        keys[match.group(1)] = match.group(2).strip()
    return keys


def probe(model: dict, timeout: float = PROBE_TIMEOUT) -> tuple[bool, str]:
    """Cheap liveness check: GET /models costs no tokens."""
    base = model.get("base") or ""
    if not base:
        return False, "no api_base"
    url = base + ("/models" if not base.endswith("/models") else "")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {model.get('key') or 'none'}",
        "User-Agent": "phone-crm-modelwatch/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            if response.status == 200:
                return True, "ok"
            return False, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return (exc.code < 500 and exc.code != 429), f"HTTP {exc.code}"
    except Exception as exc:  # network, DNS, timeout
        return False, str(exc)[:120]


def current_model(home: str) -> str:
    home = os.path.expanduser(home or "~/pico")
    config = _read(os.path.join(home, "config.json")) or {}
    return ((config.get("agents") or {}).get("defaults") or {}).get("model_name") or "default"


def switch(name: str, home: str) -> tuple[bool, str]:
    binary = os.path.join(os.path.expanduser(home or "~/pico"), "bin", "picoclaw")
    if not os.path.isfile(binary):
        return False, "picoclaw binary not found"
    env = dict(os.environ, PICOCLAW_HOME=os.path.expanduser(home or "~/pico"))
    result = subprocess.run([binary, "model", name], capture_output=True, text=True, env=env,
                            timeout=40)
    return result.returncode == 0, (result.stdout or result.stderr or "").strip()[:200]


def check(crm, cfg, home: str = "") -> dict:
    """One pass: probe the primary, switch only on a real failure, switch back on recovery."""
    home = home or getattr(cfg, "picoclaw_home", "") or "~/pico"
    models = [m for m in read_models(home) if m.get("enabled", True)]
    primary = models[0] if models else None
    fallback = models[1] if len(models) > 1 else None
    if not primary:
        return {"ok": False, "error": "no models configured"}

    healthy, reason = probe(primary)
    active = current_model(home)
    switched = None
    if not healthy and fallback and active != fallback["name"]:
        ok, output = switch(fallback["name"], home)
        switched = {"to": fallback["name"], "ok": ok, "output": output}
        crm.notify("model", "تحويل إلى النموذج البديل",
                   f"{primary['name']} لا يستجيب ({reason}) → {fallback['name']}", "/ui/capabilities")
    elif healthy and active != primary["name"]:
        ok, output = switch(primary["name"], home)
        switched = {"to": primary["name"], "ok": ok, "output": output, "recovered": True}
        crm.notify("model", "عودة النموذج الأساسي",
                   f"{primary['name']} يعمل مرة أخرى", "/ui/capabilities")

    state = {"ok": True, "primary": primary["name"], "active": current_model(home),
             "healthy": healthy, "reason": reason, "fallback": (fallback or {}).get("name"),
             "switched": switched, "at": int(time.time())}
    crm.store.set_meta("model_health", json.dumps(state, ensure_ascii=False))
    return state


def start(crm, cfg) -> None:
    import threading

    def loop():
        interval = max(600, int(getattr(cfg, "model_watch_interval", 1800)))
        while True:
            try:
                check(crm, cfg)
            except Exception:
                log.warning("model watch failed", exc_info=True)
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="modelwatch").start()
