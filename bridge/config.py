"""Configuration for the phone CRM + GOWA bridge.

One .env file (`~/gowa-espo/.env` by default) so no credential is hard-coded.
Environment variables win over the file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

ENV_PATH = os.path.expanduser("~/gowa-espo/.env")

_TRUTHY = {"1", "true", "yes", "on"}


def parse_env_file(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    if not os.path.exists(path):
        return data
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


@dataclass(frozen=True)
class Config:
    gowa_base_url: str
    gowa_device_id: str
    gowa_webhook_secret: str
    bridge_host: str
    bridge_port: int
    bridge_token: str
    newsletter_jids: tuple[str, ...]
    default_country_code: str
    db_path: str
    poll_interval: int
    channel_sync_interval: int
    log_level: str
    agent_can_publish: bool
    daily_publish_cap: int
    gowa_user: str = ""
    gowa_password: str = ""

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        path = path or os.environ.get("BRIDGE_ENV_FILE", ENV_PATH)
        values = parse_env_file(path)
        values.update({k: v for k, v in os.environ.items() if k in _KNOWN_KEYS})

        def get(key: str, default: str = "") -> str:
            return values.get(key, default)

        def get_int(key: str, default: int) -> int:
            try:
                return int(values.get(key, "") or default)
            except ValueError:
                return default

        def get_bool(key: str, default: bool = False) -> bool:
            raw = values.get(key)
            if raw is None or raw == "":
                return default
            return raw.strip().lower() in _TRUTHY

        jids = tuple(
            j.strip()
            for j in get("NEWSLETTER_JIDS", "").replace(";", ",").split(",")
            if j.strip()
        )
        cfg = cls(
            gowa_base_url=get("GOWA_BASE_URL", "http://127.0.0.1:3000").rstrip("/"),
            gowa_device_id=get("GOWA_DEVICE_ID", "primary"),
            gowa_webhook_secret=get("GOWA_WEBHOOK_SECRET"),
            bridge_host=get("BRIDGE_HOST", "127.0.0.1"),
            bridge_port=get_int("BRIDGE_PORT", 8085),
            bridge_token=get("BRIDGE_TOKEN"),
            newsletter_jids=jids,
            default_country_code=get("DEFAULT_COUNTRY_CODE", "").lstrip("+"),
            db_path=os.path.expanduser(get("CRM_DB_PATH") or get("BRIDGE_DB_PATH")
                                       or "~/gowa-espo/var/crm.db"),
            poll_interval=get_int("BRIDGE_POLL_INTERVAL", 60),
            channel_sync_interval=get_int("BRIDGE_CHANNEL_SYNC_INTERVAL", 300),
            log_level=get("BRIDGE_LOG_LEVEL", "INFO").upper(),
            agent_can_publish=get_bool("AGENT_CAN_PUBLISH", False),
            daily_publish_cap=get_int("DAILY_PUBLISH_CAP", 30),
            gowa_user=get("GOWA_USER"),
            gowa_password=get("GOWA_PASSWORD"),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        problems = []
        if not self.gowa_webhook_secret:
            problems.append("GOWA_WEBHOOK_SECRET is empty (GOWA webhooks cannot be verified)")
        if not self.bridge_token:
            problems.append("BRIDGE_TOKEN is empty (the MCP/UI token cannot be authenticated)")
        if not self.gowa_base_url.startswith("http"):
            problems.append("GOWA_BASE_URL must start with http:// or https://")
        if problems:
            raise ValueError("; ".join(problems))


_KNOWN_KEYS = {
    "GOWA_BASE_URL", "GOWA_DEVICE_ID", "GOWA_WEBHOOK_SECRET", "BRIDGE_HOST", "BRIDGE_PORT",
    "BRIDGE_TOKEN", "NEWSLETTER_JIDS", "DEFAULT_COUNTRY_CODE", "CRM_DB_PATH",
    "BRIDGE_POLL_INTERVAL", "BRIDGE_CHANNEL_SYNC_INTERVAL", "BRIDGE_LOG_LEVEL",
    "AGENT_CAN_PUBLISH", "DAILY_PUBLISH_CAP", "GOWA_USER", "GOWA_PASSWORD",
}
