import json, os, sys
sys.path.insert(0, "/app/bridge")
os.environ["PICO_TOKEN"] = open("/var/crm/pico.token").read().strip()
import chat
raw = []
answer = chat.ask("كم عدد المنشورات المنشورة في القناة؟ استخدم أدوات CRM إن لزم.", raw_log=raw)
print("ANSWER:", answer[:600])
print("FRAMES:", len(raw))
for f in raw[:6]:
    print(" ", f[:180])
