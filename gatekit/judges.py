# -*- coding: utf-8 -*-
"""Pure judgments for Akamai interstitial challenges.

Every function in this module is side-effect free: it takes a response body
(or a tiny response-like object) and returns a decision.  No network, no
cookies, no filesystem.  That is deliberate -- these are the rules that are
easiest to break and the cheapest to test.

The public names are used by :mod:`gatekit.interstitial`,
:mod:`gatekit.client` and the offline suite in ``tests/test_offline.py``.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# A response shorter than this is only "content" when it also looks like a
# real document (title + visible text).  The old rule was ``len > 20000``;
# that misclassified small but genuine home pages.
CONTENT_MIN = 20000

# Markers of other vendors' block/challenge pages.  ``content_like`` must not
# count these as content even when the body is large.
BLOCK_MARKS = (
    "access denied", "reference #", "request unsuccessful",
    "attention required", "just a moment", "are you a robot",
    "pardon our interruption", "verify you are human",
    "enable javascript and cookies to continue", "request blocked",
    "captcha-delivery.com", "px-captcha",
)

# Cookies that indicate Bot Manager is deployed on a path.  Seeing one is a
# lossless probe: it does not trigger a challenge.
BM_COOKIES = ("_abck", "bm_sz", "ak_bmsc", "bm_sv", "bm_mi")


def is_interstitial(body: str | None) -> bool:
    """Return True when *body* is an Akamai interstitial **shell**.

    A shell is what you get instead of content.  It is ~2-7 KB, HTTP 200,
    and contains a one-shot ``bm-verify`` token plus a POST to
    ``/_sec/verify``.  The status code is identical to a normal page, so the
    body is the only reliable signal.

    Only the first 40 KB are inspected.  A real page can be megabytes and
    may mention the word ``bm-verify`` further down; scanning the whole body
    would create false positives.  The window is 40 KB rather than 6 KB
    because some shells (the Magnific layer) put ``_sec/verify`` at byte
    ~6.1 KB.
    """
    if not body:
        return False
    head = body[:40960]
    return "bm-verify" in head and ("_sec/verify" in head or "interstitial" in head)


def parse_interstitial(html: str) -> dict | None:
    """Extract ``bm_verify`` / ``pow`` / ``endpoint`` from a shell.

    Returns ``None`` when no token is present.  The token appears in two
    places in a real shell:

    * the JSON body sent by the page's synchronous XHR (standard base64);
    * the ``meta refresh`` URL (URL-safe base64).

    We prefer the JSON form and fall back to the query parameter.  ``pow`` is
    an arithmetic expression of the form ``var i = <digits>; var j = i +
    Number("a" + "b")``; if it is absent the field is ``None`` (some variants
    never check it).
    """
    m_tok = re.search(r'"bm-verify"\s*:\s*"([^"]+)"', html)
    if not m_tok:                              # fallback: meta refresh query
        m_tok = re.search(r"bm-verify=([A-Za-z0-9_\-+/=%]{16,})", html)
    if not m_tok:
        return None
    tok = m_tok.group(1).split("&")[0]

    # Submission endpoint: prefer the page's own xhr.open(), otherwise the
    # conventional path.  ``provider=interstitial`` is mandatory.
    m_ep = re.search(r"""open\(\s*["']POST["']\s*,\s*["']([^"']+)["']""", html)
    endpoint = m_ep.group(1) if m_ep else "/_sec/verify?provider=interstitial"
    if not re.search(r"provider=", endpoint):
        endpoint += ("&" if "?" in endpoint else "?") + "provider=interstitial"

    m_i = re.search(r"var\s+i\s*=\s*(\d+)", html)
    m_add = re.search(r'Number\(\s*"(\d*)"\s*\+\s*"(\d*)"\s*\)', html)
    pow_v = None
    if m_i and m_add:
        pow_v = int(m_i.group(1)) + int(m_add.group(1) + m_add.group(2))
    return {"bm_verify": tok, "pow": pow_v, "endpoint": endpoint}


def content_like(body: str | None) -> bool:
    """Return True when *body* looks like a real document rather than a gate.

    Rules, in order:

    1. an interstitial shell is never content;
    2. another vendor's block page is never content;
    3. bodies > 20 KB are content;
    4. smaller bodies need a ``<title>`` and more than 800 characters of
       visible text after scripts/styles/tags are removed.

    Rule 4 exists because a 17 KB genuine home page was once rejected by a
    pure length threshold.  Rule 3 keeps large SPA shells working.
    """
    if not body or is_interstitial(body):
        return False
    low = body[:40000].lower()
    if any(k in low for k in BLOCK_MARKS):
        return False
    if len(body) > CONTENT_MIN:
        return True
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    title = (m.group(1) if m else "").strip()
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return bool(title) and len(text) > 800


def path_entropy(seg: str) -> bool:
    """Heuristic: is *seg* a random base64url segment?

    Classic sensors use mixed-case random strings (``mspJveYdjdvzTw6EVw``).
    Ordinary URL segments are words (``cricket-events``, ``october``) and are
    all lowercase.  Requiring at least two case switches is enough to tell
    them apart without a dictionary.
    """
    if len(seg) < 8:
        return False
    letters = [c for c in seg if c.isalpha()]
    if len(letters) < 6:
        return False
    if not any(c.isupper() for c in letters) or not any(c.islower() for c in letters):
        return False
    switches = sum(1 for a, b in zip(seg, seg[1:])
                   if a.isalpha() and b.isalpha() and a.isupper() != b.isupper())
    return switches >= 2


def looks_classic(path: str, page_path: str = "") -> bool:
    """Return True when *path* looks like a classic Akamai sensor path.

    Classic sensors live at 4+ segment random paths
    (``/jFr5MX/7/d/.../Eio``).  Page markup also contains deep same-site
    URLs, so two hard constraints are applied:

    * the path must not equal / be a prefix of the page's own path;
    * at least one segment must pass :func:`path_entropy`.
    """
    if "/akam/" in path or path.startswith("http"):
        return False
    segs = [s for s in path.split("/") if s]
    if len(segs) < 4:
        return False
    if not all(re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", s) for s in segs):
        return False
    if page_path:
        a, b = path.rstrip("/"), page_path.rstrip("/")
        if a and b and (a == b or a.startswith(b + "/") or b.startswith(a + "/")):
            return False
    return any(path_entropy(s) for s in segs)


def classify_sensor(body: str, page_path: str = "") -> dict:
    """Classify a response without any network access.

    Returns a dict with:

    ``sensor``
        ``interstitial`` / ``challenge_recaptcha`` / ``challenge_crypto`` /
        ``compact_v3`` / ``classic`` / ``self_captcha`` / ``None``.
    ``sensor_path``
        Path of the sensor script for the two sensor families.
    ``locked``
        Interstitial only: True means the shell is a gate, not content.
    ``challenge``
        Interstitial only: token length, pow and endpoint.
    ``evidence``
        Extra markers such as ``akamai_denied_page`` / ``akamai_rate_limit``.

    Note the order: interstitial is checked first because a shell can also
    reference ``/akam/13/``.  The gate is the ``bm-verify`` step.
    """
    out = {"sensor": None, "evidence": []}
    if not body:
        return out

    compact = re.search(r"/akam/\d+/[a-z0-9]+", body)
    classic = re.search(r'src="([^"]{0,10}/[A-Za-z0-9_\-]{4,12}/[^"]{10,200})"', body)
    if is_interstitial(body):
        out["sensor"] = "interstitial"
        out["locked"] = True
        out["evidence"].append("interstitial_shell")
        ch = parse_interstitial(body)
        if ch:
            out["challenge"] = {"token_len": len(ch["bm_verify"]),
                                "pow": ch["pow"], "endpoint": ch["endpoint"]}
    elif "sec-cpt-if" in body:
        # Akamai's own captcha/PoW page ("Challenge Validation"): a wall, not a
        # gate.  Label it before the path heuristics below, otherwise its
        # random script path makes it look like a classic sensor.
        pv = re.search(r'\bprovider=["\']([A-Za-z0-9_-]+)["\']', body)
        out["sensor"] = f"challenge_{pv.group(1)}" if pv else "challenge"
        out["evidence"].append("akamai_challenge_iframe")
    elif compact:
        out["sensor"] = "compact_v3"
        out["sensor_path"] = compact.group(0)
    elif classic and looks_classic(classic.group(1), page_path):
        out["sensor"] = "classic"
        out["sensor_path"] = classic.group(1)
    elif "Bot or Not" in body:
        out["sensor"] = "self_captcha"       # Expedia's own gate, not Akamai

    if "Access Denied" in body[:3000] and re.search(
            r"Reference\s*(?:&#32;)?(?:#|&#35;)", body):
        out["evidence"].append("akamai_denied_page")
    if "Provisioned request rate has been exceeded" in body:
        out["evidence"].append("akamai_rate_limit")
    return out


def shell_path(html: str) -> str | None:
    """Path from the shell's ``meta refresh`` (often the locale prefix)."""
    m = re.search(
        r'http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*URL=[\'"]?([^\'"\s>]+)',
        html, re.I)
    if not m:
        return None
    p = urlparse(m.group(1)).path
    return p or "/"


def cookie_domain_mismatch(resp, host: str) -> str | None:
    """Return the cookie Domain when it cannot be stored on *host*.

    Example: a POST to ``www.bike24.net`` succeeds and sets
    ``ak_bmsc=...; Domain=.bike24.com``.  RFC 6265 forbids storing that
    cookie on ``www.bike24.net``, so the next request is still a shell even
    though the receipt said ``{"reload": true}``.  The fix is to move to the
    canonical domain, not to retry the token.
    """
    sc = resp.headers.get("set-cookie", "") or ""
    h = (host or "").lower()
    for dm in re.findall(r"[Dd]omain=\s*\.?([A-Za-z0-9.-]+)", sc):
        d = dm.lower().rstrip(".")
        if h == d or h.endswith("." + d):
            continue
        return d
    return None


def canonical_remap(url: str, shell_html: str, resp=None) -> list[str]:
    """Candidate canonical URLs for a ccTLD alias host.

    Some ccTLD hosts are structural dead ends:

    * the POST sets a cookie whose Domain belongs to another host, so the
      cookie can never be stored here;
    * or ``/_sec/verify`` simply is not mounted on this host.

    The real content usually lives on the canonical domain under the locale
    prefix already written in the shell's ``meta refresh``.

    Candidates, most trustworthy first:

    1. the ``Domain=`` from the POST receipt (the server says it itself);
    2. replace the ccTLD with ``.com`` (``zara.it`` -> ``zara.com``).
    """
    path = shell_path(shell_html) or "/"
    cur = urlparse(url).netloc.lower()
    cands: list[str] = []

    def _add(host: str) -> None:
        if not host or host == cur:
            return
        u = f"https://{host}{path}"
        if u not in cands:
            cands.append(u)

    if resp is not None:
        sc = resp.headers.get("set-cookie", "") or ""
        for dm in re.findall(r"[Dd]omain=\s*\.?([A-Za-z0-9.-]+)", sc):
            _add(f"www.{dm}")

    labels = cur.split(".")
    if labels and labels[0] == "www":
        labels = labels[1:]
    if len(labels) >= 2:
        _add(f"www.{labels[0]}.com")
    return cands


def cloudfront_draw(r) -> bool:
    """True when this response came from CloudFront, not Akamai.

    Amazon properties alternate between Akamai and AWS/CloudFront at the
    DNS level (hours, not per request).  A CloudFront draw is a 202 plus a
    ~2 KB bot page: neither a shell nor content.  It is an environment
    result, not a solver failure; retry with a fresh session.
    """
    srv = (r.headers.get("server") or "").lower()
    return ("cloudfront" in srv) or (r.status_code == 202 and len(r.text) < 4000)


def hard_block(r) -> bool:
    """True for a small 4xx denial page (usually 403 + 370-390 B).

    This is the edge's intermittent rate-limit page, not a shell and not
    content.  It heals in roughly 20 minutes; the right response is a fresh
    session and a retry, not "this site has no gate".
    """
    return r.status_code >= 400 and len(r.text) < 2000 and not is_interstitial(r.text)
