"""Add a 10-day counter history for published posts (demo browsing)."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge"))
from crm import CrmClient
from store import Store

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/phone-crm/var/preview.db")
store = Store(DB)
crm = CrmClient(store)

posts = crm.list_posts("published", 20)
day = 86400
now = int(time.time())
for post in posts:
    base = post["views"] or 0
    for back in range(9, -1, -1):
        day_str = time.strftime("%Y-%m-%d", time.gmtime(now - back * day))
        if back == 0:
            views = base
        else:
            views = int(base * (0.55 + 0.45 * (9 - back) / 9))
        crm._exec(
            "INSERT INTO crm_stats (post_id, day, views, forwards, reactions, captured_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(post_id, day) DO UPDATE SET "
            "views=excluded.views, forwards=excluded.forwards, reactions=excluded.reactions",
            (post["id"], day_str, views,
             int((post["forwards"] or 0) * (views / base if base else 0)),
             int((post["reactions"] or 0) * (views / base if base else 0)), now - back * day),
        )
print("stats rows:", len(crm._all("SELECT * FROM crm_stats")))
store.close()
