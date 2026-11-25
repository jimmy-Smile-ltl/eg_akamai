"""Solve protected hosts with a plain-curl control before each attempt.

Usage: python wre/scripts/solve_batch2.py [offset] [limit]
"""

import json
import os
import re
import subprocess
import sys
import time

from _paths import NULL, RESULTS
from wre_client_akamai import AkamaiClient

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")

recs = []
for fn in ("screen_results.json", "screen2_results.json"):
    path = os.path.join(RESULTS, fn)
    if os.path.exists(path):
        recs += json.load(open(path, encoding="utf-8"))
targets = [r for r in recs if r.get("protected")]

done = set()
path = os.path.join(RESULTS, "solve2_results.json")
if os.path.exists(path):
    for r in json.load(open(path, encoding="utf-8")):
        done.add(r["host"])

targets = [r for r in targets if r["host"] not in done]
offset = int(sys.argv[1]) if len(sys.argv) > 1 else 0
limit = int(sys.argv[2]) if len(sys.argv) > 2 else len(targets)
batch = targets[offset:offset + limit]
print("protected total: %d, remaining: %d, batch: %d" % (len(targets) + len(done), len(targets), len(batch)), flush=True)


def curl_status(url):
    r = subprocess.run(["curl", "-s", "-o", NULL, "-w", "%{http_code} %{size_download}",
                        "-A", UA, "--max-time", "25", url], capture_output=True, text=True)
    return (r.stdout.strip() or ("ERR"))


out = []
for i, r in enumerate(batch, 1):
    url = r["url"]
    rec = {"host": r["host"], "url": url, "sensor": r.get("sensor"),
           "screen_status": r.get("status")}
    rec["curl"] = curl_status(url)
    t0 = time.time()
    try:
        with AkamaiClient.open({"page_url": url}, startup_timeout=30) as c:
            try:
                s = c.solve({}, deadline=120)
                abck = s["cookies"]["abck"]
                rec.update({
                    "solve_secs": round(time.time() - t0, 1),
                    "abck_status": abck["status"],
                    "validated": abck["validated"],
                    "posts": len(s.get("posts", [])),
                    "telemetry_bytes": len(s.get("telemetry") or ""),
                })
            except Exception as e:
                rec["solve_error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
            try:
                a = c.request({"url": url, "method": "GET"}, deadline=90)
                low = a["body"].lower()
                rec.update({"recheck": a["status"], "refused": a["refused"], "len": len(a["body"]),
                            "bm_verify": ("bm-verify" in low), "denied": ("access denied" in low)})
                m = re.search(r"<title[^>]*>(.*?)</title>", a["body"], re.I | re.S)
                rec["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:70] if m else None
            except Exception as e:
                rec["recheck_error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    except Exception as e:
        rec["open_error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    out.append(rec)
    print("[%d/%d] %-32s curl=%-12s abck=%-4s posts=%-4s recheck=%s %ss" % (
        i, len(batch), rec["host"], rec["curl"], rec.get("abck_status", "?"),
        rec.get("posts", "?"), rec.get("recheck", rec.get("solve_error", "?")),
        rec.get("solve_secs", "?")), flush=True)

path = os.path.join(RESULTS, "solve2_results.json")
prev = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
with open(path, "w", encoding="utf-8") as f:
    json.dump(prev + out, f, ensure_ascii=False, indent=1)
print("saved results/solve2_results.json (%d total)" % (len(prev) + len(out)), flush=True)
