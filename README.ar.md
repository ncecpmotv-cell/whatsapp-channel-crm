# جسر GOWA ⇄ EspoCRM على أندرويد (Termux، بلا روت وبلا Docker)

تشغيل **واتساب** (عبر GOWA) و**EspoCRM** معاً على هاتف أندرويد محدود الموارد،
مع جسر ثنائي الاتجاه يسجّل الرسائل الواردة في الـ CRM وينشر سجلات الـ CRM في
قنوات واتساب.

> English: [README.md](README.md)

بُني واختُبر فعلياً على **Huawei P Smart 2019** (Kirin 710، ذاكرة 2.69GB،
أندرويد 9 / EMUI 9.1) داخل Termux، **بلا روت وبلا Docker**.

---

## ما يفعله

**من واتساب إلى الـ CRM**

- رسالة خاصة واردة ← يبحث عن جهة الاتصال برقم الهاتف أو ينشئها، ويضيف الرسالة
  إلى سجلّها الزمني.
- منشور جديد في قناة متابَعة ← يُخزَّن كسجل `WhatsAppChannelPost` مع النص ونوع
  الميديا والتوقيت ومعرّف الخادم.
- عدّادات القناة (مشاهدات / إعادة نشر / تفاعلات) ← تُحدَّث على نفس السجل.

**من الـ CRM إلى واتساب**

- سجل `WhatsAppChannelPost` تُغيّر حالته إلى **Ready to Publish** ← يُنشر في
  القناة فوراً عبر خطّاف `afterSave`، ويلتقطه أيضاً فاحص كل 60 ثانية كشبكة أمان.
- أي `Contact` أو `Lead` يمكن مراسلته عبر نفس الـ webhook.

**الموثوقية** — كل عملية نشر تمرّ عبر صندوق صادر في SQLite مع إعادة محاولة
وتراجع زمني، فلا تضيع رسالة إذا خرج الجهاز من الشبكة أو نام الهاتف.

**MCP** — نفس العملية تخدم نقطة Model Context Protocol على `POST /mcp`، فيستطيع
أي عميل ذكاء اصطناعي البحث في الـ CRM، وجدولة منشورات القنوات أو نشرها، وقراءة
قناة، وإرسال رسائل واتساب. التفاصيل في [docs/MCP.md](docs/MCP.md).

---

## المعمارية

```
واتساب ──▶ GOWA :3000 ──webhook(HMAC)──▶ الجسر :8085 ──X-Api-Key──▶ EspoCRM :8081
                ▲                              │                        │
                └────── /send/message ─────────┘                        │
                                                          خطّاف afterSave + فاحص 60ث
```

التفاصيل الكاملة في [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## البدء السريع

### 1. بناء ملف GOWA التنفيذي (على أي جهاز فيه Docker)

نسخة `linux-arm64` الرسمية **لا تعمل على Termux** لأنها مرتبطة بـ glibc.
هذا السكربت ينتج نسخة static musl تعمل:

```bash
./scripts/build-gowa-arm64.sh 9.10.0 ./whatsapp
scp ./whatsapp <الجوال>:~/gowa-espo/bin/whatsapp
```

### 2. تثبيت الحزمة على الجوال

```bash
# داخل Termux
git clone <هذا المستودع> ~/gowa-espocrm-bridge
cd ~/gowa-espocrm-bridge
bash scripts/install-termux.sh
```

يثبّت الحِزم، ويهيّئ MariaDB بضبط منخفض الذاكرة، ويعدّ PHP-FPM وnginx، وينزّل
EspoCRM، ويثبّت الكيان المخصص، وينشئ مستخدم API بأقل صلاحية، ويسجّل كل الخدمات
تحت runit.

### 3. ربط واتساب

```bash
curl -X POST localhost:3000/devices -H 'Content-Type: application/json' \
  -d '{"device_id":"primary","webhook_url":"http://127.0.0.1:8085/webhook/gowa"}'

curl -s localhost:3000/devices/primary/login
# ← results.qr_link : نزّل الصورة وامسحها من واتساب ← الأجهزة المرتبطة
```

الرمز صالح 30 ثانية؛ أعد الطلب إن انتهى.

### 4. تحديد القناة

```bash
# ~/gowa-espo/.env
NEWSLETTER_JIDS=120363024512399999@newsletter
```

```bash
sv restart bridge
```

### 5. فحص السلامة

```bash
bash scripts/start-all.sh
curl -s localhost:8085/health | python3 -m json.tool
```

---

## الإعدادات

كل شيء في ملف واحد `~/gowa-espo/.env` (صلاحياته `600` ومُستثنى من git).
القائمة الكاملة في [.env.example](.env.example).

| المفتاح | الغرض |
|---------|-------|
| `GOWA_BASE_URL` | عنوان GOWA (محلي فقط) |
| `GOWA_WEBHOOK_SECRET` | مفتاح توقيع `X-Hub-Signature-256` |
| `BRIDGE_TOKEN` | رمز الحامل الذي يقدّمه EspoCRM |
| `ESPO_BASE_URL` / `ESPO_API_KEY` | عنوان الـ CRM ومفتاح مستخدم API |
| `NEWSLETTER_JIDS` | القنوات المراقَبة؛ فارغ = كل القنوات المتابَعة |
| `DEFAULT_COUNTRY_CODE` | لتطبيع الأرقام المحلية |
| `BRIDGE_POLL_INTERVAL` | ثواني فحص النشر (افتراضي 60) |
| `BRIDGE_CHANNEL_SYNC_INTERVAL` | ثواني مزامنة القنوات (افتراضي 300) |

---

## التشغيل والصيانة

```bash
sv status mariadb php-fpm nginx gowa bridge
tail -f $PREFIX/var/log/sv/bridge/current
curl -s localhost:8085/health
```

الخدمات تصمد بعد إغلاق الطرفية وبعد إعادة التشغيل (runit + `~/.termux/boot`).
لكن EMUI يحتاج ثلاثة أذونات إضافية وإلا قتل Termux ليلاً — راجع
[docs/EMUI-BATTERY.md](docs/EMUI-BATTERY.md).

---

## الأمان

- GOWA وEspoCRM والجسر تستمع على **127.0.0.1 فقط**.
- webhooks القادمة من GOWA موقّعة بـ HMAC-SHA256 على الجسم الخام.
- نداءات EspoCRM ← الجسر تتطلب رمز حامل يُقارن بثبات زمني.
- الجسر يستخدم **مستخدم API مخصصاً** بدور محدود (Contact/Lead/Case/Account/
  WhatsAppChannelPost/Note) وليس كلمة سر الأدمن.
- `.env` وبيانات جلسة واتساب وقواعد SQLite مستثناة من git.

لا تُعرّض أي منفذ للإنترنت مباشرة؛ استخدم Tailscale أو نفق SSH.

---

## حدود معروفة

- **النشر يتطلب صلاحية أدمن في القناة.** حساب متابع يستطيع المراقبة والتسجيل
  لكن واتساب يرفض النشر باسمه.
- **`views_count` للأدمن فقط**؛ الحسابات الأخرى تستلم 0.
- **اشتراكات العدّادات تعيش في ذاكرة GOWA**، لذا يعيد الجسر الاشتراك عند كل
  تشغيل وعند كل دورة مزامنة.
- لا نستخدم Advanced Pack (مدفوع)؛ النشر الفوري عبر خطّاف `afterSave` المخصص
  والفاحص يغطي فشل الخطّاف.
- الميديا تُشار إليها ولا تُنسخ (GOWA بـ `--auto-download-media=false`) للحفاظ
  على الذاكرة.
- السكربتات مستخلَصة من الأوامر التي بنت الجهاز المرجعي فعلاً، لكن تشغيلها من
  الصفر على نسخة أندرويد مختلفة قد يحتاج تعديل مسارات أو حِزم.

---

## بنية المستودع

```
bridge/              خدمة Python (إعدادات، عملاء، صندوق صادر، HTTP، اختبارات)
espocrm-custom/      تعريفات الكيان والتخطيطات وcontroller/entity/hook وvhost
scripts/             install-termux.sh، build-gowa-arm64.sh، وحدات runit، ضبط
docs/                المعمارية، الـ API، بطارية EMUI، حل المشكلات
```

الاختبارات بلا أي اعتماديات: `cd bridge && python3 -m unittest discover -s tests`

---

## الترخيص

MIT — راجع [LICENSE](LICENSE).
