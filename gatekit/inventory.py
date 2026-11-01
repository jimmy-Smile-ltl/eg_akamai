# -*- coding: utf-8 -*-
"""Five-bucket accounting for a sweep of gated hosts.

The question this module answers is narrow and easy to get wrong:

    Of the hosts that were actually behind Akamai, how many did we get
    through the gate, and how many returned real content?

A plain ``ok / total`` ratio answers it wrong four different ways, so the
buckets are deliberate:

======  ===========================================================  ==============
bucket  meaning                                                      in denominator
======  ===========================================================  ==============
PASS    real content was returned                                    yes
GATE-ONLY  the gate opened but the origin had no content (401/503)   yes
FAIL    gate did not open (shell stayed, connection died)            yes
FRONT-WAF  another vendor (AWS WAF) answered -- not our problem      **no**
ENV-FLIP  Amazon-family DNS landed on CloudFront this round          **no**
======  ===========================================================  ==============

Excluding the last two is not score-keeping: a host that alternates between
Akamai and CloudFront at the DNS level will otherwise make the same corpus
report four different percentages.  Denominate on Akamai-native rows only.

Everything here is pure except the snapshot file helpers.  Input rows are
dicts shaped like the solver's result::

    {"host": "www.example.com", "status": 200, "len": 51234,
     "ok": true, "gate": "passed", "err": "", "vendor": {"vendor": "akamai"}}
"""
from __future__ import annotations

import glob
import json
import os
import time
from collections import Counter
from pathlib import Path

MIN_SWEEP_ROWS = 20   # a smaller file is a smoke run, not "current corpus state"

BUCKETS = ("PASS", "GATE-ONLY", "FRONT-WAF", "ENV-FLIP", "FAIL")


def _data_dir(data_dir: str | os.PathLike | None) -> Path:
    if data_dir:
        return Path(data_dir)
    env = os.environ.get("GATEKIT_DATA")
    return Path(env) if env else Path.cwd() / "data"


def _row_count(path: str | os.PathLike) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        return len([r for r in rows if isinstance(r, dict) and r.get("host")])
    except Exception:  # noqa: BLE001
        return 0


def latest_sweep(explicit: str | None = None,
                 data_dir: str | os.PathLike | None = None,
                 min_rows: int = MIN_SWEEP_ROWS) -> str | None:
    """Newest ``corpus_sweep*.json`` with at least *min_rows* rows.

    Taking the newest file by mtime alone is a trap: a three-host smoke run
    then becomes "the corpus" and the headline number silently changes.
    """
    if explicit:
        return explicit if os.path.exists(explicit) else None
    files = glob.glob(str(_data_dir(data_dir) / "corpus_sweep*.json"))
    files = [f for f in files if "_vendor" not in f] or files
    files.sort(key=os.path.getmtime, reverse=True)
    for f in files:
        if _row_count(f) >= min_rows:
            return f
    return files[0] if files else None


def classify(r: dict) -> str:
    """Map one sweep row to a bucket.  Vendor triage beats status heuristics."""
    if r.get("ok"):
        return "PASS"
    v = (r.get("vendor") or {}).get("vendor")
    if v == "aws-waf":
        return "FRONT-WAF"
    if v == "akamai":
        # The row's own probe says Akamai, yet this round saw a CloudFront 202:
        # that is the Amazon-family DNS flip, not a solver failure.
        return "ENV-FLIP"
    if r.get("gate") == "passed":
        return "GATE-ONLY"
    err = r.get("err") or ""
    if (r.get("status") == 202 and (r.get("len") or 0) < 4000) or "CloudFront" in err:
        return "FRONT-WAF"
    return "FAIL"


def build_snapshot(rows: list[dict], sweep_path: str | None = None,
                   ts: str | None = None) -> dict:
    """Compress a round to the smallest structure two rounds can be diffed on."""
    cls = Counter(classify(r) for r in rows)
    n = len(rows)
    flips = cls["ENV-FLIP"]
    akamai = n - cls["FRONT-WAF"] - flips
    gate = cls["PASS"] + cls["GATE-ONLY"]

    def pct(a: int) -> float:
        return round(100.0 * a / akamai, 1) if akamai else 0.0

    sweep_ts = ""
    if sweep_path and os.path.exists(sweep_path):
        sweep_ts = time.strftime("%Y-%m-%d %H:%M",
                                 time.localtime(os.path.getmtime(sweep_path)))
    return {
        "ts": ts or time.strftime("%Y-%m-%d %H:%M"),
        "sweep": sweep_path or "",
        "sweep_ts": sweep_ts,
        "totals": {"rows": n, "akamai": akamai, "pass": cls["PASS"],
                   "gate_only": cls["GATE-ONLY"], "front_waf": cls["FRONT-WAF"],
                   "env_flip": flips, "fail": cls["FAIL"],
                   "gate": gate, "gate_rate": pct(gate),
                   "content_rate": pct(cls["PASS"])},
        "rows": [{"host": r["host"], "cls": classify(r),
                  "status": r.get("status"), "len": r.get("len") or 0,
                  "err": (r.get("err") or "")[:80]}
                 for r in rows],
    }


# ---------------------------------------------------------------- snapshots
def save_snapshot(snap: dict, path: str = "auto",
                  data_dir: str | os.PathLike | None = None) -> str:
    """Write *snap*.  ``auto`` (or ``-``) names it ``data/inventory_<ts>.json``."""
    if path in ("auto", "-"):
        d = _data_dir(data_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = str(d / time.strftime("inventory_%Y%m%d_%H%M.json"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    return path


def latest_snapshot(exclude: str = "",
                    data_dir: str | os.PathLike | None = None) -> str | None:
    files = [f for f in glob.glob(str(_data_dir(data_dir) / "inventory_*.json"))
             if os.path.abspath(f) != os.path.abspath(exclude or "")]
    return max(files, key=os.path.getmtime) if files else None


def load_snapshot(path: str | os.PathLike) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compare(a: dict, b: dict) -> dict:
    """Pure diff of two snapshots.

    Three outcomes, deliberately not "improved / regressed":

    ``good``   x -> PASS       content newly obtained (GATE-ONLY -> PASS counts)
    ``bad``    PASS -> non-PASS content lost
    ``other``  any other move  FRONT-WAF <-> ENV-FLIP is a triage change, not
                               a capability change; calling it a regression
                               sends you hunting for a bug that is not there.
    """
    A = {r["host"]: r for r in a["rows"]}
    B = {r["host"]: r for r in b["rows"]}
    moved = [(h, A[h]["cls"], B[h]["cls"]) for h in sorted(set(A) & set(B))
             if A[h]["cls"] != B[h]["cls"]]
    good = [(h, x, y) for h, x, y in moved if y == "PASS" and x != "PASS"]
    bad = [(h, x, y) for h, x, y in moved if x == "PASS" and y != "PASS"]
    other = [m for m in moved if m not in good and m not in bad]
    return {"added": sorted(set(B) - set(A)), "gone": sorted(set(A) - set(B)),
            "good": good, "bad": bad, "other": other, "rows_b": B}


# ---------------------------------------------------------------- rendering
def report(rows: list[dict], sweep_path: str | None = None,
           regress_count: int = 0) -> str:
    """Human-readable summary of one round (the number you quote)."""
    snap = build_snapshot(rows, sweep_path)
    t = snap["totals"]
    n, akamai = t["rows"], t["akamai"]
    lines = [f"[sweep] {sweep_path or '(none)'}"]
    if sweep_path and n < MIN_SWEEP_ROWS:
        lines.append(f"  ! only {n} rows (< {MIN_SWEEP_ROWS}) -- smoke run, "
                     f"do not quote as corpus state")
    flip_note = f" / DNS flip {t['env_flip']} (probe saw Akamai, re-run)" \
        if t["env_flip"] else ""
    lines.append(f"  gated hosts {n}: Akamai-native {akamai} / "
                 f"front AWS WAF {t['front_waf']}{flip_note}")
    lines.append(f"  Akamai-native {akamai} -> content PASS {t['pass']} / "
                 f"gate-only {t['gate_only']} / fail {t['fail']}")
    lines.append(f"  gate {t['gate']}/{akamai} = {t['gate_rate']}%"
                 f"   content {t['pass']}/{akamai} = {t['content_rate']}%")
    if regress_count:
        lines.append(f"[regress] {regress_count} hosts held on every run")

    non_pass = [r for r in rows if classify(r) != "PASS"]
    if non_pass:
        lines.append("")
        lines.append("[non-PASS]")
        for r in non_pass:
            lines.append(f"  {classify(r):10} {r['host'][:34]:34} "
                         f"status={str(r.get('status')):5} "
                         f"len={r.get('len', 0):>8} {(r.get('err') or '')[:52]}")
    return "\n".join(lines)


def diff_text(a: dict, b: dict, path_a: str = "", path_b: str = "") -> str:
    """Human-readable diff of two snapshots."""
    ta, tb = a["totals"], b["totals"]
    out = [f"[diff] {os.path.basename(path_a) or a.get('ts')}  ->  "
           f"{os.path.basename(path_b) or b.get('ts')}",
           f"  generated {a.get('ts')} -> {b.get('ts')}"
           f"    sweep {a.get('sweep_ts') or '-'} -> {b.get('sweep_ts') or '-'}",
           f"  denom Akamai-native {ta['akamai']} -> {tb['akamai']}"
           + ("    [!] denominator changed, percentages are not comparable"
              if ta["akamai"] != tb["akamai"] else ""),
           f"  gate    {ta['gate']}/{ta['akamai']} = {ta['gate_rate']}%  ->  "
           f"{tb['gate']}/{tb['akamai']} = {tb['gate_rate']}%",
           f"  content {ta['pass']}/{ta['akamai']} = {ta['content_rate']}%  ->  "
           f"{tb['pass']}/{tb['akamai']} = {tb['content_rate']}%"]

    d = compare(a, b)
    added, gone = d["added"], d["gone"]
    good, bad, other, B = d["good"], d["bad"], d["other"], d["rows_b"]
    if added:
        out.append(f"\n  [added {len(added)}] " + ", ".join(added[:20])
                   + (" ..." if len(added) > 20 else ""))
    if gone:
        out.append(f"\n  [gone {len(gone)}] " + ", ".join(gone[:20])
                   + (" ..." if len(gone) > 20 else ""))
    if not (good or bad or other):
        out.append("\n  bucket changes: none (same hosts, same verdicts)")
        return "\n".join(out)

    out.append(f"\n  bucket changes {len(good) + len(bad) + len(other)}:")
    if good:
        out.append(f"  + content gained {len(good)}: "
                   + " ".join(f"{h}({x}->PASS)" for h, x, _ in good[:20]))
    if bad:
        out.append(f"  - content lost {len(bad)}: "
                   + " ".join(f"{h}(PASS->{y})" for h, _, y in bad[:20]))
    if other:
        out.append(f"  ~ other {len(other)}: "
                   + " ".join(f"{h}({x}->{y})" for h, x, y in other[:20]))
    if bad:
        out.append("\n  check err on regressions first: an Amazon-family 202 is a "
                   "DNS flip, not a solver failure.")
        for h, x, y in bad[:10]:
            e = B[h].get("err") or ""
            out.append(f"    {h:34} {x}->{y}  status={B[h].get('status')} "
                       f"len={B[h].get('len')}  {e}")
    return "\n".join(out)
