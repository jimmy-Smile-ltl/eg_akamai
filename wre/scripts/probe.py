"""Discover or solve one site; prints raw JSON slices.

Usage: python wre/scripts/probe.py <url> [discover|solve]
"""

import json
import sys
import time

from wre_client_akamai import AkamaiClient

url = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "discover"
t = time.time()
with AkamaiClient.open({"page_url": url}, startup_timeout=60) as c:
    print("open %.1fs" % (time.time() - t))
    try:
        d = c.discover({}, deadline=120)
        print("discover %.1fs" % (time.time() - t))
        print(json.dumps(d, default=str)[:2500])
    except Exception as e:
        print("discover FAILED after %.1fs: %s: %s" % (time.time() - t, type(e).__name__, str(e)[:300]))
    if mode == "solve":
        print("---")
        try:
            s = c.solve({}, deadline=240)
            print("solve %.1fs" % (time.time() - t))
            print(json.dumps(s, default=str)[:5000])
        except Exception as e:
            print("solve FAILED after %.1fs: %s: %s" % (time.time() - t, type(e).__name__, str(e)[:300]))
