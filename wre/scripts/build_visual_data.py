"""Rebuild report_data.js (the 268-row ledger behind report.html) from results_all.csv.

Usage: python wre/scripts/build_visual_data.py
"""

import csv
import io
import json
import os

from _paths import RESULTS, VISUAL_DATA

rows = []
with io.open(os.path.join(RESULTS, "results_all.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        curl = (r["curl"] or "").split(" ")[0]
        rows.append({
            "h": r["host"],
            "i": (r["industry"] or "")[:40],
            "l": (r["location"] or "")[:30],
            "c": curl,
            "a": r["abck"],
            "r": "" if r["recheck"] == "" else str(r["recheck"]),
            "v": r["verdict"],
            "p": 1 if r["protected"] == "True" else 0,
            "s": r["sensor"],
            "n": r["increment"],
        })

with io.open(VISUAL_DATA, "w", encoding="utf-8") as f:
    f.write("window.LEDGER=")
    json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")

print("wrote report_data.js (%d rows)" % len(rows))
