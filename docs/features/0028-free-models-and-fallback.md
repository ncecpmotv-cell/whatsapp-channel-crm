# 0028 — نموذجان مجانيان ببديل جاهز، وإنضباط توكنز مقاس

- **Status:** shipped and measured on the phone
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.17.0
- **Roadmap:** R-37
- **Files:** `docs/MODELS.md`, `bridge/orchestrator.py`, `bridge/ui.py`

## Why

الوكيل كان يعمل على نموذج واحد عبر Ollama Cloud بلا بديل. أي 429 أو نفاد رصيد يوقف كل شيء،
والنماذج المجانية تُحسم بالتوكنات لا بالذكاء.

## How

- `default` = Ollama Cloud · `deepseek-v4.1-flash` (يعمل، 5.4s لدور كامل).
- `fallback` = OpenRouter free · `baidu/ernie-5.5-flash-preview:free` (يعمل، 7.3s، ويعيد
  `tool_calls` صحيحًا).
- التبديل أمر واحد: `picoclaw model fallback` / `picoclaw model default`.
- المفاتيح في `~/pico/.security.yml` (`model_list.<name>:0.api_keys`، صلاحية `0600`) ولا تدخل
  المستودع.
- `/ui/capabilities` صار يعرض النماذج وحالتها (الحالي/بديل).

## Verify

- استدعاء Ollama صغير: **75 توكن · 1.1s**.
- استدعاء OpenRouter بأداة: **177 توكن · 1.4s**.
- دور وكيل كامل بأداة MCP: **5.4s** أساسي · **7.3s** بديل.
- مفتاح Ollama الثاني رُفض من المزوّد (`Add usage credits`) فلم يُثبَّت.

## Limits

- التحويل بين النموذجين **يدوي** (أمر واحد)؛ لا يوجد تبديل تلقائي عند الفشل.
- `ernie-5.5-flash` سريع لكنه أقل عمقًا في التخطيط الطويل؛ اجعله للردود والمهام القصيرة.
- أرقام الطبقة المجانية تتغير؛ القياس على الجهاز هو المرجع.
