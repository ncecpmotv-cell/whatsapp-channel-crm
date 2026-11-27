# من صفر إلى نظام يعمل

دليل واحد، بالترتيب، لكل ما يحتاجه المشروع — بما فيها الخدمات التي لا يغطيها
`install.sh` تلقائيًا. اتبع الخطوات كما هي؛ كل خطوة تقول لك كيف تتأكد أنها نجحت.

---

## 0) قبل البدء

| المتطلب | لماذا | كيف |
|---|---|---|
| Termux من **F-Droid** (لا من Play) | إصدار Play قديم ولا يدعم `pkg` الحديث | https://f-droid.org/packages/com.termux |
| **Termux:Boot** | إقلاع تلقائي بعد إعادة تشغيل الجوال | https://f-droid.org/packages/com.termux.boot |
| **Termux:API** (اختياري) | إشعارات على شاشة الجوال | https://f-droid.org/packages/com.termux.api |
| مساحة ~2 GB | GOWA (32MB) + PicoClaw (35MB) + بيانات | `df -h $HOME` |
| شبكة | تنزيل الحزم وربط واتساب | Wi-Fi أفضل للتنزيل الأول |

> **لماذا F-Droid؟** إصدار Google Play لـTermux مهمل ولا يستقبل تحديثات الحزم.

---

## 1) الأمر الواحد

```bash
pkg update -y && pkg install -y git
git clone https://github.com/ncecpmotv-cell/whatsapp-channel-crm
cd whatsapp-channel-crm
bash scripts/install.sh
```

### ماذا يفعل المثبّت بالضبط

| # | الخطوة | الناتج |
|---|---|---|
| 1 | حزم Termux: `python curl unzip tar openssl-tool proot` | متطلبات التشغيل |
| 2 | **GOWA** — أحدث إصدار Linux لمعمارية الجهاز | `bin/gowa` |
| 3 | **PicoClaw** — أرشيف `arm64`/`x86_64` من الإصدارات | `bin/picoclaw` |
| 4 | نسخ كود الـCRM (`bridge/`, `scripts/`, `picoclaw/skills`) | `app/` |
| 5 | توليد الأسرار: `BRIDGE_TOKEN`, `GOWA_WEBHOOK_SECRET`, كلمة GOWA | `etc/*.env` بصلاحية 600 |
| 6 | ضبط PicoClaw: `config reset` + `picoclaw mcp add crm http://127.0.0.1:8085/mcp` | `picoclaw/config.json` |
| 7 | تثبيت مهارة `content-strategist` | `picoclaw/skills/` |
| 8 | إنشاء `bin/crmctl` (start/stop/restart/status/logs) | تحكم واحد |
| 9 | وحدة `runit` على Termux (أو تعليمات systemd) | تشغيل دائم |
| 10 | **Tailscale**: تنزيل `tailscale` + `tailscaled` الثابتين، وحدة `tailscaled` بـ`--statedir` | `bin/tailscale` |
| 11 | **Tailscale login**: يطبع رابط تفويض مرة واحدة | عقدة في شبكتك |
| 12 | تشغيل المكدّس | `crmctl start` |

> في بيئة غير Termux (سيرفر Debian)، المثبّت لا ينزّل Tailscale — يطبع لك أمر
> `tailscaled` الجاهز. الباقي نفسه.

---

## 2) Tailscale — العقدة والتسجيل والنشر

هذه هي الخطوة التي ينساها الجميع، وهي **إلزامية** إن أردت فتح الواجهة من خارج الجوال.

```bash
# 11) المثبّت طبع رابطًا مثل:
#     https://login.tailscale.com/a/xxxxxxxx
# افتحه في المتصفح وسجّل الدخول بحساب Tailscale (مجاني للاستخدام الشخصي).

# 12) بعد التسجيل، انشر الواجهة على الشبكة:
bash scripts/install.sh --finish
```

`--finish` ينفّذ:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8085
```

فيصبح الرابط: `https://<hostname>.<tailnet>.ts.net`

### التحقق

```bash
SOCK=$HOME/.whatsapp-crm/var/tailscaled.sock
$HOME/.whatsapp-crm/bin/tailscale --socket=$SOCK status     # عقدتك = online
$HOME/.whatsapp-crm/bin/tailscale --socket=$SOCK serve status
curl -s http://127.0.0.1:8085/health                        # ok
```

### أخطاء شائعة وحلولها

| الأعراض | السبب | الحل |
|---|---|---|
| `serve` يعمل لكن HTTPS لا يفتح | `tailscaled` بلا `--statedir` → `no TailscaleVarRoot` | المثبّت يضيفه؛ إن شغّلت `tailscaled` يدويًا أضفه |
| `logged out` بعد إعادة التشغيل | الحالة في مكان مؤقت | الحالة في `var/tailscaled.state` — تحقّق أن الوحدة تقرأه |
| الاسم يتغيّر بعد كل إعداد | `tailnet` فيه عقدة بنفس الاسم | `tailscale up --hostname <اسم-فريد>` |
| الرابط يفتح من الجوال فقط | Tailscale غير مفعّل على الجهاز الآخر | ثبّت التطبيق وسجّل بنفس الحساب |

---

## 3) ربط واتساب (GOWA)

```bash
bash scripts/install.sh --qr     # يعرض QR في الطرفية
```

- من الجوال: واتساب → **الأجهزة المرتبطة** → **ربط جهاز** → امسح.
- الجلسة تُحفظ في `~/.whatsapp-crm/var/gowa/`؛ لا تمسح مرة أخرى بعد كل تشغيل.
- للتحقق:

```bash
curl -s -u "crm:<GOWA_PASSWORD>" -H 'X-Device-Id: primary' \
  http://127.0.0.1:3000/app/status     # is_logged_in: true
```

---

## 4) الوكيل (PicoClaw)

```bash
PICOCLAW_HOME=$HOME/.whatsapp-crm/picoclaw \
  $HOME/.whatsapp-crm/bin/picoclaw onboard     # مفتاح المزوّد + بوت تليجرام (اختياري)
$HOME/.whatsapp-crm/bin/crmctl restart
```

تحقّق:

```bash
curl -s http://127.0.0.1:18790/health          # {"status":"ok"}
PICOCLAW_HOME=$HOME/.whatsapp-crm/picoclaw \
  $HOME/.whatsapp-crm/bin/picoclaw skills list # content-strategist
```

---

## 5) الإشعارات على شاشة الجوال (اختياري)

**الطريق أ — Termux:API** (محلي، بلا حساب):

```bash
pkg install -y termux-api
# + تثبيت تطبيق Termux:API من F-Droid وفتحه مرة واحدة
termux-notification --title "اختبار" --content "إن وصلت، فكل شيء جاهز"
```

**الطريق ب — بوت تليجرام** (يعمل حتى لو كان التطبيق مغلقًا):

1. `@BotFather` → `/newbot` → خذ التوكن.
2. أرسل رسالة للبوت، ثم افتح
   `https://api.telegram.org/bot<TOKEN>/getUpdates` وخذ `chat.id`.
3. أضف إلى `etc/crm.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
PUSH_EVENTS=content,publish,failed
```

4. `crmctl restart` ثم `curl http://127.0.0.1:8085/health` → `"push":{"enabled":true}`.

---

## 6) فحص شامل بعد التركيب

```bash
bash scripts/doctor.sh
```

يفحص دفعة واحدة: الأدوات، الوحدات، المنافذ الثلاثة، اقتران واتساب، عدد أدوات MCP،
مهارات الوكيل، عقدة Tailscale ونشرها، وحالة الإشعارات — ويطبع `✓ / ✗ / !` ورمز خروج ≠ 0
عند أي فشل. لا يصلح شيئًا، فقط يقول الحقيقة.

```bash
python3 -m unittest discover -s bridge/tests      # من داخل الريبو
```

---

## 7) ما يبقى يدويًا (لا يمكن أتمتته)

| البند | لماذا |
|---|---|
| مسح QR لواتساب | يتطلب جوالك |
| فتح رابط Tailscale مرة واحدة | مصادقة حسابك |
| مفتاح مزوّد النموذج | سرّي، تملكه أنت |
| توكن بوت تليجرام | يُنشأ من حسابك |
| السماح للتطبيق بالعمل في الخلفية | إعداد أندرويد: Battery → Unrestricted |

---

## 8) بعد إعادة تشغيل الجوال

- Termux:Boot يشغّل `~/start.sh` (أو `crmctl start`) تلقائيًا إن ثبّت التطبيق.
- تحقّق مرة واحدة: `crmctl status` — يجب أن ترى gowa/crm/picoclaw.
- إن كان Tailscale متوقفًا: `sv up tailscaled` ثم `tailscale serve status`.
