"""Stability runs for the two increment candidates (APA ×3, akamai.com ×2)."""

import json
import os
import time

from _paths import RESULTS
from wre_client_akamai import AkamaiClient

TARGETS = [("https://www.apahotel.com/", 3), ("https://www.akamai.com/", 2)]
out = []

for url, n in TARGETS:
    for i in range(1, n + 1):
        rec = {"url": url, "run": i}
        t0 = time.time()
        try:
            with AkamaiClient.open({"page_url": url}, startup_timeout=30) as c:
                try:
                    s = c.solve({}, deadline=150)
                    abck = s["cookies"]["abck"]
                    rec.update({
                        "solve_secs": round(time.time() - t0, 1),
                        "abck_status": abck["status"],
                        "validated": abck["validated"],
                        "posts": len(s.get("posts", [])),
                    })
                except Exception as e:
                    rec["solve_error"] = "%s: %s" % (type(e).__name__, str(e)[:140])
                try:
                    a = c.request({"url": url, "method": "GET"}, deadline=90)
                    rec.update({"recheck": a["status"], "refused": a["refused"], "len": len(a["body"])})
                except Exception as e:
                    rec["recheck_error"] = "%s: %s" % (type(e).__name__, str(e)[:140])
        except Exception as e:
            rec["open_error"] = "%s: %s" % (type(e).__name__, str(e)[:140])
        out.append(rec)
        print(rec, flush=True)

with open(os.path.join(RESULTS, "repeat_results.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
