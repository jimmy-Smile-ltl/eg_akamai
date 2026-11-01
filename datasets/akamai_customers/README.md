# Akamai 官网客户案例清单

从 akamai.com 的公开 customer story 页面提取的客户与站点索引。

- **304** 条客户案例（英文列表，2026-09-17 快照）
- **273** 条案例带客户网址
- **268** 个去重后的主机名（注册域同为 268 个）
- 其中 **5** 个主机对应两条案例（`www.arcxp.com`、`www.douglas.de`、
  `vizury.com`、`www.rtl.nl`、`www.sevenwestmedia.com.au`）

这份清单回答的是「**Akamai 官网公开列过谁**」，不是「全网谁在用 Akamai」，
也不是本仓库本地那份 282 万的第三方候选发现池。后者只做 DNS/CNAME 发现，
不逐站请求，也未发布；这里是**官网自己列出的客户案例**，来源可核对、体量小、
不含扫描结论。

---

## 1. 文件

| 文件 | 行数 | 说明 |
|---|---:|---|
| `stories.csv` | 304 | 一条 customer story 一行，含中英文标题、行业、地点、客户网址 |
| `sites.csv` | 268 | 按主机名去重；同一主机的多条案例合并到 `story_slugs` |
| `collect.py` | — | 重新采集这两个 CSV 的脚本，只取元数据，不下载正文/PDF/图片 |
| `check_akamai.py` | — | 配套检测：这批站点现在还能不能看到 Akamai 信号；只写本地结果 |

## 2. 数据从哪来

采集对象是 Akamai 官网的两个公开列表页：

- 英文：<https://www.akamai.com/resources/customer-story>
- 中文：<https://www.akamai.com/zh/resources/customer-story>

列表页把全部案例放在 HTML 的 `data-prop-stories` 属性里（一段 JSON）。脚本
解析出标题与详情页 URL；再逐条打开详情页，从版式里取：

| 字段 | 取法 |
|---|---|
| `customer_url` | 详情正文里第一个指向外部的链接（排除 akamai.com、社交平台、PDF/图片） |
| `industry` | `Industry` / `行业` 卡片的标签链接 |
| `location` | `Location` / `位置` 卡片的第一段文字 |
| `title_zh` | 中文列表页按 slug 对齐；没有中文版的案例留空 |

这不是 Akamai 的 API，也没有隐藏接口；就是公开营销页。`collect.py` 用
`curl_cffi` 的 Chrome TLS 指纹访问（akamai.com 自己也有 Bot Manager，裸
`requests` 会被 403），默认每个请求间隔 0.45 秒，串行。

**快照时间**：2026-09-17（UTC+8）。实时页面会增删案例；2026-11-01 复跑时
英文列表已是 302 条、中文 252 条，所以重新采集**不会**逐字节复现这份 CSV。
CSV 是快照，不是实时视图。

## 3. 字段

### `stories.csv`

| 字段 | 含义 |
|---|---|
| `slug` | 案例在 akamai.com 上的路径末段，也是唯一键 |
| `title_en` / `title_zh` | 英文 / 中文列表标题；中文缺失时为空 |
| `industry` | 首个行业标签，已把 `Media & Entertainment` 等 5 种写法归并 |
| `location` | 客户地点；已剔除卡片里混入的网址和行业 |
| `customer_url` | 详情页里链到的客户站点（可能带路径） |
| `host` | `customer_url` 的主机名；没有外部链接时为空 |
| `story_url_en` / `story_url_zh` | 案例详情页（`story_url_zh` 仅中文版存在时） |

### `sites.csv`

| 字段 | 含义 |
|---|---|
| `host` | 去重后的主机名（保留 `www.` 等子域，因为不同子域可能对应不同站点） |
| `customer_url` | 该主机第一条案例里的网址 |
| `title_en` | 第一条案例的英文标题（可能是公司名，也可能是一句话标题） |
| `industry` / `location` | 同一主机多条案例的取值用 `; ` 合并 |
| `story_slugs` | 对应案例 slug，多条用 `;` 分隔 |
| `story_url_en` | 第一条案例的详情页 |

## 4. 重新采集

```bash
pip install curl_cffi beautifulsoup4
python collect.py                 # 写 stories.csv / sites.csv 到脚本所在目录
python collect.py --list-only     # 只抓列表（不生成 sites.csv）
python collect.py --limit 5 --out tmp   # 调试：只抓前 5 条详情
```

默认会覆盖同目录的 `stories.csv` / `sites.csv`；想保留快照就用 `--out` 指到
别的目录。脚本只写这两个 CSV，不落 HTML、不下载 PDF。请遵守 akamai.com 的
服务条款与 robots，不要并发压站；默认串行 + 0.45 秒间隔。

### 看看这些站现在是否还挂 Akamai

```bash
pip install curl_cffi dnspython
python check_akamai.py                    # 读同目录 sites.csv，默认 8 线程
python check_akamai.py --no-dns           # 只做 HTTP 检测，不需要 dnspython
python check_akamai.py --cert             # 加 TLS 证书 SAN（慢）
```

脚本检查 CNAME/NS、`Server: AkamaiGHost`、`X-Akamai-*`、`_abck`/`bm_*`
cookie 和边缘拒绝页，结果写 `akamai_check.csv/.json`（已被 `.gitignore`
排除，不要提交逐站检测结果）。默认 8 线程、单站一次首页请求；检测是启发式
快照，不是合同或覆盖率证据。

## 5. 这份清单不是什么

- **不是「Akamai 当前客户」名录**。官网案例会长期保留，客户可能已经迁移，
  也可能只用 Akamai 的媒体交付/安全产品而首页看不到痕迹。2026-09-17 用
  `check_akamai.py` 的同一套口径（DNS CNAME/NS、响应头、`_abck`/`bm_*`
  cookie、拒绝页）做了一次首页级检测：273 条网址中 **100 条**仍能看到
  Akamai 信号，**164 条**没有，**9 条**无法判断。检测只覆盖首页、只做一次，
  不能当合同或覆盖率证据。
- **不是 282 万候选池**。本地那份池子来自 Majestic / Tranco / ccTLD /
  Umbrella 四份名单的并集，只做 DNS 发现；它不随仓库发布，也不在这里。
- **不是完整案例库**。304 条里 31 条没有外部客户链接（匿名案例、Akamai 自身
  案例等），所以 `sites.csv` 是 268 个主机而不是 304 个。
- **字段有启发式误差**。客户网址取「正文第一个外链」，个别案例可能链到合作
  伙伴页；行业/地点取自页面卡片，7 条没有行业、17 条没有地点、58 条没有中文
  标题。缺就是缺，没有补猜。
- **不含正文、PDF、图片、联系方式**。这些没有进仓库，也不在 CSV 里；需要
  原文请直接访问 `story_url_en` / `story_url_zh`。

## 6. 来源与许可

- 数据来自 Akamai 公开营销页，采集目的是做公开站点的索引与研究；
  案例文字、图片、商标归 Akamai 及各客户所有，本目录只保留事实性元数据。
- 本目录的代码与仓库其他部分一样使用 MIT；对数据本身不主张额外权利，
  转载/再分发请注明来源 `akamai.com`。
- 本项目与 Akamai 无关联，未获其背书。
