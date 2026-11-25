"""Batch discover over datasets/akamai_customers/sites.csv.

Usage: python wre/scripts/screen2.py [offset] [limit]
"""

import csv
import io
import json
import os
import sys
import time

from _paths import DATASET, RESULTS
from wre_client_akamai import AkamaiClient

CSV = DATASET
PRIO = ("Commerce", "Retail", "Financial", "Media", "Games", "Travel", "Telecom")

offset = int(sys.argv[1]) if len(sys.argv) > 1 else 0
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 70

rows = list(csv.DictReader(io.open(CSV, encoding="utf-8")))

tested = set()
for fn in ("screen_results.json", "screen2_results.json"):
    path = os.path.join(RESULTS, fn)
    if os.path.exists(path):
        for r in json.load(io.open(path, encoding="utf-8")):
            tested.add(r["host"])

rest = [r for r in rows if r["host"] and r["host"] not in tested]
rest.sort(key=lambda r: 0 if any(p in (r.get("industry") or "") for p in PRIO) else 1)
batch = rest[offset:offset + limit]
print("remaining: %d, this batch: %d (offset %d)" % (len(rest), len(batch), offset), flush=True)

out = []
for i, r in enumerate(batch, 1):
    host = r["host"]
    url = "https://" + host + "/"
    rec = {"host": host, "url": url, "location": r.get("location", ""),
           "industry": r.get("industry", "")}
    t0 = time.time()
    try:
        with AkamaiClient.open({"page_url": url}, startup_timeout=25) as c:
            d = c.discover({}, deadline=40)
            surf = d["surface"]
            rec.update({
                "status": d["status"],
                "protected": d["protected"],
                "sensor": surf["sensor"]["kind"] if surf["sensor"] else None,
                "challenge_page": surf["challenge_page"],
                "baza_bits": (surf["config"] or {}).get("bits"),
                "secs": round(time.time() - t0, 1),
            })
    except Exception as e:
        rec.update({"error": "%s: %s" % (type(e).__name__, str(e)[:120]),
                    "secs": round(time.time() - t0, 1)})
    out.append(rec)
    print("[%d/%d] %-38s %-20s status=%-4s prot=%-5s sensor=%s %ss" % (
        i, len(batch), host, (r.get("industry") or "")[:20],
        rec.get("status"), rec.get("protected"),
        rec.get("sensor") or (rec.get("error") or "")[:30], rec["secs"]), flush=True)

prev = []
path = os.path.join(RESULTS, "screen2_results.json")
if os.path.exists(path):
    prev = json.load(io.open(path, encoding="utf-8"))
with io.open(path, "w", encoding="utf-8") as f:
    f.write(json.dumps(prev + out, ensure_ascii=False, indent=1))
print("saved results/screen2_results.json (%d total)" % (len(prev) + len(out)), flush=True)
