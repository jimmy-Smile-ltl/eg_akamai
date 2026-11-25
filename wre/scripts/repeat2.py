"""Stability runs for the three validated hosts (IBM / British Council / Tokopedia ×2)."""

import json
import os
import time

from _paths import RESULTS
from wre_client_akamai import AkamaiClient

TARGETS = [
    ("https://www.ibm.com/", 2),
    ("https://www.britishcouncil.org/", 2),
    ("https://www.tokopedia.com/", 2),
]
out = []
for url, n in TARGETS:
    for i in range(1, n + 1):
        rec = {"url": url, "run": i}
        t0 = time.time()
        try:
            with AkamaiClient.open({"page_url": url}, startup_timeout=30) as c:
                try:
                    s = c.solve({}, deadline=120)
                    abck = s["cookies"]["abck"]
                    rec.update({"secs": round(time.time() - t0, 1), "abck": abck["status"],
                                "validated": abck["validated"], "posts": len(s.get("posts", []))})
                except Exception as e:
                    rec["solve_error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
                try:
                    a = c.request({"url": url, "method": "GET"}, deadline=90)
                    rec.update({"recheck": a["status"], "len": len(a["body"])})
                except Exception as e:
                    rec["recheck_error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        except Exception as e:
            rec["open_error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        out.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)

with open(os.path.join(RESULTS, "repeat2_results.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
