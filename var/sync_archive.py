import os, sys
sys.path.insert(0, "/app/bridge")
os.environ["BRIDGE_ENV_FILE"] = "/var/crm/node.env"
from config import Config
from service import Bridge
b = Bridge(Config.load())
print("imported posts:", b.sync_channels(count=100))
print("counters updated:", b.sync_counters())
print("channel:", b.refresh_channel_info().get("name"))
