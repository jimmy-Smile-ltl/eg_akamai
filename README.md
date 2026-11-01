# eg_akamai · gatekit

**Akamai interstitial（`bm-verify` 闸门）的探测 / 分析 / 解决工具包，判据全部可离线回归。**

> **English** — `gatekit` detects and solves the Akamai Bot Manager
> **interstitial** challenge: the 2–7 KB shell that is served with HTTP 200
> and carries a one-shot `bm-verify` token. It parses the token and its
> proof-of-work expression, posts them to `/_sec/verify?provider=interstitial`,
> rechecks at four delays, and falls back through the A0 / standard /
> canonical-domain / cross-origin variants. It also separates "the gate
> opened" from "the origin had content", so a sweep reports one honest
> number. It does **not** solve classic JS sensors, captchas, or other WAFs —
> those are reported as out of scope, not silently counted as failures.

```
python -m gatekit probe   https://www.zara.com/
python -m gatekit solve   https://www.zara.com/
python -m gatekit fetch   https://www.flaticon.com/ -o page.html
python -m gatekit inventory --sweep examples/sample_sweep.json
```

---

## 这是什么

Akamai 的拦法有很多种。本项目只做其中一种：**interstitial**。

它的特征是——响应 **HTTP 200**、体积 **2–7 KB**、正文里同时出现
`bm-verify` 与 `_sec/verify`。它不是错误页，而是一个要求浏览器先做一次
"提交令牌 → 刷新" 的壳。**状态码和体积都不足以判断**，只有正文能判断。

gatekit 把这件事拆成四层，每层都能单独测：

| 层 | 模块 | 回答的问题 |
|---|---|---|
| 判据 | `gatekit/judges.py` | 这是壳、是内容、还是别的东西？纯函数，零依赖 |
| 求解 | `gatekit/interstitial.py` | 取壳 → 解析 token/pow → POST → 四档复查 → 变体兜底 |
| 会话 | `gatekit/client.py` | 过闸后怎么复用同一个会话取页面 |
| 口径 | `gatekit/inventory.py` | 一批站里到底过了多少、拿到多少，分母是谁 |

**它不做什么**（详见 [docs/BOUNDARIES.md](docs/BOUNDARIES.md)）：

- 不碰 classic sensor（`/akam/` 压缩脚本、`_abck` 传感器）需要的 JS 环境；
- 不算 reCAPTCHA / PoW 挑战、不绕 PX / Cloudflare / DataDome；
- 不处理登录、付费墙、人机验证；
- 不内置代理池，也不需要住宅 IP——默认直连。

## 当前支持到哪

| 变体 | 行为 | 代表 |
|---|---|---|
| **A0** | 参数存在即放行（空 `?bm-verify=`） | Inditex 系、部分 Amazon 边缘 |
| **A** | qparam 容忍，POST 的 token 值也不校验 | zara、iberdrola |
| **B** | 只认 POST；先发 qparam 会弄脏会话 | flaticon、bike24 |
| **canonical** | ccTLD 别名存不下 cookie / 端点 404，需换规范域 | zara.it → zara.com/it |
| **cross-origin** | 门面站只嵌 `challenge.<apex>`，真闸在家族中枢 | iconfinder → magnific |

仓库自带的 24 行样本 sweep（`examples/sample_sweep.json`，真实结果摘录）口径：

```
gated hosts 24: Akamai-native 20 / front AWS WAF 2 / DNS flip 2
Akamai-native 20 -> content PASS 17 / gate-only 3 / fail 0
gate 20/20 = 100.0%   content 17/20 = 85.0%
```

3 个 gate-only 不是求解失败：闸开了，源站回的是维护页 / 401 / 短通告。

## 安装

```bash
pip install -e .          # 或 pip install curl_cffi
python -m gatekit --version
```

- Python 3.9+
- 只有一个运行时依赖：`curl_cffi`（TLS 指纹必需；裸 `requests` 会被边缘挡掉，
  这是实测，不是偏好）
- 判据层 `gatekit.judges` 连 `curl_cffi` 都不需要，可单独 import

## 快速开始

### 命令行

```bash
# 1. 探测：这个 URL 返回的到底是什么
python -m gatekit probe https://www.zara.com/
# {"url": "...", "status": 200, "sensor": "interstitial", "locked": true,
#  "challenge": {"token_len": 268, "pow": 2272089155, ...}, ...}

# 2. 求解：按成本从低到高跑 L1 → L2i
python -m gatekit solve https://www.zara.com/
# {"solved": true, "layer": "L2i", "trace": ["detect:200/interstitial", ...]}

# 3. 取数：过闸后在同一会话里取任意路径
python -m gatekit fetch "https://2ndstreet.jp/search?category=810032" -o result.html

# 4. 口径：一批站的分桶账本（快照可隔轮对比）
python -m gatekit inventory --sweep examples/sample_sweep.json
python -m gatekit inventory --sweep examples/sample_sweep.json --json auto
python -m gatekit inventory --diff data/inventory_20261101_1402.json
```

### 作为库

```python
from gatekit import detect, solve
from gatekit.client import InterstitialClient
from gatekit import judges

info = detect("https://www.zara.com/")
print(info["sensor"], info.get("challenge"))

res = solve("https://www.zara.com/")          # L1 + L2i
print(res["solved"], res.get("detail", {}).get("variant"))

c = InterstitialClient("https://www.nh-hotels.com")
print(c.unlock("/"))                           # {"ok": True, "variant": "..."}
status, html = c.get("/en/")

print(judges.is_interstitial(html))            # False
print(judges.content_like(html))               # True
```

## 三条核心判据

```python
# 壳：只看正文前 40 KB；状态码不参与判断
"bm-verify" in body[:40960] and ("_sec/verify" in body or "interstitial" in body)

# 内容：壳不是内容；别家拦截页不是内容；>20KB 是内容；
# 否则要求有 <title> 且可见正文 >800 字符
content_like(body)

# 闸开没开，和有没有内容，是两件事
gate == "passed" and ok == False   # 源站 401/503/短通告，不是求解失败
```

两个被真实事故钉住的细节：

- **40 KB 不是 6 KB**：flaticon 的 `_sec/verify` 落在 6,110 字节处；
- **20 KB 阈值必须给小页留活路**：17.6 KB 的真首页曾被纯长度判据误杀，
  现在由"标题 + 800 字正文"兜住。

## 五桶口径（报数前先看这里）

| 桶 | 含义 | 进分母 |
|---|---|---|
| `PASS` | 拿到真内容 | 是 |
| `GATE-ONLY` | 闸开了，源站没内容（401/503/短页） | 是 |
| `FAIL` | 闸没开（还是壳 / 连接失败） | 是 |
| `FRONT-WAF` | 前沿是别家（AWS WAF） | **否** |
| `ENV-FLIP` | Amazon 族本轮撞上 CloudFront（DNS 摆动） | **否** |

分母 = 行数 − `FRONT-WAF` − `ENV-FLIP`。不这样扣，同一份语料能报出四个不同的
通过率；`ENV-FLIP` 换一轮自己就好，不是能力变化。

## 仓库结构

```
eg_akamai/
├── gatekit/
│   ├── judges.py        # 纯判据：壳 / 内容 / 传感器 / 规范域
│   ├── interstitial.py  # L1 直连 + L2i 解闸（含 A0/变体兜底）
│   ├── client.py        # 会话客户端：过闸后取页面，重锁自动再解
│   ├── inventory.py     # 五桶口径、快照、隔轮 diff
│   └── cli.py           # python -m gatekit
├── data/fixtures/
│   ├── MANIFEST.md      # 来源、抓取时间、字节数、sha256
│   ├── real/            # 7 份真实响应（已脱敏）
│   └── synthetic/       # 3 份构造响应（覆盖小页 / 大页 / compact 传感器）
├── examples/
│   ├── README.md                # 24 行样本怎么读
│   └── sample_sweep.json        # 24 行真实结果摘录
├── datasets/
│   └── akamai_customers/        # 官网公开客户清单（304 案例 / 268 主机）+ 采集/检测脚本
│       ├── README.md
│       ├── stories.csv
│       ├── sites.csv
│       ├── collect.py
│       └── check_akamai.py
├── tests/test_offline.py        # 30 条离线断言，不联网
├── docs/                        # PLAYBOOK / SITE_FLOW / BOUNDARIES / TOOLS
├── CONTRIBUTING.md              # 判据改动与夹具提交规则
└── SECURITY.md                  # 私密报告渠道与安全边界
```

### 为什么只有这几个真实站点

它们不是"语料"，是**每种形态各一张样本**：

- `zara` —— A/A0 型壳，standard 协议；
- `flaticon` —— B 型 + Magnific 层，壳 6.9 KB、`_sec/verify` 在 6.1 KB；
- `nh-hotels` —— canonical 家族 + locale 前缀（`/en`）；
- `wurth` —— Akamai 自家的 crypto PoW 挑战页（`sec-cpt-if provider="crypto"`，
  **负样本**：是"墙"不是"闸"，`classify_sensor` 只报告不尝试）；
- `amazon` —— CloudFront 202（**负样本**：不是 Akamai 的锅）；
- `trustpilot` —— 别家 WAF 拦截页（**负样本**：不是同一个东西）；
- `zara_search_excerpt` —— 真内容 60 KB 摘录（**正样本**：不能判成壳）。

全量语料、cookie、批量扫描结果都留在本地，`.gitignore` 明确排除。
夹具已检查：不含有效 cookie、token 已过期、无个人数据。来源与 sha256 见
[data/fixtures/MANIFEST.md](data/fixtures/MANIFEST.md)。

## 公开的官网客户清单

另一类和扫描语料分开的数据：`datasets/akamai_customers/` 从 akamai.com 的
公开 customer story 页提取客户索引（2026-09-17 快照）。

- **304** 条案例、**273** 条带客户网址、**268** 个去重主机；
- 只含标题、行业、地点、公开网址等元数据，**不含正文、PDF、图片**；
- 31 条案例没有外部客户链接；5 个主机对应两条案例；
- 采集脚本 `collect.py`、检测脚本 `check_akamai.py` 一并开源。

这份清单回答的是「**官网公开列过谁**」，不是「现在谁还在用 Akamai」——
2026-09-17 的首页级检测里，273 条网址只有 100 条还能看到 Akamai 信号。
它也不是本地那份 282 万的第三方候选池；字段、口径和复现方式见
[datasets/akamai_customers/README.md](datasets/akamai_customers/README.md)。

## 研究规模（公开仓库之外）

仓库里的 7 份夹具是"每种形态各一张"，不是全部研究对象。判据和变体的结论来自
一个更大的本地语料，规模如下（**2026-11-01 快照，按主机名去重**；注册域用
`tldextract` 归并，如 `www.zara.it` → `zara.it`）：

| 口径 | 主机 | 注册域 | 说明 |
|---|---:|---:|---|
| 第三方发现池（本地，不发布） | — | 2,821,720 | Majestic / Tranco / ccTLD / Umbrella 四份名单并集；只做 DNS / CNAME 发现，未逐站请求 |
| 首页扫描 | 39,796 | 36,309 | 45,590 行探测记录 |
| 深链 / 路由级 | 3,998 | 3,951 | 每台主机多条路径 |
| 首页 + 深链对照 | 21,484 | 20,267 | 涌现实验：同一个站分别看首页和深链 |
| Bot Manager 矩阵 | 1,808 | 1,694 | 检查 `_abck` / `bm_*` |
| DNS 侧普查 | 13,071 | 13,026 | CNAME / NS / 厂商 |
| **HTTP 探测去重** | **45,446** | **41,562** | 上面各轮实验的并集 |
| **全部 JSON 去重** | **55,341** | **51,446** | 含 DNS |
| 确认 Akamai 信号 | 3,552 | 3,229 | 首页扫描中出现 `akamai_page` 或 `/akam/` 标记 |
| 确认 interstitial 壳 | 107 | 95 | `interstitial=true` 或 `bm-verify` 标记 |
| 其中闸证据并集 | 296 | 275 | `interstitial` / `bm-verify` / `gated` / `gate=passed` 的并集 |
| 求解 / 内容成功 | 177 | 149 | 求解器判定 `ok=true` |

本地语料约 3 GB：217 个 JSON（97,039 行）、550 份 HTML 快照、233 份 PDF。
**这些数据不随仓库发布**：`.gitignore` 排除 `data/full/`、`data/corpus_sweep*.json`
以及所有 cookie / HAR / session 文件；仓库里只有脱敏后的固定夹具。

读这张表要注意：第三方池的 282 万只是 DNS 发现名单，不等于逐站发过请求；各行
之间也不互斥（同一台主机可能既在首页扫描里，也在深链实验里），所以只有标为
**去重** 的两行是并集。公开的官网客户清单（268 主机）不在这张表里，它来自
akamai.com 自己列出的案例，见上一节。

## 离线回归

```bash
python tests/test_offline.py        # 30/30
python tests/test_offline.py -v     # 逐条
```

不联网、不读 cookie。改任何判据前先跑这里：它钉住了上面提到的两个真实事故
（6 KB 窗口、17 KB 误杀）以及五桶分母的算法。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/PLAYBOOK.md](docs/PLAYBOOK.md) | **探测 → 分析 → 解决**：拿到一个新站按什么顺序做决定 |
| [docs/SITE_FLOW.md](docs/SITE_FLOW.md) | **请求链路**：一个壳里有什么、每个包长什么样、变体怎么分叉 |
| [docs/BOUNDARIES.md](docs/BOUNDARIES.md) | 范围、失败模式、合规与已知缺陷 |
| [docs/TOOLS.md](docs/TOOLS.md) | CLI 参数、Python API、输出字段、退出码 |

## 边界与合规（请先读）

这个仓库是**协议研究与互操作性工具**，用于：

- 安全研究、教学、CTF；
- 对自己的站点 / 获得书面授权的目标做测试；
- 公开数据的合规采集（遵守目标站服务条款与 robots，控制速率）。

**不要**用它：

- 绕过登录、付费墙、验证码或访问控制；
- 采集个人信息、凭证、支付数据；
- 对目标站造成压力（并发保持个位数，遇到 403 就退）。

法律风险由使用者承担。不同司法辖区对"绕过技术措施"的规定不同（例如中国
《刑法》第 285 条第 3 款、《网络安全法》第 27 条；美国 CFAA；欧盟成员国
 implementations）。**先确认你有权限，再发请求。**

本项目与 Akamai 无任何关联，未获其背书。Akamai 随时可能改变挑战形态，
本仓库按"当前观测到的形态"实现，不承诺长期有效。

## 参与

- 发现新形态 / 判据误判：先读 [CONTRIBUTING.md](CONTRIBUTING.md)，附一段能
  离线复现的 body；
- 安全问题（凭据落盘、请求打错域、夹具泄漏）：按 [SECURITY.md](SECURITY.md)
  走私密渠道，**不要**开公开 issue 贴有效 token。

## License

MIT —— 见 [LICENSE](LICENSE)。
