import json, os, sys
sys.path.insert(0, "/app/bridge")
import chat
q = "كم عدد المنشورات المنشورة؟ واذكر أفضل منشور بمشاهداته. باختصار."
raw = []
ans = chat.ask(q, raw_log=raw)
print("ANSWER:", repr(ans[:200]))
for f in raw:
    try: d=json.loads(f)
    except Exception: continue
    p=d.get("payload") or {}
    print(d.get("type"), "| kind:", p.get("kind"), "| final:", p.get("final"), "| len:", len(p.get("content") or ""), "| err:", (p.get("error") or "")[:60])
