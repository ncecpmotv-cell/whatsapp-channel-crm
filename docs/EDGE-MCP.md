# edge-mcp — أدوات سحابية بلا حالة للـCRM

Worker واحد على Cloudflare، يقدّم **MCP** عبر HTTPS. الجوال يبقى صاحب البيانات؛
الـWorker يقدّم قدرة (CPU، شبكة، أسرار) لا يخزّن شيئًا.

## الأدوات

| الأداة | الوظيفة | يحتاج مفتاح؟ |
|---|---|---|
| `edge_web_extract` | جلب صفحة وإرجاع نصها المقروء (بلا scripts/styles)، بحد أقصى للبايتات | لا |
| `edge_search` | Tavily → Brave → DuckDuckGo (احتياطي) | لا (الاحتياطي غير موثوق) |
| `edge_status` | المزوّدون المضبوطون، عدد النداءات، الإصدار | لا |

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

## مصيدة النشر التجريبي (مقاسة)

نشرتُ نسخة تجريبية (`wrangler deploy --temporary`) وعنوانها `*.workers.dev`:

- من السيرفر: كل شيء يعمل (‏200، أدوات، جلب حقيقي).
- **من الجوال: 403 مع `cf-mitigated: challenge`** — Cloudflare يقدّم تحدي إدارة
  (صفحة «Just a moment…») لعناوين شبكات الجوال على الحسابات التجريبية.

الحلول بالترتيب:

1. **مطالبة الحساب** من رابط `claim-preview` الذي يطبعه wrangler (خلال 60 دقيقة) —
   يصبح حسابًا مجانيًا حقيقيًا، وغالبًا يختفي التحدي.
2. **نطاق خاص** (`edge.example.com`) عبر Workers Routes — التحدي مرتبط بـ`workers.dev`.
3. تعطيل Bot Fight Mode في لوحة Cloudflare للنطاق.

حتى ذلك الحين: أبقِ خادم MCP `edge` معطّلًا في PicoClaw أو تقبّل فشل الاتصال في السجل.

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
