# FreeRide — ما هو، وما قِسته، وكيف يُوظَّف هنا

> فُحص في 2026-11-28. لا شيء من هذا تخمين: رُكِّب على السيرفر، وشُغِّل، وقِيس.

## ما هو

عائلتان باسم واحد:

- **FreeRide v1** (`Shaivpidadi/FreeRide`) — إضافة لـOpenClaw تعيد كتابة إعداداته لتستخدم نماذج
  OpenRouter المجانية مع بدائل مرتّبة. لا تصلح لـPicoClaw كما هي.
- **FreeRideV3** (`Shaivpidadi/FreeRideV3`) — **بوابة محلية متوافقة مع OpenAI** على
  `127.0.0.1:11343` توزّع الطلب على طبقات مجانية: OpenRouter · GEMINI · Ollama Cloud · Groq ·
  NVIDIA NIM · Cloudflare Workers AI · z.ai · xKiro · Ollama المحلي، مع **فشل تلقائي داخل نفس
  الطلب** ودوران عند نفاد الحصة.

## القياس على السيرفر

```
pip install freeride-gateway   # Python 3.14، بلا مشاكل
freeride serve --port 11343
GET /v1/models                 → 200 (نموذج ernie:free بأدوات)
POST /v1/chat/completions بأداة → tool_calls: ['crm_inbox'] · 1.6s · 204 tokens
RSS                             → 69 MB
```

التليمتري مفعّل افتراضيًا: `freeride telemetry off` قبل أي استخدام.

## لماذا لم يُثبَّت على الجوال

`pip` نفسه معطوب على هذا Termux:

```
ImportError: dlopen failed: cannot locate symbol "XML_GetCurrentLineNumber64"
  referenced by pyexpat.cpython-314-aarch64-linux-android.so
```

السبب: `libexpat` في النظام أقدم من متطلبات Python 3.14. الإصلاح = ترقية حزم النظام، ومحاكاة
`pkg upgrade libexpat` تسحب معها Rust 1.100 وحزمًا أخرى — أي **ترقية نظام كاملة على جهاز إنتاج**.
مخاطرة لا تُقابلها فائدة، خصوصًا أن القيمة المطلوبة (فشل تلقائي) نُفِّذت محليًا بلا حزمة.

## ما نُفِّذ بدلًا منه (v4.18.0)

`bridge/modelwatch.py` — فشل تلقائي بلا اعتماديات:

- كل ٣٠ دقيقة يفحص `GET {api_base}/models` للنموذج الأساسي — **صفر توكنات**.
- فشل (شبكة/429/5xx) → `picoclaw model fallback` + إشعار في تيليجرام والجرس.
- عودة → `picoclaw model default` تلقائيًا مع إشعار.
- الحالة تُحفظ في `meta.model_health` وتظهر في `/ui/capabilities` والشاشة تعرض النشط والسبب.
- اختبارات: ٥ (تحليل المفاتيح، فحص سريع، تحويل عند الفشل، عدم التحويل عند السلامة، رجوع).

الفرق عن FreeRide: التحويل **بين الجلسات** لا داخل الطلب نفسه. مقبول هنا لأن الدور الواحد في
PicoClaw قصير (نداء أداة + رد)، والفارق يظهر فقط عند فشل منتصف الدور.

## إن أردت FreeRide فعلًا

**خيار أ — على السيرفر ثم عبر Tailscale:**
```bash
python3 -m venv ~/fr && ~/fr/bin/pip install freeride-gateway
printf 'OPENROUTER_API_KEY=...\nOLLAMA_CLOUD_API_KEY=...\n' > ~/.freeride/.env && chmod 600 ~/.freeride/.env
~/fr/bin/freeride telemetry off && ~/fr/bin/freeride serve --port 11343
```
ثم على الجوال: `picoclaw model add -b http://100.86.11.20:11343/v1 -k any -n freeride --model <id>`
— لكن هذا يجعل الوكيل يعتمد على السيرفر؛ إن سقط السيرفر سقط النموذج.

**خيار ب — على الجوال بعد إصلاح النظام:**
```bash
pkg upgrade           # يصلح libexpat/pyexpat — يأخذ وقتًا ويجرّ ترقيات
pip install freeride-gateway && freeride telemetry off
# ثم وحدة runit باسم freeride تشغّل: freeride serve --port 11343
```
اختبرها على جهاز غير الإنتاج أولًا.

## الأمان

- البوابة ترى كل نص يُرسَل (محلية، لكنها طرف ثالث في مسار المحتوى).
- مفاتيحها في `~/.freeride/.env` (0600) وليست في المستودع.
- التليمتري يجب أن يبقى مطفأً.
- سيرفرات MCP الخارجية لم تتغير: `crm` يبقى على loopback.
