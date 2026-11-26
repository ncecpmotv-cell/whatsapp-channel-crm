"""Seed a fresh CRM DB with realistic Arabic demo data (for browsing a preview).

Usage: python3 scripts/seed_demo.py /path/to/crm.db "1203630...@newsletter"
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge"))

from crm import CrmClient
from store import Store

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/phone-crm/var/preview.db")
JID = sys.argv[2] if len(sys.argv) > 2 else "120363000000000000@newsletter"

store = Store(DB)
crm = CrmClient(store)
now = int(time.time())

# --- contacts -------------------------------------------------------------
people = [
    ("+966501234567", "عبدالله الحربي", "مؤسسة أفق", "customer"),
    ("+966555987654", "نورة القحطاني", "كافيه صفّ", "qualified"),
    ("+966533445566", "ماجد العتيبي", "استوديو ليمو", "lead"),
    ("+966544778899", "ريم الشمري", "جمعية المهدية", "partner"),
]
ids = {}
for phone, name, org, stage in people:
    rec = crm.upsert_contact(phone, name=name, org=org, stage=stage)
    ids[phone] = rec["id"]
    crm.add_message(rec["id"], "in", "السلام عليكم، شفت القناة وأبغى أعرف الأسعار.", read=False)
    crm.add_message(rec["id"], "out", "وعليكم السلام، أرسل لك الباقات الآن.", read=True)

crm.add_message(ids["+966555987654"], "in", "هل فيه متابعة للتصوير الشهري؟", read=False)

# --- deals ---------------------------------------------------------------
deals = [
    ("+966501234567", "باقة محتوى سنوية", 18000, "negotiation", 2 * 86400),
    ("+966555987654", "تصوير منتجات شهري", 6500, "proposal", 1 * 86400),
    ("+966533445566", "فيديو تعريفي", 9000, "contacted", 4 * 86400),
]
for phone, title, value, stage, in_days in deals:
    deal = crm.upsert_deal(title, contact_id=ids[phone], value=value, stage=stage,
                           next_action_at=now + in_days)
    crm.add_activity(ids[phone], "call", f"متابعة عرض: {title}", due_at=now + in_days,
                     deal_id=deal["id"])

crm.add_activity(ids["+966544778899"], "note", "إرسال ملف التعريف للجمعية",
                 due_at=now - 3600)

# --- content pipeline ----------------------------------------------------
posts = [
    ("ثلاث نصائح لتصوير المنتجات بالجوال", "1) ضوء طبيعي من النافذة\n2) خلفية واحدة ثابتة\n3) لقطة واحدة لكل ميزة", "published", -3 * 86400, 1240, 38, 12),
    ("كواليس جلسة تصوير كافيه صفّ", "لقطات من الكواليس + الإعدادات كاملة في المنشور التالي.", "published", -2 * 86400, 870, 21, 9),
    ("عرض نوفمبر: باقة 4 منشورات", "باقة نوفمبر تشمل 4 منشورات + تصميم + جدولة. الأماكن محدودة.", "published", -1 * 86400, 430, 12, 5),
    ("إعلان: خدمة جديدة للقنوات", "قريبًا: إدارة قناة واتساب كاملة بدل من 8 منشورات شهريًا.", "scheduled", 6 * 3600, 0, 0, 0),
    ("سؤال للجمهور: أي نوع محتوى تفضّل؟", "شاركنا: تصوير منتجات، كواليس، أم نصائح سريعة؟", "review", 1 * 86400, 0, 0, 0),
    ("ملاحظات عن تصوير الكافيهات", "ثلاث ملاحظات تكررت في آخر خمس جلسات.", "draft", None, 0, 0, 0),
    ("فكرة: سلسلة أخطاء شائعة", "حلقة أسبوعية قصيرة عن خطأ واحد وتصحيحه.", "idea", None, 0, 0, 0),
]
for title, body, status, offset, views, forwards, reactions in posts:
    post = crm.create_channel_post({
        "channel_jid": JID, "title": title, "body": body,
        "status": "draft", "created_by": "human",
    })
    if status == "published":
        when = now + offset
        crm.update_channel_post(post["id"], {
            "status": "published", "published_at": when,
            "message_id": f"DEMO{post['id']}",
        })
        crm.update_counters(post["id"], views, forwards, reactions)
    elif status == "scheduled":
        crm.schedule_post(post["id"], now + offset, approved=True)
    elif status == "review":
        crm.schedule_post(post["id"], now + offset, approved=False)
    elif status == "draft":
        crm.update_channel_post(post["id"], {"status": "draft"})

print(f"seeded {DB}")
print("contacts:", crm.stats()["contacts"], "posts:", crm.stats()["posts"],
      "deals:", crm.stats()["deals"], "unread:", crm.stats()["unread"])
store.close()
