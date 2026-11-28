# 0016 — Backups that are opened, and a watchdog that speaks

- **Status:** shipped
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v3.8.0
- **Roadmap:** R-25
- **Files:** `bridge/backup.py`, `bridge/watchdog.py`, `bridge/service.py`

## Why

Two silences were unacceptable on a phone-hosted system:

1. **No backup existed.** 40 published posts, their metrics and 3 media files lived in one
   file on one device. A lost phone was a lost archive, and nobody would notice until then.
2. **Failures were quiet.** WhatsApp can log the linked device out, publishes can fail, the
   disk can fill — and the owner sees a UI that simply looks empty.

## How

**Backup** (`bridge/backup.py`), daily at 03:00 local:

- SQLite's own `backup()` API to a temp file (safe while the bridge writes), media copied
  beside it, both archived to `var/backups/crm-YYYYmmdd-HHMM.tar.gz`.
- **Every archive is verified immediately**: extract to temp, `PRAGMA integrity_check`, count
  posts. A corrupt backup fails today, not on restore day.
- Rotation keeps 7 by **mtime** (a `-1` suffix sorts before the plain name — name-sorting
  deleted the newest).
- `restore()` refuses an archive that fails verification, removes stale `-wal`/`-shm`
  sidecars (a replayed WAL resurrects deleted rows), and is documented as an offline
  operation: stop the bridge first.
- Collisions inside one minute get a suffix, so two manual runs cannot overwrite each other.

**Watchdog** (`bridge/watchdog.py`), every 5 minutes:

| Probe | Alert |
|---|---|
| GOWA device not connected/logged in | «واتساب غير متصل» |
| GOWA unreachable | «بوابة واتساب لا تستجيب» |
| ≥3 failed publishes in 24 h | «فشل نشر متكرر» |
| free disk < 500 MB | «المساحة على وشك الانتهاء» |

Every alert is deduplicated per hour (`watchdog:<code>:<hour>`) so one broken dependency
produces one notification, not 288. Alerts land in the bell and in the push channels.

## Verify

```bash
python3 -m unittest bridge.tests.test_ops.BackupTest   # backup → verify → restore → rotation
python3 -m unittest bridge.tests.test_ops.WatchdogTest # logged-out raises once, healthy silent
# on the device: a real archive is created, verified, and listed by size
ls -lh ~/crm/var/backups
```

## Limits

- Backups live on the same phone: this protects against corruption and mistakes, not against
  losing the device. Off-device (R2) is still the missing half.
- The watchdog cannot restart a dead service; it reports. Runit does the restarting.
- Disk alert needs the bridge itself to be alive; a totally dead process is silent by nature.

## Links

- `docs/CLOUD-PLACEMENT.md` (R2 for off-device copies)
