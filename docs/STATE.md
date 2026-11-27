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
```

## الحالة المُتحقَّق منها

- الوحدات: `gowa · crm · picoclaw · sshd · rtunnel · tailscaled · crond` تعمل.
- `/health`: `{"ok":true,"crm":true,"origin_guard":{"public_url":true,"tailnet":true},"push":{"enabled":true}}`
- MCP: **16 أداة** · `content_insights` يعيد بيانات حقيقية (فيديو: 16 مشاهدة).
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

- **إشعارات تليجرام**: بانتظار `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (Termux:API يعمل).
- **طبقة سحابية اختيارية**: القرار موثّق في `docs/CLOUD-PLACEMENT.md` (Cloudflare للبحث/Google/الصوت، Convex مؤجل).
- **فجوة تحليلية**: 40 منشورًا فقط — إشارات التوقيت ضعيفة؛ قلها صراحة في أي خطة.

## الخطوات الثلاث القادمة

| # | الخطوة | القبول |
|---|---|---|
| 1 | `edge-mcp` Worker: `edge_web_extract` + `edge_search` + `edge_status` | «لخّص هذه الصفحة» تعمل من تليجرام، والرام بلا تغيير |
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
