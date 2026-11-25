"""Merge every results/*.json into results/results_all.csv and print the summary.

Usage: python wre/scripts/make_report_data.py
"""

import csv
import io
import json
import os

from _paths import RESULTS


def load(fn):
    path = os.path.join(RESULTS, fn)
    if not os.path.exists(path):
        return []
    return json.load(io.open(path, encoding="utf-8"))


screen = load("screen_results.json") + load("screen2_results.json")
solves = load("solve_results.json") + load("solve2_results.json")
repeats = load("repeat_results.json") + load("repeat2_results.json")

solve_map = {}
for s in solves:
    host = s.get("host")
    if not host:
        continue
    # 有 curl 对照的记录（solve2）优先，避免被旧批次覆盖
    if "curl" in s or host not in solve_map:
        solve_map[host] = s

uniq = {}
for r in screen:
    uniq[r["host"]] = r

rows = []
for host, r in uniq.items():
    s = solve_map.get(host, {})
    abck = s.get("abck_status")
    recheck = s.get("recheck", s.get("recheck_status"))
    err = s.get("solve_error") or s.get("recheck_error") or s.get("open_error")
    if not s:
        verdict = "screened"
    elif err:
        verdict = "failed"
    elif abck == "0" and s.get("validated"):
        verdict = "validated"
    elif abck == "-1":
        verdict = "unvalidated"
    else:
        verdict = "failed"
    curl = s.get("curl", "")
    inc = ""
    if curl.startswith("403") and recheck == 200:
        inc = "403->200"
    elif curl.startswith("000") and recheck == 200:
        inc = "000->200"
    rows.append({
        "host": host,
        "url": r.get("url", ""),
        "industry": r.get("industry", ""),
        "location": r.get("location", ""),
        "screen_status": r.get("status", ""),
        "protected": r.get("protected", ""),
        "sensor": r.get("sensor") or "",
        "curl": curl,
        "abck": abck or "",
        "validated": s.get("validated", ""),
        "posts": s.get("posts", ""),
        "solve_secs": s.get("solve_secs", ""),
        "recheck": recheck if recheck is not None else "",
        "increment": inc,
        "verdict": verdict,
        "note": (err or s.get("title") or "")[:120],
    })

rows.sort(key=lambda x: (x["verdict"] != "validated", x["verdict"] != "unvalidated",
                         x["verdict"] != "failed", x["host"]))
with open(os.path.join(RESULTS, "results_all.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

total = len(rows)
prot = sum(1 for r in rows if r["protected"] is True)
valid = sum(1 for r in rows if r["verdict"] == "validated")
unval = sum(1 for r in rows if r["verdict"] == "unvalidated")
fail = sum(1 for r in rows if r["verdict"] == "failed")
inc403 = sum(1 for r in rows if r["increment"] == "403->200")
inc000 = sum(1 for r in rows if r["increment"] == "000->200")
print("rows: %d" % total)
print("protected: %d" % prot)
print("validated: %d  unvalidated: %d  failed: %d  screened-only: %d" % (
    valid, unval, fail, total - prot))
print("increment 403->200: %d   000->200: %d" % (inc403, inc000))
print("written results/results_all.csv")
