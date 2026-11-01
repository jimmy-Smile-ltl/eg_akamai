# -*- coding: utf-8 -*-
"""Offline regression for the judgment layer and the accounting rules.

No network, no cookies, no clock.  Everything here is decided from the
fixtures in ``data/fixtures/`` plus a few inline strings.

Why this file exists: before it, every rule was validated only by running
real sites.  Changing one threshold meant a 100-host manual sweep to notice
that a genuine 17 KB home page had been rejected, or that the 6 KB scan
window missed a 6.9 KB shell.  Those two bugs are cases 4 and 10 below.

Coverage
--------
judges.py     is_interstitial / parse_interstitial / content_like /
              path_entropy / looks_classic / classify_sensor / shell_path /
              cookie_domain_mismatch / canonical_remap
inventory.py  classify (five buckets) / build_snapshot / compare /
              latest_sweep (smoke-run guard) / report

Not covered: anything that opens a socket.  Real-site regression is a
separate, slower layer and is not shipped here.

Usage
-----
    py -3.12 tests/test_offline.py
    py -3.12 tests/test_offline.py -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from gatekit import judges as J        # noqa: E402
from gatekit import inventory as inv   # noqa: E402

REAL = os.path.join(ROOT, "data", "fixtures", "real")
SYNTH = os.path.join(ROOT, "data", "fixtures", "synthetic")
SAMPLE_SWEEP = os.path.join(ROOT, "examples", "sample_sweep.json")
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

CASES: list[tuple[str, object]] = []


def case(desc):
    def deco(fn):
        CASES.append((desc, fn))
        return fn
    return deco


def read(path: str) -> str:
    with io.open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def real(name: str) -> str:
    return read(os.path.join(REAL, name))


def synth(name: str) -> str:
    return read(os.path.join(SYNTH, name))


def eq(actual, expected, what=""):
    assert actual == expected, f"{what}: expected {expected!r}, got {actual!r}"


def needle(hay, sub, what=""):
    assert sub in hay, f"{what}: expected to find {sub!r} in {hay!r}"


class FakeResp:
    """A response stub carrying only headers (cookie rules read nothing else)."""

    def __init__(self, set_cookie: str = ""):
        self.headers = {"set-cookie": set_cookie} if set_cookie else {}


SHELLS = ["zara_shell.html", "flaticon_shell.html", "nh_hotels_shell.html"]
# Real responses that are *not* interstitial shells: another vendor's block
# page, a CloudFront draw, a classic-sensor crypto page, and real content.
NOT_SHELLS = ["wurth_classic_challenge.html", "amazon_cloudfront_202.html",
              "trustpilot_block.html", "zara_search_excerpt.html"]


# ---------------------------------------------------------------- shell judge
@case("is_interstitial: three real shells are positive")
def t_is_interstitial_positive():
    for n in SHELLS:
        eq(J.is_interstitial(real(n)), True, n)


@case("is_interstitial: block pages / CloudFront / content are negative")
def t_is_interstitial_negative():
    for n in NOT_SHELLS:
        eq(J.is_interstitial(real(n)), False, n)


@case("is_interstitial: empty body and None do not raise")
def t_is_interstitial_empty():
    eq(J.is_interstitial(""), False, "empty")
    eq(J.is_interstitial(None), False, "None")


@case("is_interstitial: 40 KB window (flaticon puts _sec/verify at ~6.1 KB)")
def t_is_interstitial_window():
    shell = real("flaticon_shell.html")
    off = shell.find("_sec/verify")
    assert 6000 < off < 7000, f"fixture should place _sec/verify just past 6 KB, got {off}"
    eq(J.is_interstitial(shell[:6000]), False,
       "the old 6 KB window missed this shell")
    eq(J.is_interstitial(shell), True, "40 KB window catches it")
    padded = "<html><body>" + ("x" * 50000) + shell
    eq(J.is_interstitial(padded), False, "a shell pushed past 40 KB is out of scope")


# ---------------------------------------------------------------- parsing
@case("parse_interstitial: zara token / pow / endpoint")
def t_parse_zara():
    ch = J.parse_interstitial(real("zara_shell.html"))
    assert ch, "zara shell should parse"
    eq(len(ch["bm_verify"]), 268, "token length")
    eq(ch["pow"], 2272089155, "pow = 1793514655 + 478574500")
    eq(ch["endpoint"], "/_sec/verify?provider=interstitial", "endpoint")


@case("parse_interstitial: flaticon (Magnific layer, 6.9 KB shell)")
def t_parse_flaticon():
    ch = J.parse_interstitial(real("flaticon_shell.html"))
    assert ch, "flaticon shell should parse"
    eq(len(ch["bm_verify"]), 308, "token length")
    eq(ch["pow"], 2751614010, "pow = 1793514656 + 958099354")


@case("parse_interstitial: meta-refresh-only form")
def t_parse_meta_only():
    html = ('<meta http-equiv="refresh" '
            'content="5; URL=\'/x?bm-verify=AB_CD-1234567890abcdefgh\'" />')
    ch = J.parse_interstitial(html)
    assert ch, "meta form should parse"
    eq(ch["bm_verify"], "AB_CD-1234567890abcdefgh", "URL-safe token")
    eq(ch["pow"], None, "no arithmetic => pow is None")
    eq(ch["endpoint"], "/_sec/verify?provider=interstitial", "fallback endpoint")


@case("parse_interstitial: endpoint comes from xhr.open and gains provider")
def t_parse_endpoint():
    html = ('<script>xhr.open("POST", "/custom/verify", false);</script>'
            '<script>xhr.send(JSON.stringify({"bm-verify": "AAAA////BBBB", "pow": 1}));</script>')
    ch = J.parse_interstitial(html)
    assert ch, "should parse"
    eq(ch["endpoint"], "/custom/verify?provider=interstitial", "provider appended")
    html2 = html.replace("/custom/verify", "/v?provider=interstitial")
    eq(J.parse_interstitial(html2)["endpoint"], "/v?provider=interstitial",
       "must not append provider twice")


@case("parse_interstitial: no token returns None instead of raising")
def t_parse_garbage():
    eq(J.parse_interstitial("<html><body>hello</body></html>"), None, "plain page")
    eq(J.parse_interstitial(""), None, "empty")


# ---------------------------------------------------------------- content judge
@case("content_like: real pages are positive")
def t_content_positive():
    eq(J.content_like(real("zara_search_excerpt.html")), True, "60 KB excerpt")
    eq(J.content_like(synth("content_large.html")), True, "60 KB synthetic page")


@case("content_like: a 4.7 KB page with a title and dense text is content")
def t_content_small_real():
    body = synth("content_small.html")
    assert len(body) < J.CONTENT_MIN, "this case exists to exercise the small-page path"
    eq(J.content_like(body), True, "small page must not be rejected by length alone")


@case("content_like: shells are never content")
def t_content_shell():
    for n in SHELLS:
        eq(J.content_like(real(n)), False, n)


@case("content_like: other vendors' block pages are never content")
def t_content_block_marks():
    eq(J.content_like(real("wurth_classic_challenge.html")), False, "crypto PoW page")
    eq(J.content_like(real("amazon_cloudfront_202.html")), False, "CloudFront 202")
    eq(J.content_like(real("trustpilot_block.html")), False, "other WAF block page")
    for mark in ("Access Denied", "Pardon Our Interruption", "Just a moment",
                 "verify you are human", "captcha-delivery.com", "px-captcha"):
        body = f"<html><head><title>x</title></head><body>{mark}</body></html>"
        eq(J.content_like(body), False, mark)


@case("content_like: small page without a title, or with thin text, is negative")
def t_content_small_no_title():
    body = "<html><body>" + "<p>hello world</p>" * 75 + "</body></html>"
    eq(J.content_like(body), False, "no title")
    thin = "<html><head><title>ok</title></head><body>hi</body></html>"
    eq(J.content_like(thin), False, "too little visible text")


# ---------------------------------------------------------------- sensor paths
@case("path_entropy: only mixed-case base64url segments count")
def t_path_entropy():
    eq(J.path_entropy("mspJveYdjdvzTw6EVw"), True, "real sensor segment")
    eq(J.path_entropy("cricket-events"), False, "lowercase words")
    eq(J.path_entropy("abcdefghij"), False, "all lowercase")
    eq(J.path_entropy("1234567890"), False, "digits only")
    eq(J.path_entropy("Ab1"), False, "too short")


@case("looks_classic: sensor path positive, the page's own deep URL negative")
def t_looks_classic():
    eq(J.looks_classic("/NSUGd/DtH52/bQtobg/q-QV/6t/ch4KAWsB/bxAk/CXIyACwt", "/"),
       True, "wurth's 8-segment sensor path")
    eq(J.looks_classic("/on-this-day/cricket-events/october/31",
                       "/on-this-day/cricket-events/october/31"), False,
       "same as page_path")
    eq(J.looks_classic("/narration/player/33850183/abc", "/"), False, "no random segment")
    eq(J.looks_classic("/akam/13/abc", "/"), False, "/akam/ is never classic")
    eq(J.looks_classic("https://e.com/a/BcDefGh/IjKlMnOp", "/"), False, "absolute URL")
    eq(J.looks_classic("/a/b/c", "/"), False, "too few segments")


@case("classify_sensor: shell -> interstitial (locked + challenge)")
def t_classify_interstitial():
    d = J.classify_sensor(real("zara_shell.html"), "/")
    eq(d["sensor"], "interstitial", "sensor")
    eq(d.get("locked"), True, "locked")
    eq(d["challenge"]["token_len"], 268, "token length")
    eq(d["challenge"]["pow"], 2272089155, "pow")
    needle(d["evidence"], "interstitial_shell", "evidence")


@case("classify_sensor: wurth's crypto PoW page -> challenge_crypto, 202 -> None")
def t_classify_other():
    d = J.classify_sensor(real("wurth_classic_challenge.html"), "/")
    eq(d["sensor"], "challenge_crypto", "Akamai Challenge Validation (provider=crypto)")
    needle(d["evidence"], "akamai_challenge_iframe", "evidence")
    eq(J.classify_sensor(real("amazon_cloudfront_202.html"), "/")["sensor"],
       None, "202 body")


@case("classify_sensor: content with /akam/ -> compact_v3 but not locked")
def t_classify_compact():
    for body in (synth("compact_page.html"), real("zara_search_excerpt.html")):
        d = J.classify_sensor(body, "/")
        eq(d["sensor"], "compact_v3", "Akamai injects a sensor into normal pages")
        eq(d.get("locked"), None, "not locked")


@case("classify_sensor: denial and rate-limit evidence markers")
def t_classify_evidence():
    denied = ("<html><body><h1>Access Denied</h1>"
              "Reference #18.abcd1234.1700000000</body></html>")
    needle(J.classify_sensor(denied, "/")["evidence"], "akamai_denied_page", "denial")
    rl = "<html><body>Provisioned request rate has been exceeded</body></html>"
    needle(J.classify_sensor(rl, "/")["evidence"], "akamai_rate_limit", "rate limit")
    eq(J.classify_sensor("", "/"), {"sensor": None, "evidence": []}, "empty body")


# ---------------------------------------------------------------- canonical domain
@case("shell_path: read the locale prefix from meta refresh")
def t_shell_path():
    eq(J.shell_path(real("zara_shell.html")), "/", "zara points back to root")
    eq(J.shell_path(real("nh_hotels_shell.html")), "/en", "nh-hotels locale prefix")
    html = ('<meta http-equiv="refresh" content="5; URL=\'https://www.example.com/it/\'" />')
    eq(J.shell_path(html), "/it/", "absolute URL still yields a path")
    eq(J.shell_path("<html>no refresh</html>"), None, "no meta")


@case("cookie_domain_mismatch: 'POST succeeded but the cookie cannot be stored'")
def t_cookie_domain():
    r = FakeResp("ak_bmsc=abc; Domain=.bike24.com; Path=/; HttpOnly")
    eq(J.cookie_domain_mismatch(r, "www.bike24.net"), "bike24.com", "mismatch")
    eq(J.cookie_domain_mismatch(FakeResp("ak_bmsc=abc; Domain=.bike24.net"),
                                "www.bike24.net"), None, "match")
    eq(J.cookie_domain_mismatch(FakeResp("ak_bmsc=abc"), "www.bike24.net"), None,
       "no Domain attribute")


@case("canonical_remap: ccTLD alias -> canonical host + locale prefix")
def t_canonical():
    html = '<meta http-equiv="refresh" content="5; URL=\'/it/\'" />'
    r = FakeResp("ak_bmsc=abc; Domain=.zara.com; Path=/")
    eq(J.canonical_remap("https://www.zara.it/", html, r)[0],
       "https://www.zara.com/it/", "server-stated Domain comes first")
    cands = J.canonical_remap("https://www.nh-hotels.de/", "<html>no refresh</html>", None)
    needle(cands, "https://www.nh-hotels.com/", "ccTLD -> .com")


@case("canonical_remap: never returns the current host (no self-loop)")
def t_canonical_self():
    r = FakeResp("ak_bmsc=abc; Domain=.zara.com")
    for u in ("https://www.zara.com/", "https://www.zara.it/"):
        assert u not in J.canonical_remap(u, "<html></html>", r), u


# ---------------------------------------------------------------- accounting
@case("inventory.classify: five buckets, vendor triage before status codes")
def t_inv_classify():
    eq(inv.classify({"ok": True}), "PASS", "content")
    eq(inv.classify({"vendor": {"vendor": "aws-waf"}}), "FRONT-WAF", "other vendor")
    eq(inv.classify({"vendor": {"vendor": "akamai"}}), "ENV-FLIP", "DNS flip")
    eq(inv.classify({"gate": "passed"}), "GATE-ONLY", "gate opened, origin empty")
    eq(inv.classify({"status": 202, "len": 2012}), "FRONT-WAF", "bare 202")
    eq(inv.classify({"err": "curl(28)"}), "FAIL", "everything else")


@case("denominator: the 24-row sample sweep gives 20 / 20 / 17")
def t_inv_sample_sweep():
    with io.open(SAMPLE_SWEEP, encoding="utf-8") as f:
        rows = [r for r in json.load(f) if isinstance(r, dict) and r.get("host")]
    from collections import Counter
    c = Counter(inv.classify(r) for r in rows)
    n = len(rows)
    akamai = n - c["FRONT-WAF"] - c["ENV-FLIP"]
    eq(n, 24, "rows")
    eq(c["FRONT-WAF"], 2, "front AWS WAF")
    eq(c["ENV-FLIP"], 2, "DNS flip")
    eq(akamai, 20, "Akamai-native (the denominator)")
    eq(c["PASS"] + c["GATE-ONLY"], 20, "gate passed")
    eq(c["PASS"], 17, "content")

    snap = inv.build_snapshot(rows, SAMPLE_SWEEP)
    t = snap["totals"]
    eq(t["gate_rate"], 100.0, "gate rate")
    eq(t["content_rate"], 85.0, "content rate")


@case("denominator: the Amazon family is excluded, otherwise one corpus gives four numbers")
def t_inv_amazon_excluded():
    rows = [{"host": "www.amazon.co.uk", "status": 202, "len": 2012},
            {"host": "www.amazon.co.jp", "vendor": {"vendor": "akamai"}, "ok": True},
            {"host": "www.zara.com", "ok": True}]
    from collections import Counter
    c = Counter(inv.classify(r) for r in rows)
    eq(c["PASS"], 2, "two PASS (one flipped back)")
    eq(c["FRONT-WAF"], 1, "front AWS WAF")
    eq(len(rows) - c["FRONT-WAF"], 2, "denominator after exclusion")


@case("snapshots: build totals + compare good/bad symmetry")
def t_snapshot_diff():
    rows = [{"host": "a.com", "ok": True},
            {"host": "b.com", "gate": "passed"},
            {"host": "c.com", "status": 202, "len": 2012}]
    s1 = inv.build_snapshot(rows, None)
    eq(s1["totals"]["akamai"], 2, "denominator excludes one front WAF")
    eq(s1["totals"]["gate"], 2, "gate = PASS + GATE-ONLY")
    eq(s1["totals"]["gate_rate"], 100.0, "gate rate")
    eq(s1["totals"]["content_rate"], 50.0, "content rate")

    rows2 = [{"host": "a.com", "ok": True},
             {"host": "b.com", "ok": True},   # GATE-ONLY -> PASS
             {"host": "c.com", "ok": True}]   # FRONT-WAF -> PASS
    s2 = inv.build_snapshot(rows2, None)
    d = inv.compare(s1, s2)
    eq([h for h, _, _ in d["good"]], ["b.com", "c.com"], "content gained")
    eq(d["bad"], [], "no regression")
    d2 = inv.compare(s2, s1)
    eq([h for h, _, _ in d2["bad"]], ["b.com", "c.com"], "reverse is regression")
    eq(d2["good"], [], "no good in reverse")
    eq(d["added"], [], "same host set")
    eq(d["gone"], [], "same host set")


@case("latest_sweep: a 3-row smoke run must not replace the corpus")
def t_latest_sweep_not_smoke():
    with tempfile.TemporaryDirectory() as d:
        big = os.path.join(d, "corpus_sweep_big.json")
        small = os.path.join(d, "corpus_sweep_small.json")
        with io.open(big, "w", encoding="utf-8") as f:
            json.dump([{"host": f"h{i}.example"} for i in range(inv.MIN_SWEEP_ROWS)], f)
        with io.open(small, "w", encoding="utf-8") as f:
            json.dump([{"host": f"s{i}.example"} for i in range(3)], f)
        now = time.time()
        os.utime(big, (now - 600, now - 600))   # older
        os.utime(small, (now, now))             # newer, but only 3 rows
        eq(inv.latest_sweep(None, data_dir=d), big, "skips the smoke run")
        eq(inv.latest_sweep(small, data_dir=d), small, "explicit --sweep is respected")


@case("report / diff_text: the headline numbers and the regression note appear")
def t_render():
    with io.open(SAMPLE_SWEEP, encoding="utf-8") as f:
        rows = [r for r in json.load(f) if isinstance(r, dict) and r.get("host")]
    text = inv.report(rows, SAMPLE_SWEEP)
    needle(text, "gate 20/20 = 100.0%", "gate line")
    needle(text, "content 17/20 = 85.0%", "content line")

    s1 = inv.build_snapshot([{"host": "a.com", "ok": True}], None)
    s2 = inv.build_snapshot([{"host": "a.com", "gate": "passed"}], None)
    needle(inv.diff_text(s1, s2), "content lost 1", "regression line")


# ---------------------------------------------------------------- runner
def main() -> int:
    failed = 0
    width = max(len(d) for d, _ in CASES)
    for desc, fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {desc}")
            print(f"        {e}")
            if VERBOSE:
                traceback.print_exc()
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {desc}")
            traceback.print_exc()
        else:
            if VERBOSE:
                print(f"  ok    {desc:<{width}}")
    total = len(CASES)
    print(f"\n{'=' * 60}\noffline: {total - failed}/{total} passed"
          + (f", {failed} failed" if failed else ", all green"))
    if failed:
        print("Rules changed? start here before touching a real site.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
