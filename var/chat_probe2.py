import json, os, sys
sys.path.insert(0, "/app/bridge")
os.environ["PICO_TOKEN"] = open("/var/crm/pico.token").read().strip()
import chat
raw = []
answer = chat.ask("كم عدد المنشورات المنشورة في القناة؟ اذكر الرقم فقط ثم سطر شرح.", raw_log=raw)
print("ANSWER:", repr(answer[:300]))
for f in raw:
    try:
        d = json.loads(f)
    except Exception:
        continue
    p = d.get("payload") or {}
    print(d.get("type"), "| kind:", p.get("kind"), "| final:", p.get("final"),
          "| len:", len(p.get("content") or ""), "| tools:", len(p.get("tool_calls") or []))
