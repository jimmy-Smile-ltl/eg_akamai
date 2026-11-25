"""Print the protected-host table and the solve rows from results/.

Usage: python wre/scripts/summary.py
"""

import json
import os

from _paths import RESULTS

recs = []
for fn in ("screen_results.json", "screen2_results.json"):
    path = os.path.join(RESULTS, fn)
    if os.path.exists(path):
        recs += json.load(open(path, encoding="utf-8"))

seen = {}
for r in recs:
    seen[r["host"]] = r
recs = list(seen.values())

prot = [r for r in recs if r.get("protected")]
print("screened: %d hosts, protected: %d" % (len(recs), len(prot)))
print()
print("%-36s %-12s %-6s %-22s %s" % ("host", "sensor", "status", "industry", "location"))
for r in sorted(prot, key=lambda x: ((x.get("sensor") or ""), x["host"])):
    print("%-36s %-12s %-6s %-22s %s" % (
        r["host"], r.get("sensor") or "-", r.get("status"),
        (r.get("industry") or "")[:22], (r.get("location") or "")[:26]))

print()
print("sensor kinds:", {k: sum(1 for r in prot if r.get("sensor") == k)
                         for k in ("obfuscated", "sensor", None)})

solves = []
for fn in ("solve_results.json", "solve2_results.json", "repeat_results.json"):
    path = os.path.join(RESULTS, fn)
    if os.path.exists(path):
        solves += json.load(open(path, encoding="utf-8"))

print()
print("%-34s %-10s %-5s %-8s %-8s %-5s %s" % (
    "host", "curl", "abck", "valid", "posts", "rechk", "note"))
for s in solves:
    host = s.get("host") or s.get("url", "").split("//")[-1].split("/")[0]
    curl = s.get("curl", s.get("run", ""))
    print("%-34s %-10s %-5s %-8s %-8s %-5s %s" % (
        host, curl, s.get("abck_status", "-"), s.get("validated", s.get("abck_validated", "-")),
        s.get("posts", "-"), s.get("recheck", s.get("recheck_status", "-")),
        s.get("solve_error", "")[:50]))
