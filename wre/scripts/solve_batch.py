"""Solve every protected row from screen_results.json (first solve pass).

Usage: python wre/scripts/solve_batch.py
"""

import io
import json
import os
import time

from _paths import RESULTS
from wre_client_akamai import AkamaiClient

recs = json.load(io.open(os.path.join(RESULTS, "screen_results.json"), encoding="utf-8"))
targets = [r for r in recs if r.get("protected")]
print("solving:", [r["host"] for r in targets], flush=True)

out = []
for i, r in enumerate(targets, 1):
    url = r["url"]
    rec = {"host": r["host"], "url": url, "sensor": r.get("sensor")}
    t0 = time.time()
    try:
        with AkamaiClient.open({"page_url": url}, startup_timeout=30) as c:
            try:
                s = c.solve({}, deadline=150)
                abck = s["cookies"]["abck"]
                rec.update({
                    "solve_secs": round(time.time() - t0, 1),
                    "machine": s["run"]["machine"],
                    "abck_status": abck["status"],
                    "abck_validated": abck["validated"],
                    "abck_rejected": abck["rejected"],
                    "posts": len(s.get("posts", [])),
                    "telemetry_bytes": len(s.get("telemetry") or ""),
                    "pow_field": abck["fields"][4] if len(abck["fields"]) > 4 else None,
                })
            except Exception as e:
                rec["solve_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
            try:
                a = c.request({"url": url, "method": "GET"}, deadline=90)
                low = a["body"].lower()
                rec.update({
                    "recheck_status": a["status"],
                    "recheck_refused": a["refused"],
                    "recheck_len": len(a["body"]),
                    "marks": {m: (m in low) for m in
                              ("challenge", "access denied", "captcha", "bm-verify", "denied")},
                })
                import re as _re
                m = _re.search(r"<title[^>]*>(.*?)</title>", a["body"], _re.I | _re.S)
                rec["title"] = _re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else None
            except Exception as e:
                rec["recheck_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    except Exception as e:
        rec["open_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    out.append(rec)
    print("[%d/%d] %-28s abck=%s validated=%s posts=%s recheck=%s %ss" % (
        i, len(targets), rec["host"],
        rec.get("abck_status", "?"), rec.get("abck_validated", "?"),
        rec.get("posts", "?"), rec.get("recheck_status", rec.get("solve_error", "?")[:30]),
        rec.get("solve_secs", "?")), flush=True)

with io.open(os.path.join(RESULTS, "solve_results.json"), "w", encoding="utf-8") as f:
    f.write(json.dumps(out, ensure_ascii=False, indent=1))
print("written results/solve_results.json", flush=True)
