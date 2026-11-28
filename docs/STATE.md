# حالة المشروع — نقطة البداية لأي جلسة جديدة

> اقرأ هذا الملف أولًا، ثم مهارة `whatsapp-channel-crm` (فيها الدروس والمصائد).
> آخر تحديث: 2026-11-27 · آخر دفعة: `1ab363b` وما بعدها.

## ما هو المشروع

CRM خفيف لقناة واتساب: مسودة → معتمد ومجدول → منشور · ملغى، مع واجهة عربية RTL،
و16 أداة MCP لوكيل ذكي (PicoClaw)، وإشعارات جرح + دفع، ويعمل **بالكامل على الجوال**.

## أين يعمل (المصدر الوحيد للحقيقة)

| المكوّن | المكان | العنوان |
|---|---|---|
| الجهاز | HUAWEI **POT-LX1AF** (P Smart 2019) · Termux · aarch64 · 2.7GB | — |
| GOWA (واتساب) | وحدة runit `gowa` · بروتوكول proot · v9.10.0 | `127.0.0.1:3000` |
| CRM + MCP + UI | وحدة runit `crm` · Python 3.14 · stdlib | `127.0.0.1:8085` |
| PicoClaw | وحدة runit `picoclaw` · v0.3.1 (arm64) | `127.0.0.1:18790` |
| tailscaled | وحدة runit `tailscaled` · userspace · **`--statedir` إلزامي** | `~/gowa-espo/var/tailscaled.sock` |
| SSH صيانة | نفق عكسي من الجوال إلى السيرفر | `ssh smartp` (127.0.0.1:2225) |

**الوصول للمستخدم:** https://smartp.tail16a0c8.ts.net — Basic auth `crm` + `BRIDGE_TOKEN`
(في `~/crm/crm.env`).

## المسارات

```
~/crm/                 الكود + DB + media   (bridge/, scripts/, config/)
~/crm/crm.env          أسرار الواجهة (600)  BRIDGE_TOKEN · GOWA_* · PUBLIC_BASE_URL
~/crm/var/crm.db       SQLite (42 منشورًا، 40 منشورًا على القناة + مسودتان)
~/crm/var/media/       وسائط الرفع
~/gowa-espo/           GOWA: bin/whatsapp · storages/ · .env
~/gowa-espo/bin/       whatsapp · tailscale · tailscaled
~/pico/                PicoClaw home: config.json · .security.yml · skills/
~/start.sh             إقلاع مرتّب: infra → gowa → crm → picoclaw + الحالة
~/.termux/boot/00-server.sh   يستدعي ~/start.sh فقط
~/doctor.sh            نسخة من scripts/doctor.sh للفحص السريع
edge/ (في الريبو)      Worker بلا حالة: edge_web_extract · edge_search · edge_status
```

## الحالة المُتحقَّق منها

- الوحدات: `gowa · crm · picoclaw · sshd · rtunnel · tailscaled · crond` تعمل.
- `/health`: `{"ok":true,"crm":true,"origin_guard":{"public_url":true,"tailnet":true},"push":{"enabled":true}}`
- **الخطط**: `crm_plans` + `crm_plan_items` · `crm_save_plan` / `crm_get_plan` /
  `crm_approve_plan` · صفحة `/ui/plan` · تقرير أسبوعي تلقائي الأحد 20:00 (thread داخل الجسر).
- **العمليات**: نسخ احتياطي يومي 03:00 (مُتحقَّق) · حارس كل 5 دقائق · موجز 09:00 ·
  خطة أسبوعية استباقية (cron `0 10 * * 4`) · `/ui/search` · `/ui/media` · A/B.
- MCP: **27 أداة محلية** (إرفاق وسائط · فحص ما قبل النشر · أفضل وقت) · `content_gaps` (فجوات الموضوعات) و`semantic_search` (BM25 + تجذيع عربي).
- **edge-mcp** منشور على Cloudflare: `https://edge-mcp.fixed-friend.workers.dev` — 3 أدوات
  (extract/search/status)، مسجّل في PicoClaw كخادم MCP ثانٍ. مُتحقَّق من الجوال عبر الوكيل:
  استخراج example.com (172 حرفًا) + `content_gaps` في نفس الدور.
- **بحث ويب أصلي في PicoClaw**: `tools.web.tavily` مفعّل بمفتاح Tavily (1000 استعلام/شهر)،
  والمزوّد `tavily` بدل `sogou`. مُتحقَّق عبر الوكيل: 3 نتائج حقيقية بروابط في ~25 ثانية.
- PicoClaw: مهارة `content-strategist` مثبّتة، وMCP `crm` مسجّل.
- الاقتران: `is_logged_in:true` للرقم `966502369637` — بلا QR بعد نقل `storages/`.
- `doctor.sh`: **22 فحصًا ناجحًا · 0 فشل**.
- الاختبارات: `python3 -m unittest discover -s bridge/tests` → 40 اختبارًا.
- CI على GitHub: أخضر.

## الريبو

https://github.com/ncecpmotv-cell/whatsapp-channel-crm — **عام**، فرع `main`.
لا أسرار متعقّبة (فُحصت القيم والأنماط). الـ`var/` و`etc/` مستثناة.

## قرارات لا تُنقض بلا سبب

1. **الجوال هو المصدر الوحيد**؛ السيرفر احتياطي متوقف (`~/crm-node` بـvolumes محفوظة).
2. **حالة واحدة = زر ذهبي واحد**؛ لا مراحل فكرية/مراجعة.
3. **منشور `published` غير قابل للتعديل أو الحذف**؛ الإلغاء قبل النشر.
4. **الحذف مسموح للمسودة والملغى فقط**؛ المجدول يُلغى أولًا.
5. **كل حدث يكتب في الجرس من طبقة البيانات** (`CrmClient.notify`) — لا من معالجات HTTP.
6. **التوثيق عقد**: صفحة لكل ميزة + فهرس + roadmap + `check_docs.py` في CI.
7. **الأسرار لا تُكتب في توثيق أو أمثلة**؛ الأمثلة `<BRIDGE_TOKEN>`.

## مصائد وقعنا فيها (لا تعِدها)

- `Origin: null` من متصفح تليجرام الداخلي → عاملها كغياب ترويسة، وCSRF يحسم.
- `tailscale serve` يحتاج `--statedir` وإلا `no TailscaleVarRoot`.
- قيم `crm.env` تُقرأ عبر `Config`، **لا** `os.environ` (مفاتيح الملف غير مُصدَّرة).
- منفذ MCP داخل الحاوية كان 8086؛ على الجوال 8085 — سطر واحد يُعطّل كل الأدوات بصمت.
- PicoClaw يحمل مسار `/data/workspace` من الحاوية؛ على Termux يجب استبداله.
- وحدة runit بلا `$HOME` تفشل فورًا (`down: 0s`) — اكتب المسارات المطلقة.
- `down` marker قديم يُبقي وحدة ميتة بعد الإقلاع رغم `sv up`.
- `pkill -f "picoclaw"` يقتل جلسة SSH نفسها؛ استخدم PID من `pgrep` أو أنماط مبنية.
- النفق `rtunnel` يسقط أحيانًا (خصوصًا بعد إعادة تشغيل) → `sv up rtunnel`.

## مفتوح الآن

- **تكرار أدوات**: PicoClaw يملك الآن `web_search` أصليًا + `web_fetch`، فـ`edge_search`
  و`edge_web_extract` صارا احتياطًا. القيمة المتبقية للـWorker: Google OAuth مستقبلًا.
  قرار: نُبقيه أو نُلغي تسجيله لتوفير سياق — يُحسم عند إضافة أدوات Google.
- **إشعارات تليجرام**: بانتظار `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (Termux:API يعمل).
- **طبقة سحابية اختيارية**: القرار موثّق في `docs/CLOUD-PLACEMENT.md` (Cloudflare للبحث/Google/الصوت، Convex مؤجل).
- **فجوة تحليلية**: 40 منشورًا فقط — إشارات التوقيت ضعيفة؛ قلها صراحة في أي خطة.

## قاعدة التكلفة (ملزمة لكل ميزة قادمة)

لا طبقة مدفوعة. كل ميزة سحابية تُشحن بسقف صارم يرفض الطلب (`413`/`429`/`507`) وعدّاد و`/usage`.
السقوف الحالية: 3 نسخ · 8MB للنسخة · 64MB للمجموع · 40 استدعاء ذكاء يوميًا.
التفاصيل والأسعار وقواعد التصميم: [`COST-GUARDRAILS.md`](COST-GUARDRAILS.md) · الميزة `0021`.

## الرادار واللوحة (v4.1.0)

- **الرادار:** الحافة تجلب 3–10 مصادر RSS كل 30 دقيقة (كرون، بلا نموذج)؛ الجوال يقيس الجِدّة مقابل
  الأرشيف ويخزّن الزوايا في `crm_angles`. الأدوات: `crm_radar_scan` · `crm_angles` ·
  `crm_angle_use` (مسودة فقط) · `crm_angle_dismiss`.
- **اللوحة:** `/ui` = «لوحة القيادة» وفيها: متوسط المشاهدات · التفاعل · الإيقاع · نمو المشتركين ·
  أفضل الأوقات · فجوات المحتوى · الزوايا · الإخفاقات · المسودات · آخر نسخة · آخر نبضة.
- **القياس الحي:** 36 أداة · مسح 40 عنوانًا → 12 زاوية (أعلى جِدّة 0.988) · استدعاء ذكاء واحد
  للمسح اليدوي فقط · المسح الخلفي كل ساعتين بلا استدعاء.

## الحافة (edge-mcp)

- **الرابط الحي:** `https://edge-mcp.ncecpmo.workers.dev` (الإصدار 0.2.0، حساب `0476abbe…`).
- **يعمل الآن:** `/health` · `/heartbeat` · `/status` · `/ai/transcribe` · `/ai/caption`.
- **مُتحقَّق من الجوال عبر MCP:** تحويل صوت mp3 في 2.9 ثانية · وصف صورة في 3.9 ثانية
  (`{description, hashtags}`) · `crm_edge_status` يعيد `version 0.2.0` و`status 200` ·
  `/status` تعرض «يعمل · قبل 0 دقيقة».
- **معلّق:** `/backup` — إنشاء حاوية R2 يعيد `10042 Please enable R2 through the Cloudflare Dashboard`؛
  الربط معلّق في `wrangler.toml` حتى تُفعَّل R2 من اللوحة، ثم يُزال التعليق ويُنشر.
- **الأسرار:** `EDGE_TOKEN` و`BACKUP_KEY` مضبوطان على الـWorker (المفتاح في `~/.cf.env` على السيرفر، 0600).
- **مصيدة المسارات:** الخدمة تقرأ `~/gowa-espo/.env` لا `~/crm/crm.env`؛ استخدم `scripts/phone-edge-env.sh`.
- **مصيدة الاتصال:** `urllib` بلا User-Agent يأخذ 403 `1010` من Cloudflare.

## الخطوات الثلاث القادمة

| # | الخطوة | القبول |
|---|---|---|
| 1 | ~~`edge-mcp` Worker~~ ✅ الكود جاهز (`edge/`) | يتبقى `wrangler deploy` بحسابك ثم `picoclaw mcp add edge` |
| 2 | Google: `gsheet_append` + `gcal_event` (التوكن في أسرار الـWorker) | خطة أسبوع في شيت + أحداث تقويم |
| 3 | SubTurn: محلّل → استراتيجي → محرّر + `/plan` | خطة + مسودات، والسياق < 8k توكن |

## كيف تبدأ جلسة جديدة

```bash
cd ~/phone-crm && git pull
ssh smartp 'sh ~/start.sh status'     # أو: bash ~/doctor.sh
bash scripts/doctor.sh                 # من الريبو
```

ثم اقرأ: `docs/STATE.md` (هذا الملف) → `skill_view whatsapp-channel-crm` →
`docs/CLOUD-PLACEMENT.md` → `ROADMAP.md`.
