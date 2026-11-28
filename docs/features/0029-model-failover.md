# 0029 — فشل تلقائي للنموذج، وتقييم FreeRide

- **Status:** shipped (modelwatch) · FreeRide evaluated, not installed
- **Owner:** @ncecpmotv-cell
- **Shipped in:** v4.18.0
- **Roadmap:** R-38
- **Files:** `bridge/modelwatch.py`, `bridge/service.py`, `bridge/config.py`, `bridge/orchestrator.py`, `bridge/ui.py`, `bridge/tests/test_modelwatch.py`, `docs/FREERIDE.md`

## Why

على الطبقات المجانية يفشل المزوّد (429/5xx/شبكة) في منتصف العمل. كان الحل يدويًا: `picoclaw model
fallback`. FreeRideV3 يحل ذلك داخل الطلب، لكن تركيبه على الجوال يتطلب ترقية نظام كاملة لأن
`pyexpat` معطوب. القيمة المطلوبة أُنجزت محليًا بلا اعتماديات.

## How

- فحص `GET {api_base}/models` كل ٣٠ دقيقة — **بلا توكنات**.
- فشل → تحويل إلى `fallback` + إشعار · عودة → رجوع تلقائي إلى `default` + إشعار.
- الحالة في `meta.model_health` وتُعرض في `/ui/capabilities` (النشط · السبب · آخر فحص).
- إيقاف/ضبط: `MODEL_WATCH_ENABLED` · `MODEL_WATCH_INTERVAL`.

## Verify

```bash
python3 -m unittest bridge.tests.test_modelwatch   # 5 tests
```
حيًّا: الفحص يعيد `healthy:true` على `default` و`active: default`.

## Limits

- التحويل بين الجلسات لا داخل الطلب (فرق عن FreeRide).
- فحص `/models` يثبت أن المزوّد حيّ، لا أن الحصة كافية؛ 429 يظهر عند أول طلب فعلي.
- لا يعيد ترتيب نماذج :free تلقائيًا؛ التبديل بين المزوّدين فقط.

## Links

- `docs/FREERIDE.md`
- [0028 — free models](0028-free-models-and-fallback.md)
