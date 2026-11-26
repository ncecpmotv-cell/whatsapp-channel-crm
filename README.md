# CRM الجوال — PicoClaw + CRM + GOWA في منظومة واحدة

نظام واحد خفيف يعمل داخل Termux على الجوال: يقرأ واتساب (GOWA)، ينظّم محتوى
القناة، يدير العملاء والصفقات، ويُعرّض كل ذلك لوكيل الذكاء **PicoClaw** عبر MCP —
بلا EspoCRM، بلا MariaDB، بلا PHP، بلا Node.

```
PicoClaw ──MCP :8085/mcp──┐
                          ├── CRM (Python stdlib + SQLite) ── crm.db
GOWA :3000 ──webhook──────┘        └── واجهة ويب عربية :8085/ui
```

- **عملية واحدة، منفذ واحد (8085)، ملف SQLite واحد** (`~/gowa-espo/var/crm.db`).
- إعداد PicoClaw **لا يتغير**: نفس العنوان `http://127.0.0.1:8085/mcp` ونفس أسماء الأدوات `mcp_crm_*`.

## المحتوى

الحالات: `idea → draft → review → scheduled → publishing → published | failed`.

- الوكيل ينشئ مسودات ويقترح وقتًا (`content_schedule`) → تصبح `review`.
- **النشر قرار بشري** من الواجهة (زر «جدولة» أو «نشر الآن») — إلا إذا فعّلت
  `AGENT_CAN_PUBLISH=1` صراحةً.
- كل نشر يمر عبر outbox مع إعادة محاولة 30/60/90… ثانية (حتى 5 محاولات)،
  وفشل دائم يظهر في الواجهة (`last_error`).
- أرشيف القناة يُسحب تلقائيًا عند الإقلاع وكل `BRIDGE_CHANNEL_SYNC_INTERVAL`،
  والقياسات (مشاهدات/تمرير/تفاعل) تُحدَّث من `message-updates`.

## الواجهة

`http://127.0.0.1:8085/ui` — مصادقة Basic: اسم أي شيء، كلمة المرور = `BRIDGE_TOKEN`.

شاشات: اليوم · المحتوى · العملاء · الفرص · القياسات. PWA عبر `/ui/manifest.webmanifest`.

## التركيب على الجوال

```bash
# في Termux، داخل نسخة المستودع
bash scripts/upgrade-to-crm.sh                 # يحوّل الجسر إلى CRM محلي
bash scripts/upgrade-to-crm.sh --retire-espocrm # ويوقف EspoCRM/MariaDB/nginx
```

السكربت: نسخة احتياطية → نسخ `bridge/*.py` → ترحيل `.env` → إعادة تشغيل → فحص صحة.
للتجربة بدون تشغيل: `--no-start`.

## التطوير والاختبار

```bash
cd bridge && python3 -m unittest discover -s tests -v     # 14 اختبارًا
cd .. && python3 scripts/e2e_local.py                      # 19 فحصًا عبر HTTP حقيقي
```

`e2e_local.py` يشغّل GOWA وهميًا + الجسر الحقيقي ويتحقق من: توقيع webhook، إنشاء
جهة اتصال من رسالة، عرض الواجهة ومصادقتها، مسودة → اقتراح وقت → موافقة بشرية →
نشر عبر الطابور، أرشفة القناة، وتحديث القياسات.

## MCP tools

`crm_search` · `crm_get` · `crm_create_channel_post` · `crm_update_channel_post` ·
`content_schedule` · `crm_list_ready_posts` · `channel_metrics` · `contact_upsert` ·
`deal_update` · `followups_due` · `wa_send` · `wa_channel_messages` · `bridge_health`

## ملفات

- `bridge/crm.py` — نموذج البيانات (SQLite) وسير المحتوى.
- `bridge/service.py` — الوارد من واتساب، الطابور، النشر، القياسات.
- `bridge/mcp.py` — واجهة الوكيل + سياسة الموافقة.
- `bridge/ui.py` + `bridge/app.py` — واجهة عربية وخادم HTTP واحد.
- `scripts/upgrade-to-crm.sh` — النشر على الجوال.
- `docs/LEGACY-espocrm-bridge.md` — توثيق النسخة القديمة (EspoCRM) للرجوع.
