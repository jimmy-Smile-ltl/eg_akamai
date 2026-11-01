# -*- coding: utf-8 -*-
"""A small client that opens an interstitial gate, then fetches paths.

Typical use::

    from gatekit.client import InterstitialClient

    c = InterstitialClient("https://www.example.com")
    print(c.unlock("/"))
    status, html = c.get("/search?q=shoes")

The client intentionally keeps the same session for the shell, the POST and
the recheck: the challenge state is stored at the edge for that session.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin, urlparse

from curl_cffi import requests

from .judges import (
    canonical_remap,
    cloudfront_draw,
    content_like,
    hard_block,
    is_interstitial,
    parse_interstitial,
    shell_path,
)
from .interstitial import UA


class InterstitialClient:
    def __init__(self, base: str, proxy: str | None = None,
                 impersonate: str = "chrome", timeout: int = 45):
        """*base* is an origin such as ``https://www.example.com`` (no path).

        ``proxy=None`` or ``""`` means direct.  Prefer direct: a dead default
        proxy makes every site look unreachable.
        """
        self.base = base.rstrip("/")
        self.impersonate = impersonate
        self.timeout = timeout
        self.proxy = proxy or None
        self.s = requests.Session(impersonate=impersonate, timeout=(8, timeout))
        if self.proxy:
            self.s.proxies = {"http": self.proxy, "https": self.proxy}
        self.unlocked = False
        self.variant = None          # A0 / standard / qparam / canonical / cross-origin
        self.a0 = False              # A0 sites need ?bm-verify= on every request
        self.a0_err = None
        self.hub = None              # cross-origin content host
        self._apex_hang = False
        self.stats = {"get": 0, "unlock": 0, "relock": 0}

    # ------------------------------------------------------------------ internals
    def _u(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.base + (path if path.startswith("/") else "/" + path)

    @staticmethod
    def _a0_url(url: str) -> str:
        """A0 sites: append an empty ``bm-verify`` parameter."""
        return f"{url}{'&' if '?' in url else '?'}bm-verify="

    def _is_ok(self, r) -> bool:
        return content_like(r.text)

    def _try_a0(self, url: str) -> dict | None:
        """Probe the A0 variant with a one-shot session.

        A qparam on variant B dirties the session, so the main session must
        stay clean.  A connection-level timeout usually means the apex SNI is
        hung; remember it and retry the probe on ``www``.
        """
        tmo = min(self.timeout, 15)

        def _probe(u: str):
            sa = requests.Session(impersonate=self.impersonate, timeout=(8, tmo))
            if self.proxy:
                sa.proxies = {"http": self.proxy, "https": self.proxy}
            return sa, sa.get(self._a0_url(u), headers=self._headers())

        try:
            sa, ra = _probe(url)
            if self._is_ok(ra):
                self.s = sa
                self.a0 = True
                return {"ok": True, "variant": "A0", "status": ra.status_code,
                        "len": len(ra.text),
                        "note": "parameter presence passes (no shell, no token)"}
        except Exception as e:  # noqa: BLE001
            self.a0_err = f"{type(e).__name__}:{str(e)[:40]}"
            if "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower():
                self._apex_hang = True
                u0 = urlparse(url)
                if u0.netloc and not u0.netloc.startswith("www."):
                    try:
                        sa2, ra2 = _probe(url.replace(
                            f"://{u0.netloc}", f"://www.{u0.netloc}", 1))
                        if self._is_ok(ra2):
                            self.s = sa2
                            self.a0 = True
                            self.base = f"{u0.scheme or 'https'}://www.{u0.netloc}"
                            return {"ok": True, "variant": "A0", "status": ra2.status_code,
                                    "len": len(ra2.text), "via_host": "www." + u0.netloc,
                                    "note": "A0 (probed on www after apex hang)"}
                    except Exception as e2:  # noqa: BLE001
                        self.a0_err += f" | www:{type(e2).__name__}"
        return None

    def _headers(self) -> dict:
        return {"user-agent": UA, "accept-language": "en-US,en;q=0.9"}

    def _post(self, endpoint: str, payload: dict, referer: str):
        if endpoint.startswith("/"):
            endpoint = self.base + endpoint
        return self.s.post(endpoint, json=payload,
                           headers={"user-agent": UA, "accept": "*/*",
                                    "content-type": "application/json",
                                    "origin": self.base, "referer": referer})

    @staticmethod
    def _verdict(rp) -> dict | None:
        """Parse the POST receipt: ``{"reload": true}`` / ``{"location": ...}``."""
        try:
            j = json.loads(rp.text)
        except Exception:  # noqa: BLE001
            return None
        return j if isinstance(j, dict) else None

    @staticmethod
    def _family_hub(shell_html: str) -> tuple[str | None, str | None]:
        """Return ``(hub_base, path)`` when another domain owns the gate.

        Some sites only embed ``challenge.<apex>`` and refresh to a path on
        their own domain.  Posting to the facade returns another shell, not
        JSON; the real token and endpoint live on the hub.
        """
        m = re.search(r"https?://challenge\.([A-Za-z0-9.-]+)", shell_html)
        if not m:
            return None, None
        hub = f"https://www.{m.group(1)}"
        path = shell_path(shell_html) or "/"
        return hub, path

    def _redirect_loop_get(self, url: str):
        """Three-level fallback for redirect loops (curl 47)."""
        time.sleep(0.5)
        try:
            return self.s.get(url, headers=self._headers())
        except Exception:  # noqa: BLE001
            pass
        r, cur = None, url
        for _ in range(3):
            r = self.s.get(cur, headers=self._headers(), allow_redirects=False)
            loc = r.headers.get("location")
            if not (300 <= r.status_code < 400 and loc):
                return r
            cur = loc if loc.startswith("http") else urljoin(cur, loc)
        return r

    def _get_once(self, url: str):
        try:
            return self.s.get(url, headers=self._headers())
        except Exception as e:  # noqa: BLE001
            if "47" in str(e) or "Redirect" in type(e).__name__:
                return self._redirect_loop_get(url)
            raise

    def _get_retry(self, url: str):
        """GET, falling back to ``www`` on apex connection failure or denial."""
        u0 = urlparse(self.base)
        can_www = bool(u0.netloc) and not u0.netloc.startswith("www.")

        def _via_www():
            self.base = f"{u0.scheme or 'https'}://www.{u0.netloc}"
            self.stats["get"] += 1
            return self._get_once(url.replace(
                f"://{u0.netloc}", f"://www.{u0.netloc}", 1))

        if self._apex_hang and can_www:
            return _via_www()
        try:
            r = self._get_once(url)
        except Exception:  # noqa: BLE001
            if not can_www:
                raise
            self._apex_hang = True
            return _via_www()
        if hard_block(r) and can_www:
            try:
                rw = self._get_once(url.replace(
                    f"://{u0.netloc}", f"://www.{u0.netloc}", 1))
            except Exception:  # noqa: BLE001
                return r
            if rw.status_code < 400 or len(rw.text) > len(r.text):
                self.base = f"{u0.scheme or 'https'}://www.{u0.netloc}"
                self.stats["get"] += 1
                return rw
        return r

    # ------------------------------------------------------------------ public
    def unlock(self, path: str = "/") -> dict:
        """Open the gate.  Returns a result dict with ``ok`` and ``variant``."""
        url = self._u(path)

        # 0) A0: parameter presence is enough.
        a0 = self._try_a0(url)
        if a0:
            self.unlocked = True
            self.stats["unlock"] += 1
            self.variant = "A0"
            return a0

        r = self._get_retry(url)
        self.stats["get"] += 1

        # Intermittent hard denial: retry with a fresh session (same as solver).
        for _ in range(2):
            if not hard_block(r):
                break
            time.sleep(1.0)
            s2 = requests.Session(impersonate=self.impersonate,
                                  timeout=(8, self.timeout))
            if self.proxy:
                s2.proxies = {"http": self.proxy, "https": self.proxy}
            self.s = s2
            try:
                r = self._get_retry(url)
            except Exception:  # noqa: BLE001
                break
            self.stats["get"] += 1

        # CloudFront draw: a new session means a new DNS resolution.
        for _ in range(2):
            if not cloudfront_draw(r):
                break
            time.sleep(0.8)
            s2 = requests.Session(impersonate=self.impersonate,
                                  timeout=(8, self.timeout))
            if self.proxy:
                s2.proxies = {"http": self.proxy, "https": self.proxy}
            try:
                r2 = s2.get(r.url or url, headers=self._headers())
            except Exception:  # noqa: BLE001
                break
            self.s, r = s2, r2
            self.stats["get"] += 1

        # Follow the host that actually served the shell.
        fu = urlparse(r.url)
        if fu.netloc and fu.netloc != urlparse(self.base).netloc:
            hn = fu.netloc
            for suffix in (":443", ":80"):
                if hn.endswith(suffix):
                    hn = hn[:-len(suffix)]
                    break
            self.base = f"{fu.scheme or 'https'}://{hn}"

        if not is_interstitial(r.text):
            if self._is_ok(r):
                self.unlocked = True
                return {"ok": True, "note": "no gate"}
            return {"ok": False,
                    "err": f"neither shell nor content ({r.status_code}/{len(r.text)}B)"}

        ch = parse_interstitial(r.text)
        if ch is None:
            return {"ok": False, "err": "cannot parse token from shell"}

        # 1) Standard POST.
        rp = self._post(ch["endpoint"],
                        {"bm-verify": ch["bm_verify"], "pow": ch["pow"]},
                        self._u("/"))
        vd = self._verdict(rp)

        u0, bu = urlparse(url), urlparse(self.base)
        if bu.netloc and bu.netloc != u0.netloc:
            targets = [f"{bu.scheme or 'https'}://{bu.netloc}{u0.path or '/'}"
                       + (f"?{u0.query}" if u0.query else "")]
        else:
            targets = [url]
        if vd and isinstance(vd.get("location"), str) and vd["location"]:
            loc = vd["location"]
            targets = [loc if loc.startswith("http")
                       else self.base + ("" if loc.startswith("/") else "/") + loc]

        # Recheck four times: content may only be readable after ~1 s.
        r2 = None
        for wait in (0.6, 1.0, 1.5, 2.0):
            time.sleep(wait)
            for t in targets:
                r2 = self._get_retry(t)
                self.stats["get"] += 1
                if self._is_ok(r2):
                    self.unlocked = True
                    self.stats["unlock"] += 1
                    self.variant = ("standard" if rp.status_code == 200
                                    else "standard(value unchecked)")
                    return {"ok": True, "variant": self.variant,
                            "post": rp.status_code, "verify": vd,
                            "len": len(r2.text),
                            "token_len": len(ch["bm_verify"])}

        # 1') Gate opened, origin returned a short landing page.  The gate is
        # open when the shell is gone; report it separately from "no content".
        vd_ok = bool(vd and (vd.get("reload") is True or vd.get("location")))
        if vd_ok and not is_interstitial(r2.text):
            if r2.status_code >= 400:
                return {"ok": False, "gate": "passed",
                        "origin_status": r2.status_code,
                        "post": rp.status_code, "verify": vd,
                        "err": f"gate passed, origin {r2.status_code} ({len(r2.text)}B)"}
            if len(r2.text) >= 1000:
                self.unlocked = True
                self.stats["unlock"] += 1
                self.variant = "standard(short page)"
                return {"ok": True, "variant": self.variant,
                        "post": rp.status_code, "verify": vd,
                        "gate": "passed", "content": "short",
                        "len": len(r2.text), "token_len": len(ch["bm_verify"])}

        # 2) Canonical domain fallback (ccTLD alias).
        for cand in canonical_remap(url, r.text, rp)[:2]:
            try:
                up = urlparse(cand)
                c3 = InterstitialClient(f"https://{up.netloc}",
                                        proxy=self.proxy or "",
                                        timeout=self.timeout)
                r4 = c3.unlock(up.path or "/")
                if r4.get("ok"):
                    self.hub = c3
                    self.unlocked = True
                    self.stats["unlock"] += 1
                    self.variant = "canonical"
                    return {"ok": True, "variant": "canonical",
                            "canonical": cand, "alias_url": url,
                            "post": rp.status_code,
                            "len": r4.get("len"),
                            "token_len": len(ch["bm_verify"])}
            except Exception as e:  # noqa: BLE001
                self.a0_err = f"canonical:{type(e).__name__}:{str(e)[:40]}"

        # 3) qparam variant (variant A only; rebuild the challenge first).
        self.stats["get"] += 1
        self._get_retry(url)
        sep = "&" if "?" in url else "?"
        rq = self._get_retry(f"{url}{sep}bm-verify=1")
        self.stats["get"] += 1
        if self._is_ok(rq):
            self.unlocked = True
            self.stats["unlock"] += 1
            self.variant = "qparam"
            return {"ok": True, "variant": "qparam", "post": rp.status_code,
                    "len": len(rq.text), "token_len": len(ch["bm_verify"])}

        # 4) Cross-origin hub (facade -> family hub).
        hub, hub_path = self._family_hub(r.text)
        if hub:
            try:
                c2 = InterstitialClient(hub, proxy=self.proxy or "",
                                        timeout=self.timeout)
                r3 = c2.unlock(hub_path or "/")
                if r3.get("ok"):
                    self.hub = c2
                    self.unlocked = True
                    self.stats["unlock"] += 1
                    self.variant = "cross-origin"
                    return {"ok": True, "variant": "cross-origin",
                            "hub": hub, "hub_path": hub_path,
                            "post": rp.status_code,
                            "len": r3.get("len"),
                            "token_len": len(ch["bm_verify"])}
            except Exception as e:  # noqa: BLE001
                self.a0_err = f"hub:{type(e).__name__}:{str(e)[:40]}"

        return {"ok": False, "post": rp.status_code, "verify": vd,
                "verify_body": rp.text[:60],
                "err": f"POST and qparam both failed "
                       f"({r2.status_code}/{len(r2.text)}B)"}

    def get(self, path: str, auto_unlock: bool = True) -> tuple[int, str]:
        """GET *path*; if it re-locks, open the gate once more."""
        if self.hub:
            return self.hub.get(path, auto_unlock)
        url = self._u(path)
        r = self._get_retry(url)
        self.stats["get"] += 1
        if is_interstitial(r.text) and auto_unlock:
            self.stats["relock"] += 1
            self.unlocked = False
            self.unlock("/")
            r = self.s.get(self._a0_url(url) if self.a0 else url,
                           headers=self._headers())
            self.stats["get"] += 1
        return r.status_code, r.text
