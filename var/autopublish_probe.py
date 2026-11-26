"""Auto-publish probe: retry a failed text post and add a due-in-40s scheduled post."""
import sqlite3
import time
import uuid

DB = "/var/crm/preview.db"
JID = "120363409750144525@newsletter"
c = sqlite3.connect(DB)
now = int(time.time())

retry = c.execute(
    "select id, title from crm_posts where status='failed' and media_type='text' order by updated_at desc limit 1"
).fetchone()
if retry:
    c.execute("update crm_posts set status='scheduled', scheduled_at=?, last_error=NULL where id=?",
              (now + 5, retry[0]))
    print("retry:", retry[0], retry[1][:40])

pid = uuid.uuid4().hex[:12]
c.execute(
    "insert into crm_posts (id, channel_jid, title, body, status, scheduled_at, media_type, "
    "created_by, created_at, updated_at) values (?,?,?,?,?,?,?,?,?,?)",
    (pid, JID, "اختبار الجدولة التلقائية", "منشور مجدول اختباري — يجب أن يُنشر تلقائيًا.",
     "scheduled", now + 40, "text", "human", now, now))
c.commit()
print("new scheduled:", pid, "due in 40s")
