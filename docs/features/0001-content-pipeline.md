# 0001 — Content pipeline with human approval

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v2.0.0
- **Roadmap:** R-01
- **Files:** `bridge/crm.py`, `bridge/service.py`, `bridge/ui.py`, `bridge/app.py`

## Why

A channel owner publishes from a phone between other work. Ideas, drafts and approved
posts used to live in notes and chats, so posts were lost, duplicated, or published
without review. The pipeline gives every piece of content exactly one state and one
owner at a time, and makes "who may publish" a rule instead of a habit.

## How

`crm_posts.status` moves `draft → scheduled → publishing → published`, with `failed`
acting as the cancelled bucket (kept in the archive, purge only from there).

- A human schedules from the UI (`/ui/content/schedule` or the edit form, where a date
  also reschedules). The agent can only create drafts and propose times.
- The worker claims due posts (`claim_post`, an atomic `UPDATE … WHERE status IN
  ('scheduled','publishing')`), sends through GOWA, stores `message_id`, marks
  `published`, and records per-post counters.
- Failures go to the outbox with backoff (30 s → 6 h, 5 attempts). A permanent failure
  (a poll on a channel, `479`) is recorded with the GOWA message and is not retried.
- Published posts are immutable in the UI; cancelling keeps the record so the archive
  still explains what happened.

The non-obvious decision: **the outbox lives in SQLite, not in memory.** Android kills
background processes; a queue that only exists in RAM loses the post with the process.

## Verify

```bash
python3 -m unittest discover -s bridge/tests -v      # 15 tests, lifecycle covered
python3 scripts/e2e_local.py                          # 21 checks: draft → approve → outbox → published
```

Live check on the phone: a scheduled post moved to `published` at its time without
intervention, and `message_id` was stored.

## Deleting

`crm.delete_post` allows `draft` and `failed` (cancelled). A `scheduled` or `publishing`
post must be cancelled first — it is in the queue and may be mid-flight. `published` is
immutable: the channel keeps its own copy, so deleting the row would lie about the record.

## Limits

- One channel per deployment is the tested path; the schema is per-`channel_jid` but the
  UI reads the first configured channel.
- No scheduling conflict detection (two posts at the same minute are allowed).
- No draft versioning: edits overwrite, the archive keeps only the published text.

## Links

- `docs/ARCHITECTURE.md#flows`
- `docs/API-MCP.md#ui-routes`
- CHANGELOG: "Content pipeline with four states…"
