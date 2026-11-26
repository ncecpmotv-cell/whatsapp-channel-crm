"""Remove demo/seed rows so the CRM reflects the real channel only."""
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "/var/crm/preview.db"
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

demo_phones = ("+966501234567", "+966555987654", "+966533445566", "+966544778899")

demo_posts = c.execute(
    "SELECT id, title FROM crm_posts WHERE message_id LIKE 'DEMO%' "
    "OR (status <> 'published' AND title IN ('اختبار حذف','اختبار صورة','رابط'))"
).fetchall()
for row in demo_posts:
    c.execute("DELETE FROM crm_stats WHERE post_id = ?", (row["id"],))
    c.execute("DELETE FROM outbox WHERE ref = ?", (row["id"],))
    c.execute("DELETE FROM crm_posts WHERE id = ?", (row["id"],))
print("demo posts removed:", len(demo_posts))

for phone in demo_phones:
    contact = c.execute("SELECT id FROM crm_contacts WHERE phone = ?", (phone,)).fetchone()
    if not contact:
        continue
    cid = contact["id"]
    c.execute("DELETE FROM crm_activities WHERE contact_id = ?", (cid,))
    c.execute("DELETE FROM crm_messages WHERE contact_id = ?", (cid,))
    c.execute("DELETE FROM crm_deals WHERE contact_id = ?", (cid,))
    c.execute("DELETE FROM crm_contacts WHERE id = ?", (cid,))
print("demo contacts removed:", len(demo_phones))

c.execute("DELETE FROM crm_notifications")
c.execute("DELETE FROM outbox WHERE status = 'failed'")
c.commit()

print("posts:", c.execute("SELECT COUNT(*) FROM crm_posts").fetchone()[0],
      "| published:", c.execute("SELECT COUNT(*) FROM crm_posts WHERE status='published'").fetchone()[0],
      "| contacts:", c.execute("SELECT COUNT(*) FROM crm_contacts").fetchone()[0],
      "| deals:", c.execute("SELECT COUNT(*) FROM crm_deals").fetchone()[0])
