"""First sweep: Japan-located customer hosts plus a small EXTRA list.

Usage: python wre/scripts/screen.py
"""

import csv
import io
import json
import os
import time

from _paths import DATASET, RESULTS
from wre_client_akamai import AkamaiClient

CSV = DATASET

# 日本站优先（CN IP 最容易拿到响应），再加几个欧洲/东南亚大站
EXTRA = [
    "commerzbank.de",
    "www.aareal-bank.com",
    "bmo.com",
    "rytbank.my",
    "www.asus.com",
    "www.airbnb.com",
    "www.adobe.com",
    "onefootball.com",
    "www.alodokter.com",
    "telegraphmediagroup.com",
    "www.alphanetworks.tv",
    "www.bio-techne.com",
]

rows = list(csv.DictReader(io.open(CSV, encoding="utf-8")))
hosts = []
for r in rows:
    if "Japan" in (r.get("location") or ""):
        hosts.append((r["host"], r.get("location", ""), r.get("industry", "")))
for h in EXTRA:
    hosts.append((h, "extra", ""))

seen = set()
uniq = []
for h, loc, ind in hosts:
    if h and h not in seen:
        seen.add(h)
        uniq.append((h, loc, ind))

print("candidates:", len(uniq), flush=True)
out = []
for i, (host, loc, ind) in enumerate(uniq, 1):
    url = "https://" + host + "/"
    rec = {"host": host, "location": loc, "industry": ind, "url": url}
    t0 = time.time()
    try:
        with AkamaiClient.open({"page_url": url}, startup_timeout=30) as c:
            d = c.discover({}, deadline=45)
            surf = d["surface"]
            rec.update({
                "status": d["status"],
                "protected": d["protected"],
                "sensor": surf["sensor"]["kind"] if surf["sensor"] else None,
                "challenge_page": surf["challenge_page"],
                "baza_bits": (surf["config"] or {}).get("bits"),
                "abck_state": (d["cookies"] or {}).get("state"),
                "secs": round(time.time() - t0, 1),
            })
    except Exception as e:
        rec.update({"error": "%s: %s" % (type(e).__name__, str(e)[:160]),
                    "secs": round(time.time() - t0, 1)})
    out.append(rec)
    print("[%d/%d] %-40s status=%-4s protected=%-5s sensor=%-10s %ss" % (
        i, len(uniq), host, rec.get("status"), rec.get("protected"),
        rec.get("sensor") or rec.get("error", "")[:40], rec["secs"]), flush=True)

with io.open(os.path.join(RESULTS, "screen_results.json"), "w", encoding="utf-8") as f:
    f.write(json.dumps(out, ensure_ascii=False, indent=1))
print("\nwritten results/screen_results.json", flush=True)
