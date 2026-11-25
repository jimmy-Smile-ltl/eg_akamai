"""Prove whether page access rides on cookies or on the transport fingerprint.

Exports the session cookie header, then curls the same URL with and without it.
Usage: python wre/scripts/cookie_probe.py
"""

import subprocess

from _paths import NULL
from wre_client_akamai import AkamaiClient

URL = "https://www.apahotel.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")


def curl(code_url, cookie_header=None):
    cmd = ["curl", "-s", "-o", NULL, "-w", "%{http_code} %{size_download}",
           "-A", UA, "--max-time", "25", code_url]
    if cookie_header:
        cmd[1:1] = ["-H", "Cookie: " + cookie_header]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() or ("ERR " + (r.stderr or "")[:120])


with AkamaiClient.open({"page_url": URL}, startup_timeout=30) as c:
    print("client methods:", [m for m in dir(c) if not m.startswith("_")])
    s = c.solve({}, deadline=150)
    print("solve cookies keys:", list(s["cookies"].keys())[:12])

    header = None
    for args in ({}, None):
        try:
            ck = c.cookies(args) if args is not None else c.cookies()
        except TypeError:
            continue
        except Exception as e:
            print("cookies() err:", type(e).__name__, str(e)[:200])
            break
        # 只打印结构，不回显 cookie 值（避免测试日志泄露会话材料）
        shape = sorted(ck.keys()) if isinstance(ck, dict) else type(ck).__name__
        print("cookies() ->", shape)
        if isinstance(ck, dict) and ck.get("header"):
            header = ck["header"]
        break

    if not header:
        abck = (s["cookies"].get("abck") or {})
        bm = (s["cookies"].get("bm_sz") or {})
        parts = []
        if abck.get("token"):
            parts.append("_abck=" + abck["token"])
        if bm.get("token"):
            parts.append("bm_sz=" + bm["token"])
        header = "; ".join(parts)
    print("cookie header len:", len(header or ""))

    print("curl no cookie:", curl(URL))
    print("curl with cookie:", curl(URL, header))
