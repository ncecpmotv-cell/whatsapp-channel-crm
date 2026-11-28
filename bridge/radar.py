"""Phone half of the radar: score headlines against the archive, store angles, summarise on demand.

The edge fetches feeds on a cron and stores a batch; this module decides what is *new to this
channel*, which the edge cannot know. Summaries cost one model call, so they happen only when the
owner asks for angles — a background scan stores headlines alone.
"""
from __future__ import annotations

import email.utils
import logging
import time

from crm import _tokens

log = logging.getLogger("bridge.radar")

MAX_ITEMS = 12
SUMMARY_TOP = 5


def novelty(tokens: set[str], archive: list[set[str]]) -> float:
    """1.0 = nothing like it in the archive; 0.0 = a near-duplicate of an existing post."""
    if not tokens or not archive:
        return 1.0
    best = 0.0
    for other in archive:
        union = tokens | other
        if not union:
            continue
        best = max(best, len(tokens & other) / len(union))
    return round(1.0 - best, 3)


def recency(published: str, now: float | None = None) -> float:
    """1.0 for something published now, 0.0 after three days."""
    if not published:
        return 0.5
    try:
        stamp = email.utils.parsedate_to_datetime(published).timestamp()
    except (TypeError, ValueError):
        return 0.5
    age_hours = max(0.0, ((now or time.time()) - stamp) / 3600)
    return round(max(0.0, 1.0 - age_hours / 72), 3)


def archive_tokens(crm, limit: int = 150) -> list[set[str]]:
    rows = crm._all(
        "SELECT title, body FROM crm_posts ORDER BY COALESCE(published_at, created_at) DESC LIMIT ?",
        (limit,))
    return [set(_tokens(f"{row['title'] or ''} {row['body'] or ''}")) for row in rows]


def scan(crm, cfg, limit: int = MAX_ITEMS, summarize: bool = False, notify: bool = True) -> dict:
    from edge import from_config

    client = from_config(cfg)
    if not client.enabled():
        return {"ok": False, "error": "edge is not configured"}

    batch = client.radar()
    items = batch.get("items") or []
    if not items:
        return {"ok": False, "error": "radar batch is empty", "fetched_at": batch.get("fetchedAt")}

    archive = archive_tokens(crm)
    scored = []
    for item in items:
        tokens = set(_tokens(item.get("title") or ""))
        if not tokens:
            continue
        fresh = novelty(tokens, archive)
        score = round(0.7 * fresh + 0.3 * recency(item.get("published") or ""), 3)
        scored.append({**item, "novelty": fresh, "score": score})
    scored.sort(key=lambda row: -row["score"])
    top = scored[:limit]

    angles = {}
    summarized = False
    if summarize and top:
        result = client.radar_summarize([row["title"] for row in top[:SUMMARY_TOP]])
        for entry in result.get("angles") or []:
            try:
                angles[int(entry.get("i"))] = str(entry.get("angle") or "").strip()
            except (TypeError, ValueError):
                continue
        summarized = bool(angles)

    stored = 0
    for index, row in enumerate(top):
        row["angle"] = angles.get(index, "")
        if crm.add_angle(row):
            stored += 1

    if notify and stored >= 3:
        crm.notify("radar", "زوايا جديدة", f"{stored} زاوية من الرادار", "/ui/radar")

    return {"ok": True, "scanned": len(scored), "stored": stored, "summarized": summarized,
            "fetched_at": batch.get("fetchedAt"), "top": top[:5]}
