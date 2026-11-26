"""Publish one post of every content type to the TEST channel and report results.

Runs inside the CRM node:  python3 /var/crm/publish_all_types.py <channel-jid>
"""
import json
import os
import sys
import time

sys.path.insert(0, "/app/bridge")
from crm import CrmClient  # noqa: E402
from store import Store  # noqa: E402

DB = "/var/crm/preview.db"
JID = sys.argv[1] if len(sys.argv) > 1 else "120363409750144525@newsletter"
MEDIA = "/var/crm/media"

store = Store(DB)
crm = CrmClient(store)

specs = [
    ("text", {"title": "اختبار: نص",
              "body": "اختبار آلي لمنشور نصي من CRM — يمكن تجاهله.",
              "media_type": "text"}),
    ("image", {"title": "اختبار: صورة",
               "body": "اختبار صورة عبر CRM.",
               "media_type": "image", "media_path": f"{MEDIA}/test-image.png"}),
    ("video", {"title": "اختبار: فيديو",
               "body": "اختبار فيديو عبر CRM.",
               "media_type": "video", "media_path": f"{MEDIA}/test-video.mp4"}),
    ("audio", {"title": "اختبار: صوت",
               "body": "اختبار صوت عبر CRM.",
               "media_type": "audio", "media_path": f"{MEDIA}/test-audio.mp3"}),
    ("poll", {"title": "اختبار: استبيان — أي نوع محتوى تفضّل؟",
              "body": "",
              "media_type": "poll",
              "meta": json.dumps({
                  "options": ["نص", "صورة", "فيديو", "صوت"],
                  "max_answer": 1,
              }, ensure_ascii=False)}),
]

created = []
for kind, fields in specs:
    post = crm.create_channel_post({"channel_jid": JID, "created_by": "human", **fields})
    crm.schedule_post(post["id"], int(time.time()), approved=True)
    created.append((kind, post["id"]))
    print(f"queued {kind}: {post['id']}")

deadline = time.time() + 180
while time.time() < deadline:
    pending = [pid for _, pid in created
               if (crm.get_channel_post(pid) or {}).get("status") not in ("published", "failed")]
    if not pending:
        break
    time.sleep(3)

print("\nkind\tstatus\tmessage_id\tserver_id\terror")
failed = 0
for kind, pid in created:
    row = crm.get_channel_post(pid) or {}
    if row.get("status") != "published":
        failed += 1
    print(f"{kind}\t{row.get('status')}\t{row.get('message_id')}\t{row.get('server_id')}\t{(row.get('last_error') or '')[:80]}")
print(f"\n{len(created) - failed}/{len(created)} published")
store.close()
sys.exit(1 if failed else 0)
