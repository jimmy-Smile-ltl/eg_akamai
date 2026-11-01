#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集 Akamai 官网公开的 customer story 清单。

只输出两类结构化数据，不下载正文、PDF 或图片：

    stories.csv  一条 customer story 一行（标题、行业、地点、客户网址）
    sites.csv    按主机名去重后的客户站点清单

数据来源是 akamai.com 的公开营销页面：

    https://www.akamai.com/resources/customer-story
    https://www.akamai.com/zh/resources/customer-story

用法：

    pip install curl_cffi beautifulsoup4
    python collect.py                     # 抓全量详情，约 5~8 分钟（默认 0.45s/请求）
    python collect.py --list-only         # 只抓列表，不请求详情，也不写 sites.csv
    python collect.py --limit 5 --out tmp # 调试：只抓前 5 条详情

注意：默认写脚本所在目录，会覆盖同名的 stories.csv / sites.csv；想保留快照
就用 --out 指到别的目录。

akamai.com 前面有 Akamai Bot Manager，普通 requests 容易被 403。这里用
curl_cffi 的 Chrome TLS 指纹；遇到 403/412/429 会重建会话并退避重试。
请控制速率，不要并发扫站。
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
from collections import defaultdict
from urllib.parse import urljoin, urlparse

try:
    from curl_cffi import requests
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖：pip install curl_cffi beautifulsoup4")

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖：pip install curl_cffi beautifulsoup4")


BASE = "https://www.akamai.com"
LIST_URLS = {
    "en": f"{BASE}/resources/customer-story",
    "zh": f"{BASE}/zh/resources/customer-story",
}
SOCIAL_DOMAINS = (
    "twitter.com", "x.com", "facebook.com", "linkedin.com", "youtube.com",
    "instagram.com", "onetrust.com", "google.com", "akamai.com",
)
CARD_KEYS = {
    "location": "location", "位置": "location",
    "industry": "industry", "行业": "industry",
}
URL_RE = re.compile(r"https?://\S+", re.I)
# 裸域名（含路径）：详情卡片里网址和地名常常写在同一个字段
DOMAIN_RE = re.compile(
    r"(?<!\w)(?:[a-z0-9-]+\.)+"
    r"(?:com|net|org|io|ai|tv|us|uk|de|jp|fr|ca|au|nl|dk|in|hk|sg|br|il|es|it|se|no|"
    r"fi|ch|at|be|pl|ru|cn|kr|tw|co|me|app|dev|xyz)(?:/\S*)?",
    re.I,
)
INDUSTRY_MAP = {
    "Media & Entertainment": "Media",
    "Media and Entertainment": "Media",
    "Retail, Travel, and Hospitality": "Retail, Travel & Hospitality",
    "Business and Technology Services": "Business Services",
    "Service Providers": "Service Provider",
}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").replace(" ", " ").strip()


def norm_url(url: str) -> str:
    url = (url or "").strip().strip("\"'")
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        url = BASE + url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def host_of(url: str) -> str:
    try:
        return (urlparse(norm_url(url)).hostname or "").lower().lstrip(".")
    except ValueError:
        return ""


def slug_of(url: str) -> str:
    path = urlparse(norm_url(url)).path.rstrip("/")
    return path.rsplit("/", 1)[-1]


def clean_title(text: str) -> str:
    text = norm(text)
    return re.sub(r"\s*\|\s*Akamai\s*$", "", text, flags=re.I).strip()


def clean_industry(text: str) -> str:
    text = norm((text or "").split("|")[0])
    return INDUSTRY_MAP.get(text, text)


def clean_location(raw: str, site: str, industry: str) -> str:
    """详情卡片把地名、网址、行业拼在一起，这里只留地名。"""
    text = URL_RE.sub(" ", raw or "")
    host = host_of(site)
    if host:
        bare = host[4:] if host.startswith("www.") else host
        for token in {site, host, bare, "www." + bare}:
            if token:
                text = re.sub(re.escape(token), " ", text, flags=re.I)
    text = DOMAIN_RE.sub(" ", text)
    if industry:
        text = text.replace(industry, " ")
    return norm(text.split("|")[0])


def is_customer_site(url: str) -> bool:
    url = norm_url(url)
    if not url.lower().startswith(("http://", "https://")):
        return False
    host = host_of(url)
    if not host:
        return False
    if any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS):
        return False
    return not url.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".svg", ".gif"))


class Fetcher:
    def __init__(self, delay: float, timeout: float):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session(impersonate="chrome")

    def _reset(self):
        try:
            self.session.close()
        except Exception:
            pass
        self.session = requests.Session(impersonate="chrome")

    def get(self, url: str, tries: int = 3) -> str:
        last = None
        for attempt in range(tries):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code in (403, 412, 429):
                    last = f"HTTP {resp.status_code}"
                    self._reset()
                    time.sleep(1.0 + attempt)
                    continue
                resp.raise_for_status()
                time.sleep(self.delay)
                return resp.text
            except Exception as exc:  # 网络错误 / 5xx / TLS
                last = str(exc)
                if attempt == tries - 1:
                    break
                time.sleep(1.0 + attempt)
        raise RuntimeError(f"GET {url} 失败：{last}")


def parse_list(text: str) -> list[dict]:
    """列表页把 304 条案例塞在 data-prop-stories 属性里。"""
    match = re.search(r'data-prop-stories="(\[\{.*?\}\])"', text, re.S)
    if not match:
        raise ValueError("列表页里没有 data-prop-stories，页面结构可能变了")
    data = json.loads(html.unescape(match.group(1)))
    seen, items = set(), []
    for item in data:
        url = norm_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        item = dict(item)
        item["url"] = url
        item["slug"] = slug_of(url)
        items.append(item)
    return items


def collect_card(heading) -> str:
    """收集卡片标题到下一个 h2/h3 之间的文本（兼容两种版式）。"""
    items = []
    for node in heading.find_all_next():
        if node.name in ("h2", "h3"):
            break
        if node.name in ("p", "li", "a"):
            text = norm(node.get_text(" ", strip=True))
            if text and not text.lower().startswith(("http://", "https://")):
                items.append(text)
    return " | ".join(dict.fromkeys(items))


def parse_detail(text: str) -> tuple[str, str, str]:
    """返回 (客户网址, 地点, 行业)。"""
    soup = BeautifulSoup(text, "html.parser")
    main = soup.find("main") or soup
    kids = main.find_all(recursive=False)
    story = kids[1] if len(kids) > 1 else main

    cards = {}
    for heading in story.find_all(["h2", "h3"]):
        key = CARD_KEYS.get(norm(heading.get_text()).lower())
        if key and key not in cards:
            cards[key] = collect_card(heading)

    site = ""
    for link in story.find_all("a", href=True):
        href = link["href"].strip()
        if is_customer_site(href):
            site = norm_url(href)
            break

    industry = clean_industry(cards.get("industry", ""))
    location = clean_location(cards.get("location", ""), site, industry)
    return site, location, industry


def build_rows(en_items: list[dict], zh_items: list[dict], details: dict[str, dict],
               with_details: bool) -> tuple[list[dict], list[dict]]:
    zh_by_slug = {item["slug"]: item for item in zh_items if item.get("slug")}
    stories = []
    for item in en_items:
        detail = details.get(item["slug"], {})
        site = detail.get("site", "") if with_details else ""
        industry = detail.get("industry", "") if with_details else ""
        stories.append({
            "slug": item["slug"],
            "title_en": clean_title(item.get("title", "")),
            "title_zh": clean_title(zh_by_slug.get(item["slug"], {}).get("title", "")),
            "industry": industry,
            "location": detail.get("location", "") if with_details else "",
            "customer_url": site,
            "host": host_of(site),
            "story_url_en": item["url"],
            "story_url_zh": zh_by_slug.get(item["slug"], {}).get("url", ""),
        })
    stories.sort(key=lambda row: row["slug"])

    by_host = defaultdict(list)
    for row in stories:
        if row["host"]:
            by_host[row["host"]].append(row)

    sites = []
    for host in sorted(by_host):
        group = by_host[host]
        first = group[0]
        industries = list(dict.fromkeys(x["industry"] for x in group if x["industry"]))
        locations = list(dict.fromkeys(x["location"] for x in group if x["location"]))
        sites.append({
            "host": host,
            "customer_url": first["customer_url"],
            "title_en": first["title_en"],
            "industry": "; ".join(industries),
            "location": "; ".join(locations),
            "story_slugs": "; ".join(x["slug"] for x in group),
            "story_url_en": first["story_url_en"],
        })
    return stories, sites


def write_csv(path: str, fields: list[str], rows: list[dict]):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="采集 akamai.com 的公开 customer story 清单（不含正文/PDF）")
    parser.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)),
                        help="输出目录（默认：脚本所在目录）")
    parser.add_argument("--list-only", action="store_true",
                        help="只抓列表页，不请求详情（sites.csv 会为空）")
    parser.add_argument("--limit", type=int, default=0,
                        help="只抓前 N 条详情，调试用（0 = 全量）")
    parser.add_argument("--delay", type=float, default=0.45,
                        help="请求间隔秒数（默认 0.45）")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    fetcher = Fetcher(args.delay, args.timeout)

    print("[1/3] 列表页")
    en_items = parse_list(fetcher.get(LIST_URLS["en"]))
    print(f"      en: {len(en_items)} 条")
    try:
        zh_items = parse_list(fetcher.get(LIST_URLS["zh"]))
    except Exception as exc:
        print(f"      zh 失败（{exc}），继续只用英文列表")
        zh_items = []
    print(f"      zh: {len(zh_items)} 条")

    details = {}
    if not args.list_only:
        todo = en_items[:args.limit] if args.limit else en_items
        print(f"[2/3] 详情页 {len(todo)} 条")
        for idx, item in enumerate(todo, 1):
            try:
                site, location, industry = parse_detail(fetcher.get(item["url"]))
            except Exception as exc:
                print(f"      [{idx}/{len(todo)}] {item['slug']}: 失败 {exc}")
                continue
            details[item["slug"]] = {"site": site, "location": location, "industry": industry}
            if idx % 20 == 0 or idx == len(todo):
                print(f"      [{idx}/{len(todo)}] {item['slug']} -> {host_of(site) or '-'}")

    print("[3/3] 写 CSV")
    stories, sites = build_rows(en_items, zh_items, details, not args.list_only)
    story_fields = ["slug", "title_en", "title_zh", "industry", "location",
                    "customer_url", "host", "story_url_en", "story_url_zh"]
    write_csv(os.path.join(args.out, "stories.csv"), story_fields, stories)
    print(f"      stories.csv: {len(stories)} 行")

    if args.list_only:
        print("      sites.csv 未生成（--list-only 不请求详情）")
        return

    site_fields = ["host", "customer_url", "title_en", "industry", "location",
                   "story_slugs", "story_url_en"]
    write_csv(os.path.join(args.out, "sites.csv"), site_fields, sites)
    print(f"      sites.csv:   {len(sites)} 个主机"
          f"（{sum(1 for x in stories if x['host'])} 条案例有客户网址）")


if __name__ == "__main__":
    main()
