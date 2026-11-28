# edge-mcp — أدوات سحابية بلا حالة للـCRM

Worker واحد على Cloudflare، يقدّم **MCP** عبر HTTPS. الجوال يبقى صاحب البيانات؛
الـWorker يقدّم قدرة (CPU، شبكة، أسرار) لا يخزّن شيئًا.

## الأدوات

| الأداة | الوظيفة | يحتاج مفتاح؟ |
|---|---|---|
| `edge_web_extract` | جلب صفحة وإرجاع نصها المقروء (بلا scripts/styles)، بحد أقصى للبايتات | لا |
| `edge_search` | Tavily → Brave → DuckDuckGo (احتياطي) | لا (الاحتياطي غير موثوق) |
| `edge_status` | المزوّدون المضبوطون، عدد النداءات، الإصدار | لا |

## النشر الحي

| | |
|---|---|
| الرابط | `https://edge-mcp.ncecpmo.workers.dev` |
| الحساب | `0476abbe850271778d2149ce242d005a` (`ncec.pmo.tv@gmail.com`) |
| نطاق workers.dev | `ncecpmo` (سُجّل عبر `PUT /accounts/<id>/workers/subdomain`) |
| KV | `STATUS` = `9114b63f0a7347bb984f52f0e8235f5b` |
| R2 | **معلّق** — الإنشاء يعيد `10042 Please enable R2 through the Cloudflare Dashboard` |
| النماذج | تحويل: `whisper-large-v3-turbo` → `whisper` · رؤية: `llama-4-scout-17b-16e-instruct` |

`llava-1.5-7b-hf` أُوقف في 2026-11-20، و`whisper-large-v3-turbo` لا يعيد نصًا عربيًا، لذا كل
مساعد يمشي على قائمة نماذج ويعيد اسم النموذج الذي أجاب فعلًا.

ثلاث مصائد كلّفت وقتًا حقيقيًا:

1. **مفاتيح `cfk_` ليست Bearer tokens.** المفتاح العام يحتاج `X-Auth-Email` + `X-Auth-Key`
   (في wrangler: `CLOUDFLARE_EMAIL` + `CLOUDFLARE_API_KEY`)، ويحتاج `CLOUDFLARE_ACCOUNT_ID`
   إن كان المفتاح يرى أكثر من حساب.
2. **`urllib` بلا User-Agent** يأخذ `403 error code: 1010` من قواعد Cloudflare حتى على Worker
   خاص بك؛ `bridge/edge.py` يرسل UA حقيقيًا.
3. **الخدمة على الجوال تقرأ `~/gowa-espo/.env`** لا `~/crm/crm.env`؛ استخدم
   `scripts/phone-edge-env.sh`.

## النشر (5 دقائق، بلا بطاقة لخطة Workers المجانية)

```bash
cd edge
npx wrangler login                       # متصفح، مرة واحدة
npx wrangler secret put EDGE_TOKEN       # اكتب توكنًا طويلًا (32+ حرفًا)
# اختياري — يرفع جودة البحث كثيرًا:
npx wrangler secret put TAVILY_API_KEY   # tavily.com: رصيد مجاني شهري
npx wrangler secret put BRAVE_API_KEY    # بديل
npx wrangler deploy
```

سينتج رابطًا مثل:

```
https://edge-mcp.<account>.workers.dev
```

## الربط بـPicoClaw على الجوال

```bash
TOKEN=<نفس EDGE_TOKEN>
~/pico/bin/picoclaw mcp add edge https://edge-mcp.<account>.workers.dev/mcp \
  -t http -H "Authorization: Bearer $TOKEN" -f
sv restart picoclaw          # أو: PICOCLAW_HOME=~/pico ~/pico/bin/picoclaw gateway
```

تحقّق أن الأدوات ظهرت:

```bash
curl -s https://edge-mcp.<account>.workers.dev/health
# {"ok":true,"service":"edge-mcp","version":"0.1.0","tools":3}
```

## التشغيل محليًا (بلا حساب)

```bash
cd edge
EDGE_TOKEN=dev node dev-server.mjs        # http://127.0.0.1:8787/mcp
curl -s -X POST http://127.0.0.1:8787/mcp \
  -H 'Authorization: Bearer dev' -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
npm test                                   # 13 اختبارًا بلا اعتماديات
```

## مصيدة النشر التجريبي — وكيف حُلّت

نشرتُ نسخة تجريبية (`wrangler deploy --temporary`) على `*.workers.dev`:

- من السيرفر: كل شيء يعمل (200، أدوات، جلب حقيقي 0.32 ثانية).
- **من الجوال: 403 مع `cf-mitigated: challenge`** — تحدي إدارة من Cloudflare لعناوين
  شبكات الجوال على الحسابات التجريبية.

**الحل الذي نجح:** المطالبة بالحساب من رابط `claim-preview` الذي يطبعه wrangler خلال
60 دقيقة. بعد المطالبة اختفى التحدي، وأصبح نفس الرابط يعمل من الجوال.

بدائل إن تكرر: نطاق خاص عبر Workers Routes، أو تعطيل Bot Fight Mode في المنطقة.

**الدرس:** `edge_status` لا يستطيع كشف هذا العطل لأنه لا يُنفَّذ أصلًا؛ علامة
`cf-mitigated: challenge` تعني مشكلة حساب/منطقة، لا مشكلة أداة.

## القيود المقاسة

- **DuckDuckGo الاحتياطي يعيد صفرًا من عناوين مراكز البيانات** (اختُبر من هذا السيرفر) —
  لذلك الأداة تُرجع `note` صريحًا، والطريق الموثوق مفتاح Tavily أو Brave.
- خطة Workers المجانية: **100,000 طلب/يوم** و**10ms CPU** — الجلب والانتظار لا يُحسبان،
  لكن تحليل HTML ضخم يُحسب: لذلك سقف البايتات ونصّ افتراضي 6,000 حرف.
- الـWorker **لا يخزّن** نتائج ولا بيانات؛ كل نداء مستقل.

## الأمان

- توكن Bearer إلزامي، مقارنة بزمن ثابت، ولا يُعاد في أي رد.
- لا أسرار في `wrangler.toml` — كلها عبر `wrangler secret`.
- `edge_status` يعيد **أعلامًا** فقط (`brave: true/false`)، لا المفاتيح.
- الجوال لا يثق بالرد أعمى: أي فشل يُعاد كنص خطأ واضح، والمهارة تُلزم الوكيل بقوله.
