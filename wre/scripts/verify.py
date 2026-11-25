"""Solve one site, then re-check the same session and print the verdict fields.

Usage: python wre/scripts/verify.py <url>
"""

import json
import sys
import time

from wre_client_akamai import AkamaiClient

url = sys.argv[1]
with AkamaiClient.open({"page_url": url}, startup_timeout=60) as c:
    t = time.time()
    try:
        s = c.solve({}, deadline=240)
    except Exception as e:
        print("solve FAILED after %.1fs: %s: %s" % (time.time() - t, type(e).__name__, str(e)[:400]))
        raise SystemExit(1)
    print("solve: %.1fs" % (time.time() - t))
    print("machine:", s["run"]["machine"])
    abck = s["cookies"]["abck"]
    print("abck status: %r validated: %r rejected: %r" % (abck["status"], abck["validated"], abck["rejected"]))
    print("abck fields[1]: %r  fields[4]: %r" % (abck["fields"][1], abck["fields"][4]))
    print("posts:", len(s.get("posts", [])))
    print("telemetry bytes:", len(s.get("telemetry") or ""))
    try:
        a = c.request({"url": url, "method": "GET"}, deadline=120)
        print("recheck: status %r refused %r len %d" % (a["status"], a["refused"], len(a["body"])))
        title = a["body"].lower()
        print("marks:", {m: (m in title) for m in ("<title>", "challenge", "access denied", "bm-verify", "captcha")})
    except Exception as e:
        print("recheck FAILED: %s: %s" % (type(e).__name__, str(e)[:300]))
