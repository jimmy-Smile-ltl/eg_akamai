# MANIFEST — 夹具来源与校验

> 每份夹具都是**一次真实响应**（synthetic 除外），抓取时间统一按 UTC+8 记。
> 体积是磁盘上的字节数；sha256 可按同名算法自行复核。
> token / challenge 值**均已过期**，不能重放，只用于判据测试。

---

## 1. real/ —— 7 份真实响应

| 文件 | 来源 | 抓取时间 | 字节 | sha256 | 代表什么 |
|---|---|---|---|---|---|
| `zara_shell.html` | `https://www.zara.com/` | 2026-11-01 14:30 | 2,122 | `99633fc73b044317b5dc227fffa75477e716b3d1d63a4aace5d8e159639e0e42` | interstitial 壳，standard 协议；token 268、`pow = 1793514655 + 478574500`（A/A0 型站） |
| `flaticon_shell.html` | `https://www.flaticon.com/` | 2026-11-01 14:30 | 6,924 | `7cf58d3750210764ccd86b864adea769c2dd944c93e0711f11a46653169f47f6` | 最大的壳（Magnific 层），`_sec/verify` 在约 6,110 B 处——6 KB 扫描窗口会漏掉它；B 型站 |
| `nh_hotels_shell.html` | `https://www.nh-hotels.com/` | 2026-10-31 23:04 | 2,253 | `af93bdc12887368cd71b519323e037caa47a3c3ecc21eda66966b7edbdd6b2b9` | canonical 家族；`meta refresh` 指向 locale 前缀 `/en?bm-verify=...` |
| `wurth_classic_challenge.html` | `https://www.wurth.fr/` | 2026-11-01 01:24 | 1,822 | `8bd6c2512f7e1c88ebecc3cf02efae3387f8f1863dfb78206da99183480d70e0` | **负样本**：Akamai 自家验证页（`id="sec-cpt-if"`，`provider="crypto"`，`difficulty: 2500`）。是**墙**不是闸；随机脚本路径会诱使 `classic` 误判，故分类器先标 `challenge_crypto` |
| `amazon_cloudfront_202.html` | `https://www.amazon.co.uk/` | 2026-11-01 11:30 | 2,055 | `d076d879408e0af96d47e89a5bcc4b777b4eb4e6cc88c09561b75bb4837ccbc9` | **负样本**：202 + AWS WAF（`gokuProps` / `awswaf` token）。是别的厂商，不是 Akamai 闸；口径记 `FRONT-WAF` / `ENV-FLIP` |
| `trustpilot_block.html` | `https://www.trustpilot.com/` | 2026-10-31 23:59 | 991 | `92d97ed45d6cc267c657b864c4deee1c2d896cda361adc660bc16538a75700f2` | **负样本**：AWS WAF "Verifying Connection" 拦截页 |
| `zara_search_excerpt.html` | `https://www.zara.com/`（搜索页） | 2026-10-31 23:03 | 60,000 | `a6432ef373e9f81f93b8f9d5ba1dde9bdc7c6c7fa685bd8978d363f445af5c52` | **正样本**：真内容。原始 721,316 B，截前 60,000 B（`_zara_search_nogate.html`），证明 >20 KB 内容不会被判成壳 |

## 2. synthetic/ —— 3 份构造响应

由构造脚本生成（简单 HTML 拼接，无抓包），**不是**任何站点的响应：

| 文件 | 字节 | sha256 | 用途 |
|---|---|---|---|
| `compact_page.html` | 24,134 | `a85e2358903be60ab84ddb469de26bb46e360638990fd7a87d8e8e2511963861` | 正常页 + `/akam/13/...` 传感器标签 → `compact_v3`，`locked` 必须为空 |
| `content_large.html` | 60,348 | `f1e899e6db6140fa8f07727fa3ffe2b5ad0c4a89d85525f6ca98dec5c195d404` | 大页内容，走 `len > 20000` 分支 |
| `content_small.html` | 4,777 | `a2751d08ce944898c902df15886fab6c3113e9f85f5a257eebddede0e0171431` | 4.7 KB 但 `<title>` + 密集正文 → 必须判为内容（17 KB 误杀事故的回归） |

## 3. 脱敏说明

- **不保留任何 cookie**：抓取时只取响应头用于判据，仓库里的文件是正文；
- **token / challenge 已过期**：`bm-verify` 是一次性的，`challenge` blob 里的
  `timestamp` 早已越窗，重放只会得到新的壳；
- **无个人数据**：搜索页摘录只含公开商品目录，不含账号、订单、地址；
- **保留品牌与文案**：判据依赖标题与错误提示（如 "Access Denied"），刻意不删。

## 4. 复核

```bash
# 在仓库根目录
python - <<'PY'
import hashlib, glob, os
for p in sorted(glob.glob("data/fixtures/**/*.html", recursive=True)):
    b = open(p, "rb").read()
    print(f"{os.path.basename(p):32s} {len(b):7d}  {hashlib.sha256(b).hexdigest()}")
PY
```

体积或哈希与上表不符，说明夹具被改动过——先跑 `tests/test_offline.py`，
再检查是哪条断言依赖了被改的字节。
