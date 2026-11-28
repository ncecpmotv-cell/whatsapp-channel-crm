"""Rotating backups with a restore drill — a backup that was never opened is a rumour.

Daily: sqlite backup API → temp dir (plus media) → tar.gz in `var/backups/` → keep N.
Every run verifies the archive by extracting it to a temp dir and counting rows, so a
corrupt file fails today, not on the day you need it.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time

log = logging.getLogger("bridge.backup")


def _stamp(now: float | None = None) -> str:
    return time.strftime("%Y%m%d-%H%M", time.localtime(now or time.time()))


def make_backup(db_path: str, media_dir: str, dest_dir: str, keep: int = 7,
                now: float | None = None) -> dict:
    db_path = os.path.expanduser(db_path)
    media_dir = os.path.expanduser(media_dir)
    dest_dir = os.path.expanduser(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="crm-backup-")
    try:
        staged_db = os.path.join(work, "crm.db")
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(staged_db)
        with target:
            source.backup(target)          # safe while the bridge is writing
        source.close()
        target.close()
        if os.path.isdir(media_dir):
            shutil.copytree(media_dir, os.path.join(work, "media"), dirs_exist_ok=True)
        base = os.path.join(dest_dir, f"crm-{_stamp(now)}")
        archive, suffix = base + ".tar.gz", 1
        while os.path.exists(archive):  # two backups inside the same minute must not collide
            archive = f"{base}-{suffix}.tar.gz"
            suffix += 1
        with tarfile.open(archive, "w:gz") as tar:
            for name in os.listdir(work):
                tar.add(os.path.join(work, name), arcname=name)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    verification = verify_backup(archive)
    removed = prune(dest_dir, keep)
    return {"archive": archive, "bytes": os.path.getsize(archive),
            "verified": verification["ok"], "posts": verification.get("posts"),
            "removed": removed}


def verify_backup(archive: str) -> dict:
    """Open the archive and the database inside it; count the posts."""
    work = tempfile.mkdtemp(prefix="crm-verify-")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(work, filter="data")
        db = os.path.join(work, "crm.db")
        if not os.path.exists(db):
            return {"ok": False, "error": "archive has no crm.db"}
        conn = sqlite3.connect(db)
        posts = conn.execute("SELECT COUNT(*) FROM crm_posts").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        return {"ok": integrity == "ok", "posts": posts, "integrity": integrity}
    except Exception as exc:  # noqa: BLE001 - any failure means the archive is not usable
        return {"ok": False, "error": str(exc)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def prune(dest_dir: str, keep: int) -> list[str]:
    # by mtime, not by name: a suffix can sort before the plain name
    archives = sorted(glob.glob(os.path.join(dest_dir, "crm-*.tar.gz")),
                      key=os.path.getmtime)
    removed = []
    while len(archives) > max(1, keep):
        victim = archives.pop(0)
        try:
            os.remove(victim)
            removed.append(os.path.basename(victim))
        except OSError:
            pass
    return removed


def restore(archive: str, db_path: str, media_dir: str) -> dict:
    """Replace the live database and media with the archive's contents."""
    check = verify_backup(archive)
    if not check["ok"]:
        raise ValueError(f"archive failed verification: {check.get('error')}")
    db_path = os.path.expanduser(db_path)
    media_dir = os.path.expanduser(media_dir)
    work = tempfile.mkdtemp(prefix="crm-restore-")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(work, filter="data")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # a leftover WAL would be replayed over the restored file and resurrect old rows
        for sidecar in (db_path + "-wal", db_path + "-shm"):
            if os.path.exists(sidecar):
                os.remove(sidecar)
        shutil.copyfile(os.path.join(work, "crm.db"), db_path)
        restored_media = os.path.join(work, "media")
        if os.path.isdir(restored_media):
            os.makedirs(media_dir, exist_ok=True)
            shutil.copytree(restored_media, media_dir, dirs_exist_ok=True)
        log.info("restored %s (%s posts)", archive, check.get("posts"))
        return {"restored": True, "posts": check.get("posts"), "db": db_path}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def maybe_backup(crm, cfg, now: float | None = None) -> bool:
    """Called by the service loop: once a day at BACKUP_HOUR, verified, rotating."""
    now = time.time() if now is None else now
    hour = int(getattr(cfg, "backup_hour", 3))
    local = time.gmtime(now + int(getattr(cfg, "tz_offset", 3)) * 3600)
    last_raw = crm.store.get_meta("last_backup_at")
    last = float(last_raw) if last_raw else 0.0
    if local.tm_hour != hour or (now - last) < 20 * 3600:
        return False
    dest = os.path.expanduser(getattr(cfg, "backup_dir", "") or "~/crm/var/backups")
    result = make_backup(cfg.db_path, getattr(cfg, "media_dir", ""), dest,
                         keep=int(getattr(cfg, "backup_keep", 7)), now=now)
    crm.store.set_meta("last_backup_at", str(int(now)))
    crm.notify("digest", "نسخة احتياطية",
               f"{os.path.basename(result['archive'])} · {result['posts']} منشورًا"
               + ("" if result["verified"] else " · فشل التحقق"),
               "/ui")
    log.info("backup %s verified=%s posts=%s removed=%s", result["archive"],
             result["verified"], result["posts"], result["removed"])
    return True
