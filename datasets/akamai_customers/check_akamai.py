#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查一批站点是否还能看到 Akamai 的痕迹。

这是 `sites.csv` 的配套工具：清单回答「官网列过谁」，这个脚本回答「现在首页
还能不能看到 Akamai」。检测是启发式的、单次快照，不是合同或覆盖率证据。

信号（命中任一强信号即判 `akamai`）：

1. DNS CNAME 指向 Akamai 边缘域（edgekey.net / edgesuite.net / akamaiedge.net …）
2. 注册域 NS 指向 Akamai Edge DNS
3. 响应头 `Server: AkamaiGHost` / `X-Akamai-*` / `Akamai-Origin-Hop`
4. 响应 Set-Cookie 出现 `_abck` / `ak_bmsc` / `bm_sz` / `bm_sv` / `bm_mi`
5. 正文是 Akamai 边缘的 Access Denied 页（`Access Denied` + `Reference #`）
6. 可选 `--cert`：TLS 证书 SAN 命中 Akamai 共享证书域（慢）

三态：`akamai`（有强信号）/ `none`（请求成功但无信号）/ `unknown`（请求失败且无信号）。

用法：

    pip install curl_cffi            # 必需
    pip install dnspython            # 可选；没有就只做 HTTP 检测
    python check_akamai.py                       # 读同目录 sites.csv
    python check_akamai.py --csv sites.csv --workers 8
    python check_akamai.py --urls https://a.com,https://b.com
    python check_akamai.py --cert                # 加证书 SAN（慢）

输出默认写 `akamai_check.csv` / `akamai_check.json`，已被 .gitignore 排除。
请控制并发：Akamai 站点对陌生流量敏感，默认 8 线程、单站一次请求。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
from urllib.parse import urlparse

try:
    from curl_cffi import requests
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖：pip install curl_cffi")

try:
    import dns.resolver
except ImportError:  # pragma: no cover
    dns = None

HERE = os.path.dirname(os.path.abspath(__file__))
AKAMAI_CNAME_SUFFIXES = (
    "edgekey.net", "edgesuite.net", "akamaiedge.net", "akamai.net",
    "akamaitechnologies.com", "akamai-staging.net", "akamaized.net",
    "globalredir.akadns.net",
)
AKAMAI_NS_SUFFIXES = ("akamai.net", "akamaitechnologies.com")
AKAMAI_HEADERS = (
    "X-Akamai-Transformed", "X-Akamai-Edgescape", "Akamai-Origin-Hop",
    "X-Akamai-Request-ID", "X-Reference-Error", "X-Akamai-Staging",
)
AKAMAI_COOKIES = ("_abck", "ak_bmsc", "bm_sz", "bm_sv", "bm_mi")
COMMON_SUBDOMAINS = ("static", "www2", "cdn", "img", "media", "api", "m",
                     "assets", "s", "origin", "edge", "images", "video")
DENIED_RE = re.compile(r"Access\s+Denied", re.I)
REF_RE = re.compile(r"Reference\s*(?:&#32;)?(?:#|&#35;|&num;)", re.I)
_thread = threading.local()


def norm_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    return value


def host_of(value: str) -> str:
    try:
        return (urlparse(norm_url(value)).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def session():
    if not getattr(_thread, "s", None):
        _thread.s = requests.Session(impersonate="chrome", timeout=12)
    return _thread.s


def resolve_cname_chain(host: str):
    """返回 (CNAME 链, 错误)。没有 CNAME 记录不算错误。"""
    if dns is None:
        return [], "dnspython not installed"
    chain, current = [], host.rstrip(".")
    try:
        for _ in range(10):
            answer = dns.resolver.resolve(current, "CNAME", lifetime=5)
            target = str(answer[0].target).rstrip(".")
            if target in chain:
                break
            chain.append(target)
            current = target
        return chain, None
    except dns.resolver.NoAnswer:
        return chain, None
    except dns.resolver.NXDOMAIN:
        return chain, "nxdomain"
    except Exception as exc:
        return chain, str(exc)[:80]


def resolve_ns(host: str):
    if dns is None:
        return [], "dnspython not installed"
    parts = host.split(".")
    registered = ".".join(parts[-2:]) if len(parts) >= 2 else host
    try:
        answer = dns.resolver.resolve(registered, "NS", lifetime=5)
        hits = []
        for record in answer:
            ns = str(record.target).rstrip(".").lower()
            if any(ns == suffix or ns.endswith("." + suffix)
                   for suffix in AKAMAI_NS_SUFFIXES):
                hits.append(ns)
        return hits, None
    except Exception as exc:
        return [], str(exc)[:60]


def cert_san_hits(host: str, port: int = 443):
    """读 TLS 证书 SAN；命中 Akamai 共享证书域时返回证据。"""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=6) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                san = tls.getpeercert().get("subjectAltName", ()) or ()
        hits = []
        for _, value in san:
            low = value.lower()
            if any(low == suffix or low.endswith("." + suffix)
                   for suffix in ("akamaized.net", "edgekey.net", "akamai.net", "edgesuite.net")):
                hits.append(value)
        return hits
    except Exception:
        return []


def http_probe(url: str, proxy: str | None):
    try:
        resp = session().get(url, timeout=15, allow_redirects=True,
                             proxies={"http": proxy, "https": proxy} if proxy else None)
    except Exception as exc:
        return None, url, {}, [], "", str(exc)[:100]
    return (resp.status_code, str(resp.url), dict(resp.headers),
            list(resp.cookies.keys()), resp.text[:4000], None)


def is_denied(body: str) -> bool:
    return bool(DENIED_RE.search(body) and REF_RE.search(body))


def check_site(url: str, do_cert: bool = False, proxy: str | None = None,
               use_dns: bool = True) -> dict:
    url = norm_url(url)
    host = host_of(url)
    evidence = []

    if use_dns and dns is not None and host:
        ns_hits, _ = resolve_ns(host)
        for ns in ns_hits:
            evidence.append(f"ns:{ns}")

        bases = [host]
        if not host.startswith("www."):
            bases.append("www." + host)
        main_hit = False
        for candidate in bases:
            chain, _ = resolve_cname_chain(candidate)
            for cname in chain:
                low = cname.lower()
                if any(low == suffix or low.endswith("." + suffix)
                       for suffix in AKAMAI_CNAME_SUFFIXES):
                    evidence.append(f"cname:{candidate}->{cname}")
                    main_hit = True
        # 主域/www 没命中时，再看常见子域（很多站只在静态资源域挂 Akamai）
        if not main_hit:
            base = host[4:] if host.startswith("www.") else host
            for sub in COMMON_SUBDOMAINS:
                candidate = f"{sub}.{base}"
                chain, _ = resolve_cname_chain(candidate)
                for cname in chain:
                    low = cname.lower()
                    if any(low == suffix or low.endswith("." + suffix)
                           for suffix in AKAMAI_CNAME_SUFFIXES):
                        evidence.append(f"cname:{candidate}->{cname}")
                        break

    status, final_url, headers, cookies, body, error = http_probe(url, proxy)
    if error is None:
        lower_headers = {key.lower(): value for key, value in headers.items()}
        for name in AKAMAI_HEADERS:
            if name.lower() in lower_headers:
                evidence.append(f"header:{name}")
        if "akamaighost" in lower_headers.get("server", "").lower():
            evidence.append("header:Server=AkamaiGHost")
        for cookie in AKAMAI_COOKIES:
            if cookie in cookies:
                evidence.append(f"cookie:{cookie}")
        if is_denied(body):
            evidence.append("page:akamai-access-denied")
    else:
        evidence.append(f"http_error:{error}")

    if do_cert and host:
        for san in cert_san_hits(host):
            evidence.append(f"cert_san:{san}")

    evidence = list(dict.fromkeys(evidence))
    strong = any(item.startswith(("cname:", "ns:", "header:", "cookie:",
                                  "page:", "cert_san:")) for item in evidence)
    verdict = "akamai" if strong else ("none" if error is None else "unknown")
    return {
        "host": host,
        "url": url,
        "verdict": verdict,
        "status": status,
        "final_url": final_url,
        "evidence": evidence,
    }


def read_targets(path: str):
    targets = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            url = (row.get("customer_url") or row.get("url") or "").strip()
            host = (row.get("host") or "").strip()
            if not url and host:
                url = "https://" + host
            if url:
                targets.append(url)
    return targets


def main():
    parser = argparse.ArgumentParser(
        description="检查站点是否还能看到 Akamai 信号（启发式、单次快照）")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--csv", default=os.path.join(HERE, "sites.csv"),
                        help="含 customer_url 或 host 列的 CSV（默认：sites.csv）")
    source.add_argument("--urls", help="逗号分隔的 URL")
    source.add_argument("--file", help="每行一个 URL 的文件")
    parser.add_argument("--out", default=os.path.join(HERE, "akamai_check"),
                        help="输出前缀（默认：同目录 akamai_check）")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--cert", action="store_true", help="检测 TLS 证书 SAN（慢）")
    parser.add_argument("--no-dns", action="store_true", help="跳过 DNS，只做 HTTP")
    parser.add_argument("--proxy", default="", help="如 http://127.0.0.1:7890")
    args = parser.parse_args()

    if args.urls:
        targets = [norm_url(x) for x in args.urls.split(",") if x.strip()]
    elif args.file:
        targets = [norm_url(x) for x in open(args.file, encoding="utf-8") if x.strip()]
    else:
        targets = read_targets(args.csv)

    targets = list(dict.fromkeys(targets))
    use_dns = not args.no_dns
    if use_dns and dns is None:
        print("[warn] 未安装 dnspython，跳过 DNS 检测（pip install dnspython）")
        use_dns = False
    print(f"[check] {len(targets)} sites, workers={args.workers}, "
          f"dns={use_dns}, cert={args.cert}")

    started = time.time()
    results = []
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futures = {
            pool.submit(check_site, url, args.cert, args.proxy or None, use_dns): url
            for url in targets
        }
        for index, future in enumerate(cf.as_completed(futures), 1):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "host": host_of(futures[future]), "url": futures[future],
                    "verdict": "unknown", "status": None, "final_url": None,
                    "evidence": [f"err:{str(exc)[:80]}"],
                })
            if index % 25 == 0:
                print(f"  {index}/{len(targets)} ({time.time() - started:.0f}s)")

    results.sort(key=lambda row: row["host"])

    with open(args.out + ".json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    with open(args.out + ".csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["host", "url", "verdict", "status", "final_url", "evidence"])
        for row in results:
            writer.writerow([row["host"], row["url"], row["verdict"],
                             row["status"], row["final_url"],
                             " | ".join(row["evidence"])])

    counts = {}
    for row in results:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    print(f"[done] {time.time() - started:.0f}s -> {args.out}.csv/.json")
    print("  " + "  ".join(f"{key}={counts.get(key, 0)}"
                           for key in ("akamai", "none", "unknown")))
    for row in results:
        if row["verdict"] == "akamai":
            print(f"  {row['host'][:40]:40} {', '.join(row['evidence'])[:100]}")


if __name__ == "__main__":
    main()
