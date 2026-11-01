# -*- coding: utf-8 -*-
"""Network side of the interstitial solver.

The open-source edition ships **L1 direct** and **L2i interstitial** only.
The classic sensor layers (L2a/L2b) depend on per-site JavaScript
environments and are intentionally out of scope; see ``docs/BOUNDARIES.md``.

Design notes that are easy to get wrong:

* A shell and a real page are both HTTP 200.  Never use the status code as
  the success criterion; use :func:`gatekit.judges.is_interstitial`.
* The same session must fetch the shell *before* posting the token.  The
  challenge state lives at the edge.
* The fallback order is ``POST -> cross-origin hub -> canonical domain ->
  qparam``.  On variant B, sending a qparam first dirties the session and
  makes the subsequent POST fail.
"""
from __future__ import annotations

import json
import re
import threading
import time
from urllib.parse import urljoin, urlparse

from curl_cffi import requests

from .judges import (
    classify_sensor,
    cloudfront_draw,
    content_like,
    cookie_domain_mismatch,
    hard_block,
    is_interstitial,
    parse_interstitial,
    canonical_remap,
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")
FINGERPRINTS = ["chrome", "chrome124", "safari", "firefox", "edge"]


def _px(proxy: str | None) -> dict | None:
    return {"http": proxy, "https": proxy} if proxy else None


def detect(url: str, proxy: str | None = None, impersonate: str = "chrome") -> dict:
    """Fetch *url* once and classify the response (L0).

    Returns ``status`` / ``len`` / ``sensor`` / ``evidence`` and, for an
    interstitial shell, the parsed challenge metadata.  This is a diagnostic
    call, not a solver; it never retries.
    """
    out = {"url": url, "status": None, "sensor": None, "evidence": []}
    try:
        r = requests.get(url, impersonate=impersonate, timeout=30, proxies=_px(proxy),
                         headers={"user-agent": UA,
                                  "accept-language": "en-US,en;q=0.9"})
        out["status"] = r.status_code
        out["len"] = len(r.text)
        out.update(classify_sensor(r.text, urlparse(url).path))
        return out
    except Exception as e:  # noqa: BLE001 - diagnostics should not raise
        out["err"] = str(e)[:80]
        return out


def direct_get(url: str, proxy: str | None = None) -> dict:
    """Try a small fingerprint matrix and return the first page that passes.

    A 200 that is still an interstitial shell is **not** a pass; it is handed
    to the interstitial layer.  An explicit Akamai denial page stops the
    matrix, because changing TLS fingerprints cannot fix an ACL/geo block.
    """
    for imp in FINGERPRINTS:
        try:
            s = requests.Session(impersonate=imp, timeout=12)
            if proxy:
                s.proxies = _px(proxy)
            r = s.get(url, headers={"user-agent": UA,
                                    "accept-language": "en-US,en;q=0.9"})
            if r.status_code == 200:
                if is_interstitial(r.text):
                    return {"ok": False, "layer": "L1", "status": 200,
                            "challenge": "interstitial", "len": len(r.text)}
                return {"ok": True, "layer": f"L1:{imp}", "status": 200,
                        "len": len(r.text)}
            if r.status_code in (403, 429):
                body = r.text[:3000]
                if "Access Denied" in body and ("Reference" in body or "&#35;" in body):
                    return {"ok": False, "layer": "L1", "status": r.status_code,
                            "blocked": True}
                continue
        except Exception:  # noqa: BLE001 - try the next fingerprint
            continue
    return {"ok": False, "layer": "L1", "err": "all fingerprints failed"}


def _recheck_get(s, url: str, headers: dict, hops: int = 3):
    """GET after the POST, with a three-level redirect-loop fallback.

    Some edges (the Bershka family, observed 2026-11-01) answer the POST with
    ``{"reload": true}`` but then loop on redirects.  Retrying once and then
    following at most three hops without auto-redirect recovers the content.
    Only redirect errors are swallowed here; connection errors propagate so
    the caller can try the www host.
    """
    try:
        return s.get(url, headers=headers)
    except Exception as e:  # noqa: BLE001
        if not ("47" in str(e) or "Redirect" in type(e).__name__):
            raise
    time.sleep(0.5)
    try:
        return s.get(url, headers=headers)
    except Exception:  # noqa: BLE001
        pass
    r, u = None, url
    for _ in range(hops):
        r = s.get(u, headers=headers, allow_redirects=False)
        loc = r.headers.get("location")
        if not (300 <= r.status_code < 400 and loc):
            return r
        u = loc if loc.startswith("http") else urljoin(u, loc)
    return r


def solve_interstitial(url: str, proxy: str | None = None,
                       impersonate: str = "chrome", _depth: int = 0) -> dict:
    """Solve one interstitial challenge and return a result dict.

    The result separates two questions:

    ``ok``
        did we receive content (``content_like``)?
    ``gate``
        did the challenge itself open?  ``gate == "passed"`` with
        ``ok == False`` means the origin returned 401/503 or a short notice;
        that is not a solver failure and should be reported separately.

    ``variant`` records which path worked: ``A0`` / ``standard`` /
    ``canonical`` / ``hub`` / ``qparam``.
    """
    host = urlparse(url).netloc
    base = f"https://{host}"

    # Connection timeout 8 s: a hung apex is a *connection-level* hang.  A
    # read timeout of 45 s waits forever without receiving a byte.
    s = requests.Session(impersonate=impersonate, timeout=(8, 45))
    if proxy:
        s.proxies = _px(proxy)
    hdr = {"user-agent": UA, "accept-language": "en-US,en;q=0.9"}

    for _attempt in range(3):
        try:
            r = s.get(url, headers=hdr)
        except Exception as e:  # noqa: BLE001
            # Apex and www often resolve to the same edge IPs, but the edge
            # silently hangs "apex SNI + Chrome fingerprint".  Try www.
            u0 = urlparse(url)
            if not u0.netloc or u0.netloc.startswith("www."):
                return {"ok": False, "layer": "L2i", "err": f"get:{str(e)[:50]}"}
            try:
                r = s.get(url.replace(f"://{u0.netloc}", f"://www.{u0.netloc}", 1),
                          headers=hdr)
            except Exception as e2:  # noqa: BLE001
                return {"ok": False, "layer": "L2i", "err": f"get:{str(e2)[:50]}"}

        # An apex can also be hard-denied (403 + a few hundred bytes).  A
        # 403 is not an exception, so the except branch above never sees it.
        if r.status_code >= 400 and len(r.text) < 2000:
            u0 = urlparse(url)
            if u0.netloc and not u0.netloc.startswith("www."):
                try:
                    rw = s.get(url.replace(f"://{u0.netloc}", f"://www.{u0.netloc}", 1),
                               headers=hdr)
                    if rw.status_code < 400 or len(rw.text) > len(r.text):
                        r = rw
                except Exception:  # noqa: BLE001
                    pass

        # Hard denial is intermittent.  Only three consecutive small 4xx
        # responses are accepted as a real block.
        if hard_block(r):
            time.sleep(1.0 + _attempt)
            s = requests.Session(impersonate=impersonate, timeout=(8, 45))
            if proxy:
                s.proxies = _px(proxy)
            continue
        break

    # A CloudFront draw is a DNS-level event.  A new session means a new DNS
    # resolution; reusing keep-alive always reaches the same edge.
    for _ in range(2):
        if not cloudfront_draw(r):
            break
        time.sleep(0.8)
        s2 = requests.Session(impersonate=impersonate, timeout=(8, 45))
        if proxy:
            s2.proxies = _px(proxy)
        try:
            r2 = s2.get(r.url or url, headers=hdr)
        except Exception:  # noqa: BLE001
            break
        s, r = s2, r2

    # The site may redirect the apex to a canonical host.  The token is only
    # valid on the host that actually served the shell, so follow r.url.
    fu = urlparse(r.url)
    if fu.netloc and fu.netloc != host:
        host = fu.netloc
        for suffix in (":443", ":80"):
            if host.endswith(suffix):
                host = host[:-len(suffix)]
                break
        base = f"{fu.scheme or 'https'}://{host}"

    # ``url`` is the original argument and may now point at a dead host
    # (apex hang or redirect).  Rewrite it once so every later request
    # (A0 probe, recheck, qparam rebuild) uses the live base.
    u0, bn = urlparse(url), urlparse(base)
    req_url = url
    if bn.netloc and bn.netloc != u0.netloc:
        req_url = (f"{bn.scheme or 'https'}://{bn.netloc}{u0.path or '/'}"
                   + (f"?{u0.query}" if u0.query else ""))

    if not is_interstitial(r.text):
        if r.status_code == 200 and content_like(r.text):
            return {"ok": True, "layer": "L2i", "status": 200, "len": len(r.text),
                    "note": "first hop already returned content"}
        if cloudfront_draw(r):
            return {"ok": False, "layer": "L2i", "status": r.status_code,
                    "len": len(r.text),
                    "err": (f"CloudFront edge (DNS flip, not a gate; "
                            f"{r.status_code}/{len(r.text)}B)"),
                    "server": r.headers.get("server", "")}
        return {"ok": False, "layer": "L2i",
                "err": f"no interstitial (status {r.status_code}, len {len(r.text)})"}

    # --- A0: presence of the parameter is enough (one-shot session) ---
    # A fresh session with ``?bm-verify=`` (empty value) returns content on
    # some edge configurations.  Probe with an empty value only: a non-empty
    # value could also pass on variant A and would mislabel it.  Keep the
    # main session clean because a qparam on variant B dirties it.
    sep = "&" if "?" in req_url else "?"
    a0_err = None
    try:
        sa = requests.Session(impersonate=impersonate, timeout=15)
        if proxy:
            sa.proxies = _px(proxy)
        ra = sa.get(f"{req_url}{sep}bm-verify=", headers=hdr)
        if content_like(ra.text):
            ti = re.search(r"<title[^>]*>(.*?)</title>", ra.text[:200000], re.S | re.I)
            return {"ok": True, "layer": "L2i", "variant": "A0",
                    "status": ra.status_code, "len": len(ra.text),
                    "note": "A0 variant (parameter presence, no token)",
                    "title": re.sub(r"\s+", " ", ti.group(1)).strip()[:60] if ti else ""}
    except Exception as e:  # noqa: BLE001
        a0_err = f"{type(e).__name__}:{str(e)[:40]}"

    # --- Standard POST protocol ---
    ch = parse_interstitial(r.text)
    if ch is None:
        return {"ok": False, "layer": "L2i",
                "err": "interstitial shell but token unparsed"}

    endpoint = ch["endpoint"]
    if endpoint.startswith("/"):
        endpoint = base + endpoint
    try:
        rp = s.post(endpoint,
                    json={"bm-verify": ch["bm_verify"], "pow": ch["pow"]},
                    headers={"user-agent": UA, "accept": "*/*",
                             "content-type": "application/json",
                             "origin": base, "referer": req_url})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "layer": "L2i", "err": f"post:{str(e)[:50]}"}

    try:
        vd = json.loads(rp.text)
        vd = vd if isinstance(vd, dict) else None
    except Exception:  # noqa: BLE001
        vd = None

    recheck_url = req_url
    if vd and isinstance(vd.get("location"), str) and vd["location"]:
        loc = vd["location"]
        recheck_url = (loc if loc.startswith("http")
                       else base + ("" if loc.startswith("/") else "/") + loc)

    # Recheck at four delays: the Magnific family rotates ak_bmsc and only
    # serves content after ~1 s.  If POST returned HTML instead of JSON, we
    # hit the wrong origin; a recheck cannot help, so skip it.
    wrong_origin = vd is None and is_interstitial(rp.text)
    r2 = None
    if not wrong_origin:
        for wait in (0.6, 1.0, 1.5, 2.0):
            time.sleep(wait)
            try:
                r2 = _recheck_get(s, recheck_url, hdr)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "layer": "L2i", "err": f"recheck:{str(e)[:50]}"}
            if content_like(r2.text):
                break
    else:
        r2 = rp                                 # use the POST shell as the recheck

    ok = content_like(r2.text)
    out = {"ok": ok, "layer": "L2i", "status": r2.status_code, "len": len(r2.text),
           "verify_status": rp.status_code, "verify_body": rp.text[:60].strip(),
           "token_len": len(ch["bm_verify"]), "pow": ch["pow"],
           "set_cookie": list(dict(rp.cookies))}
    if vd:
        out["verify_json"] = vd
    if a0_err:
        out["a0_err"] = a0_err

    # Gate state and content state are separate.  401/503 after a successful
    # POST means the gate opened and the origin has nothing to give.
    post_ok = bool(vd and (vd.get("reload") is True or vd.get("location")))
    still_shell = is_interstitial(r2.text)
    gate_passed = post_ok and not still_shell
    out["gate"] = "passed" if gate_passed else ("shell" if still_shell else "unknown")

    if gate_passed and not ok:
        out["origin_status"] = r2.status_code
        if r2.status_code >= 400:
            low = r2.text.lower()
            kind = ("maintenance page" if ("メンテナンス" in r2.text or "maintenance" in low)
                    else "Basic Auth" if r2.status_code == 401
                    else "error page")
            out["err"] = f"gate passed, origin {r2.status_code} ({len(r2.text)}B, {kind})"
        else:
            out["err"] = f"gate passed but content too short ({r2.status_code}/{len(r2.text)}B)"
        return out

    # --- Fallback 1: cross-origin family hub ---
    # The visible host may only be a facade; the real gate lives on
    # challenge.<apex>, and content on www.<apex>.  Try before qparam because
    # wrong_origin is a strong signal and qparam always wastes time here.
    if not ok and wrong_origin:
        m = re.search(r"https?://challenge\.([A-Za-z0-9.-]+)", r.text)
        if m:
            hub = f"https://www.{m.group(1)}"
            mr = re.search(
                r'http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*URL=[\'"]?([^\'"\s>]+)',
                r.text, re.I)
            hp = urlparse(mr.group(1)).path if mr else "/"
            try:
                rr = solve_interstitial(hub + (hp or "/"), proxy=proxy,
                                        impersonate=impersonate)
                if rr.get("ok"):
                    rr.update({"note": f"cross-origin hub {hub}{hp or '/'}",
                               "fallback": "hub", "hub": hub, "hub_path": hp or "/"})
                    return rr
                out["hub_err"] = rr.get("err")
            except Exception as e:  # noqa: BLE001
                out["hub_err"] = f"hub:{type(e).__name__}:{str(e)[:40]}"

    # --- Fallback 1.6: ccTLD alias -> canonical domain + locale prefix ---
    if not ok and _depth == 0 and (
            wrong_origin or rp.status_code >= 400 or post_ok
            or cookie_domain_mismatch(rp, urlparse(url).netloc)):
        for cand in canonical_remap(url, r.text, rp)[:2]:
            try:
                rr = solve_interstitial(cand, proxy=proxy,
                                        impersonate=impersonate, _depth=1)
                if rr.get("ok"):
                    rr.update({"note": f"ccTLD alias -> canonical {cand}",
                               "fallback": "canonical", "canonical": cand,
                               "alias_url": url})
                    return rr
                out["canonical_err"] = rr.get("err")
            except Exception as e:  # noqa: BLE001
                out["canonical_err"] = f"canonical:{type(e).__name__}:{str(e)[:40]}"

    # --- Fallback 2: qparam variant ---
    # Only variant A honors it.  Rebuild the challenge first; a qparam is
    # only meaningful when the session has just fetched a shell.
    if not ok:
        sep = "&" if "?" in req_url else "?"
        try:
            s.get(req_url, headers=hdr)
            time.sleep(0.3)
            rq = s.get(f"{req_url}{sep}bm-verify=1", headers=hdr)
            if content_like(rq.text):
                out.update({"ok": True, "status": rq.status_code, "len": len(rq.text),
                            "note": "qparam variant (value not checked)",
                            "fallback": "qparam"})
                r2 = rq
                ok = True
            else:
                out["qparam_err"] = f"{rq.status_code}/{len(rq.text)}B"
        except Exception as e:  # noqa: BLE001
            out["qparam_err"] = f"qparam:{str(e)[:40]}"

    # --- Fallback 3: repeat the cross-origin hub (safety net) ---
    if not ok:
        m = re.search(r"https?://challenge\.([A-Za-z0-9.-]+)", r.text)
        if m:
            hub = f"https://www.{m.group(1)}"
            mr = re.search(
                r'http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*URL=[\'"]?([^\'"\s>]+)',
                r.text, re.I)
            hp = urlparse(mr.group(1)).path if mr else "/"
            try:
                rr = solve_interstitial(hub + (hp or "/"), proxy=proxy,
                                        impersonate=impersonate)
                if rr.get("ok"):
                    rr.update({"note": f"cross-origin hub {hub}{hp or '/'}",
                               "fallback": "hub", "hub": hub, "hub_path": hp or "/"})
                    return rr
                out["hub_err"] = rr.get("err")
            except Exception as e:  # noqa: BLE001
                out["hub_err"] = f"hub:{type(e).__name__}:{str(e)[:40]}"

    title = re.search(r"<title[^>]*>(.*?)</title>", r2.text[:200000], re.S | re.I)
    if title:
        out["title"] = re.sub(r"\s+", " ", title.group(1)).strip()[:60]
    if not ok:
        out["err"] = f"still interstitial (len {len(r2.text)}, verify {rp.status_code})"
    return out


def solve(url: str, proxy: str | None = None, layers=("L1", "L2i"),
          do_detect: bool = True, impersonate: str = "chrome") -> dict:
    """Try the shipped layers in order and return the first success.

    Layers are ordered by cost, not strength: one direct request is cheap;
    the interstitial protocol is only attempted when the response is (or may
    be) a shell.  The open-source edition does not include L2a/L2b.
    """
    trace: list[str] = []
    info = detect(url, proxy, impersonate) if do_detect else {}
    if do_detect:
        trace.append(f"detect:{info.get('status')}/{info.get('sensor')}")
    sensor = (info or {}).get("sensor")

    for layer in layers:
        if layer == "L1":
            res = direct_get(url, proxy)
        elif layer == "L2i":
            # A 200 shell must not be skipped just because the status is 200.
            if do_detect and sensor not in (None, "interstitial"):
                trace.append(f"{layer}:skip(sensor={sensor})")
                continue
            res = solve_interstitial(url, proxy, impersonate)
        else:
            trace.append(f"{layer}:unsupported")
            continue
        trace.append(f"{layer}:{res.get('status') if res.get('ok') else res.get('err', 'fail')}")
        if res.get("ok"):
            return {"url": url, "solved": True, "layer": res["layer"],
                    "trace": trace, "sensor": (info or {}).get("sensor"),
                    "detail": res}
    return {"url": url, "solved": False, "trace": trace,
            "sensor": (info or {}).get("sensor"), "detect": info}
