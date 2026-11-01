# -*- coding: utf-8 -*-
"""Command line entry point: ``python -m gatekit <command>``.

    probe URL              one request, classify the response
    solve URL              run the shipped layers in cost order
    fetch URL [-o FILE]    open the gate, then GET the path and save the body
    inventory              five-bucket accounting over a sweep file

Every command accepts ``--proxy`` (omit it; direct is usually the right
answer) and prints JSON so it can be piped into ``jq``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlparse

from . import __version__
from .inventory import (
    build_snapshot,
    classify,
    diff_text,
    latest_snapshot,
    latest_sweep,
    load_snapshot,
    report,
    save_snapshot,
)
from .interstitial import detect, solve


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _cmd_probe(a) -> int:
    info = detect(a.url, proxy=a.proxy, impersonate=a.impersonate)
    _dump(info)
    return 0 if info.get("sensor") or info.get("status") else 1


def _cmd_solve(a) -> int:
    layers = tuple(x.strip() for x in a.layers.split(",") if x.strip())
    res = solve(a.url, proxy=a.proxy, layers=layers, impersonate=a.impersonate)
    _dump(res)
    return 0 if res.get("solved") else 1


def _cmd_fetch(a) -> int:
    from .client import InterstitialClient

    u = urlparse(a.url)
    if not u.netloc:
        sys.exit(f"not an absolute URL: {a.url}")
    base = f"{u.scheme or 'https'}://{u.netloc}"
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    c = InterstitialClient(base, proxy=a.proxy, impersonate=a.impersonate)
    gate = c.unlock(path)
    status, body = c.get(path)
    if a.out:
        with open(a.out, "w", encoding="utf-8", errors="replace") as f:
            f.write(body)
    _dump({"url": a.url, "gate": gate, "status": status, "len": len(body),
           "variant": c.variant, "stats": c.stats,
           "saved": a.out or None})
    return 0 if gate.get("ok") and status < 400 else 1


def _cmd_inventory(a) -> int:
    if a.diff:
        if len(a.diff) == 1:
            pa = a.diff[0]
            pb = latest_snapshot(exclude=pa, data_dir=a.data_dir)
            if not pb:
                sys.exit(f"only one snapshot ({pa}); run with --json auto first")
        elif len(a.diff) == 2:
            pa, pb = a.diff
        else:
            sys.exit("--diff takes one or two snapshot paths")
        for p in (pa, pb):
            if not os.path.exists(p):
                sys.exit(f"snapshot not found: {p}")
        print(diff_text(load_snapshot(pa), load_snapshot(pb), pa, pb))
        return 0

    sweep_path = latest_sweep(a.sweep, data_dir=a.data_dir)
    rows: list[dict] = []
    if sweep_path:
        with open(sweep_path, encoding="utf-8") as f:
            rows = [r for r in json.load(f) if isinstance(r, dict) and r.get("host")]

    print(report(rows, sweep_path))
    if a.md:
        snap = build_snapshot(rows, sweep_path)
        out = [f"# Gate inventory ({snap['ts']})", "",
               "| host | bucket | status | len | note |", "|---|---|---|---|---|"]
        for r in sorted(rows, key=classify):
            out.append(f"| {r['host']} | {classify(r)} | {r.get('status') or '-'} | "
                       f"{r.get('len') or 0} | {(r.get('err') or '')[:60]} |")
        with open(a.md, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        print(f"\n[md] {a.md}")

    if a.json_out:
        path = save_snapshot(build_snapshot(rows, sweep_path), a.json_out,
                             data_dir=a.data_dir)
        print(f"\n[snapshot] {path}")
        print(f"  next round: python -m gatekit inventory --diff {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="gatekit",
        description="Detect and solve Akamai interstitial challenges.")
    ap.add_argument("--version", action="version", version=f"gatekit {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--proxy", default=None,
                        help="http(s) proxy; omit for direct (recommended)")
    common.add_argument("--impersonate", default="chrome",
                        help="curl_cffi TLS fingerprint (default: chrome)")

    p = sub.add_parser("probe", parents=[common],
                       help="classify one response without solving")
    p.add_argument("url")
    p.set_defaults(func=_cmd_probe)

    p = sub.add_parser("solve", parents=[common],
                       help="run the shipped layers in cost order")
    p.add_argument("url")
    p.add_argument("--layers", default="L1,L2i",
                   help="comma separated: L1, L2i (default: L1,L2i)")
    p.set_defaults(func=_cmd_solve)

    p = sub.add_parser("fetch", parents=[common],
                       help="open the gate, then GET one path")
    p.add_argument("url")
    p.add_argument("-o", "--out", default=None, help="write the body here")
    p.set_defaults(func=_cmd_fetch)

    p = sub.add_parser("inventory", parents=[common],
                       help="five-bucket accounting over a sweep file")
    p.add_argument("--sweep", default=None,
                   help="sweep json (default: newest corpus_sweep*.json in data/)")
    p.add_argument("--data-dir", default=None,
                   help="where sweeps and snapshots live (default: ./data)")
    p.add_argument("--json", dest="json_out", default=None,
                   help="save a snapshot; 'auto' names it data/inventory_<ts>.json")
    p.add_argument("--md", default=None, help="also write a Markdown table")
    p.add_argument("--diff", nargs="+", metavar="SNAP",
                   help="diff two snapshots (one path: the other is the newest)")
    p.set_defaults(func=_cmd_inventory)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
