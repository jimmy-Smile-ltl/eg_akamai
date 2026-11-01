# PLAYBOOK — 探测 / 分析 / 解决

> 这份文档只回答三件事：**拿到一个新域名，先看什么、再判什么、最后跑什么。**
> 请求链路细节见 [SITE_FLOW.md](SITE_FLOW.md)，范围与缺陷见
> [BOUNDARIES.md](BOUNDARIES.md)，命令参数见 [TOOLS.md](TOOLS.md)。

---

## 零、三分钟

| 阶段 | 要回答的问题 | 一条命令 | 通过的样子 |
|---|---|---|---|
| **探测** | 这站拦不拦？拦在哪一层？ | `python -m gatekit probe URL` | `sensor=interstitial` |
| **分析** | 是壳、是传感器、还是别家的墙？ | 同上，看 `sensor` / `evidence` | `locked=true` 且 `challenge` 有值 |
| **解决** | 闸能不能开？ | `python -m gatekit solve URL` | `solved=true` |
| **取数** | 开了闸拿不拿得到内容？ | `python -m gatekit fetch URL -o page.html` | `gate.ok=true` + 合理体积 |
| **报数** | 一批站适配了多少？ | `python -m gatekit inventory --sweep ...` | `gate N/N` + 内容数分开 |

最常见的三个错位：

1. 把"响应慢 / 连不上"当成"没闸" → §1.5；
2. 把"过了闸"当成"拿到了数据" → §2.5；
3. 把"解不开"当成"求解器坏了" → §3.3 排障表。

---

## 一、探测：先回答"值不值得解"

### 1.1 它到底是不是 Akamai —— 信号有强弱

| 强度 | 信号 | 判据 | 备注 |
|---|---|---|---|
| ★★★ | **DNS CNAME** | 后缀 `edgekey.net` / `edgesuite.net` / `akamaiedge.net` / `akamai.net` / `akamaized.net` | 唯一能当**分母**的判据 |
| ★★★ | DNS NS | `a1-23.akamai.net` 这类 | Edge DNS 客户可能没有 CNAME 特征 |
| ★★ | `Set-Cookie` | `_abck` / `ak_bmsc` / `bm_sz` / `bm_mi` / `_bm` | **无损探针**：只说明该路径部署了 Bot Manager，不触发挑战 |
| ★ | `403 Access Denied` + `Reference #` | 注意 `#` 可能编码成 `&#35;` | 只证明"被拦过"，不证明是谁拦的 |
| ★ | 证书 SAN 含 `*.akamaized.net` | 共享证书 | 只能当线索 |
| ✗ | `Server: AkamaiGHost` / `X-Akamai-Transformed` | — | **放行时 Akamai 会透传源站 Server 头**，只在被拦那一刻才出现 |

**为什么较真分母**：被放行时响应头来自源站，拿 `server` 头统计会把大量
Akamai 站算成"没有 Akamai"。分母错了，通过率就没有意义。

### 1.2 有没有闸 —— 不看状态码

```
GET 目标路径 → status 是多少都不重要 → 只看 body：
    is_interstitial(body)  → 有闸（2–7KB 壳，含 bm-verify + _sec/verify）
    content_like(body)     → 真内容（无闸，或已放行）
    两者都不 → 别的形态，查 §2.1 的十六种表
```

壳和正常页**都是 200**。把状态码当判据是这一档最经典的误判。

### 1.3 闸在哪条路径 —— A / B / C 三种作用域

| 形态 | 表现 | 采集策略 |
|---|---|---|
| **A 整站闸** | 所有真实路径都返壳 | 必须走求解器 |
| **B 仅根路径** | 只有 `/` 返壳，子路径直通 | 采集端不需要求解器 |
| **C 路由级** | 一部分路由闸、一部分通（高频是 `/search*`） | 只有那条路由要过闸 |

两条必须遵守的探法：

- **每条路由一个全新会话**。复用会话会把 A 形误判成 B 形。
- **带对照路径**（一条确定不存在的）。否则 catch-all 站会被误判成"可直采"。

所以"这站有没有闸"是错问题，正确问法是"**我要的那条路径有没有闸**"。

### 1.4 五个盲区：会把"有"看成"没有"

| 盲区 | 症状 | 怎么办 |
|---|---|---|
| **apex SNI 挂起** | `curl(28)` 超时，但 `www.` 0.2s 回壳（两者同一对 IP） | 换 `www.`；把连接超时压到 8s |
| **假 0 命中** | `status` 全空、`len` 全 0、错误清一色 `curl(7)` | **一个响应都没拿到 ≠ 这批没闸**；降并发重跑 |
| **只打 `/`** | C 形站在所有首页扫描里都记成"无闸" | 用多路由扫描补 |
| **单次 ERR** | 样本轮是通、全量轮是 ERR | ERR 单独计数，不并进 PASS，关键队列补扫 |
| **小壳启发式** | 247 + `rbzns` / `winsocks` 这类别家 WAF | 判据必须**多个标记同时成立**，不能简化成"小 body = 挑战页" |

---

## 二、分析：拿到一个响应，按这张表判

### 2.1 十六种响应形态

| # | 响应长相 | 判据 | 是什么 | 处置 |
|---|---|---|---|---|
| 1 | 200 · 2–7KB · `bm-verify` + `_sec/verify` | `is_interstitial` | **interstitial 壳** | 可解（主线） |
| 2 | 200 · ~1KB · `Challenge Validation` + `provider="recaptcha"` | `id="sec-cpt-if"` | reCAPTCHA 挑战 | **墙** |
| 3 | 200 · ~1.8KB · `provider="crypto"` + `challenge="<b64>"` | 同上 + `provider` | PoW 挑战 | 理论可算，未实现 |
| 4 | 200 · 大页面 · `/akam/\d+/[a-z0-9]+` | compact 正则 | 正常页 + 传感器 | **不是闸** |
| 5 | 429 · `Bot or Not` | 字面 | 经典 sensor 严格模式 | 站方自建，别家专题 |
| 6 | 403 · ~370B · `Access Denied` | 短版 | 瞬时限流 / 路径硬拒 | 换会话重试；**可解** |
| 7 | 403 · 2.4–3.4KB · `Access Denied` + `Reference` | 长版参考页 | 限流升级，约 20 分钟自愈 | 重试；**可解** |
| 8 | 202 · ~2KB · `server: CloudFront` | 响应头 | Amazon 族 DNS 摆动 / 前置 AWS WAF | **不是 Akamai 的锅**，剔分母 |
| 9 | 247 · ~570B · `rbzns` / `winsocks` | 字面 | 别家 WAF | 不是 Akamai |
| 10 | `Just a moment` | 字面 | Cloudflare | 别家 |
| 11 | `Pardon Our Interruption` / `px-captcha` | 字面 | PerimeterX | 别家 |
| 12 | `captcha-delivery.com` | 字面 | DataDome | 别家 |
| 13 | 401 + `www-authenticate` | 响应头 | **闸已过**，源站要 Basic Auth | `gate=passed` |
| 14 | 503 + 维护页 | 状态码 | **闸已过**，源站维护 | `gate=passed` |
| 15 | 200 + `<title>` + 正文（>800 字或 >20KB） | `content_like` | 真内容 | 收工 |
| 16 | 200 · <8KB · 无壳无 title | 兜底 | 停车页 / JS 跳转 / 极简落地页 | 人工看一眼 |

1、3、8、15 有真实夹具；其余形态由 `content_like` 的 block marks 与
`classify_sensor` 的 evidence 断言覆盖。

### 2.2 是不是 interstitial 壳：三个条件同时成立

```python
"bm-verify" in body[:40960] and ("_sec/verify" in body or "interstitial" in body)
```

- 窗口是 **40KB 不是 6KB**（flaticon 的 `_sec/verify` 在 6,110 字节）；
- **不看状态码**；壳体积也是指纹：2.1–2.3KB（纯 interstitial）/ 6.9KB（带 Magnific iframe）；
- 只满足一个标记的（247 那类、普通文档页）都不算。

### 2.3 变体分型：五个变体各怎么测出来

| 变体 | 怎么测 | 判据 | 代表 |
|---|---|---|---|
| **A0** 参数存在即放行 | **全新会话** `GET /?bm-verify=`（空值） | 直接出内容 | Inditex 系、部分 Amazon 边缘 |
| **A** qparam 容忍 | 取过壳后 `?bm-verify=<随便>` | 出内容；POST 的 token 值也不校验 | zara / iberdrola |
| **B** POST 专用 | 全新会话 POST | 只认 POST；先发 qparam 会 **403 并弄脏会话** | flaticon / bike24 |
| **canonical** 别名 | 看 POST 的 `Set-Cookie: Domain=` / `/_sec/verify` 是否 404 | Domain 不属于当前 host，或端点没挂 | zara.it → zara.com/it |
| **cross-origin** 门面 | POST 回来的是 **HTML 壳而不是 JSON** | 壳里有 `challenge.<apex>` iframe | iconfinder → magnific |

两个附加事实：

- **A0 只对 interstitial 站生效**：403 的 Akamai 站（GEO/ACL）加参数只多 5 字节 URL 回显；
- **A0 仍需 TLS 指纹**：裸 `requests` 在 nh-hotels 上 403/380B，
  `curl_cffi impersonate="chrome"` 239KB。

### 2.4 闸 vs 墙

| 类别 | 例子 | 能不能解 |
|---|---|---|
| **闸** | interstitial 壳、短/长 `Access Denied` | 能，本项目主线 |
| **墙** | reCAPTCHA 挑战、geo-block、叠加 PX / CF / DataDome | 不能（要人机 / 换当地 IP / 别的专题） |
| **不是门** | CloudFront 202、247 别家 WAF、维护页 | 别当失败，按 §2.5 归因 |

判据不是"看着像墙"，而是**有没有可执行的通关动作**：有 token 能算、
有端点能 POST 的才是闸。

### 2.5 "没内容"的三种归因（最容易写错报告的地方）

| 现象 | 根因 | 该记成 |
|---|---|---|
| 复查还是同一个壳 | **闸没开** | 求解失败 |
| `{"reload": true}` + 壳消失 + 内容短 / 401 / 503 | **闸开了，源站没内容** | `gate=passed`（不是失败） |
| 首页干净、某条路由返壳 | **内容在别的路径**（C 形） | 换路径，不是失败 |

仓库样本里就有三条：kasikornbank 过闸后是 6,182B 通告、training.oysho 是
4,105B 短页、wb-ookura 过闸后 503。它们**都不该记求解失败**，否则排查会被
带偏去查 token。

---

## 三、解决：用哪条命令、失败看哪里

### 3.1 默认路径

```bash
python -m gatekit solve  https://www.example.com/          # 单站，L1 → L2i
python -m gatekit fetch  https://www.example.com/ -o page.html   # 过闸后取数
```

分层是**从便宜到贵**，不是从强到弱：L1 直连几秒 → L2i interstitial。
本项目不含 L2a/L2b（需要按站补 Node 环境的传感器层）。

### 3.2 兜底顺序不能反

```
POST → 跨源中枢（challenge.<apex> → www.<apex>）→ 规范域（Set-Cookie Domain / 去 ccTLD 换 .com）→ qparam
```

| 顺序 | 为什么必须在这 | 反了会怎样 |
|---|---|---|
| POST 在最前 | B 型只认 POST | 先发 qparam → 403 + 会话被弄脏，随后的 POST 也失效 |
| 跨源中枢在 qparam 前 | `wrong_origin` 是强信号 | qparam 在这类站必然白跑 |
| 规范域在 qparam 前 | 别名 host 的 cookie 存不下 / 端点 404 | 挑战死循环，重试多少次都是壳 |
| qparam 最后 | 只有 A 类站认 | 仅 A 型有效，且必须先 GET 一次壳重建挑战状态 |

### 3.3 排障表：症状 → 根因 → 动作

| 症状 | 根因 | 动作 |
|---|---|---|
| `curl(28)`，apex 挂、www 快 | apex SNI 被静默挂起（同一对 IP） | 换 www；连接超时压到 8s |
| 全批 `status=None`、清一色 `curl(7)` | 环境问题（并发打满 DNS） | **不是 0 命中**，降并发重跑 |
| `403 + 373B Access Denied` | 瞬时限流，约 20 分钟自愈 | 换 www → 新会话重试 ≤3 |
| `403 + 2.4–3.4KB` 参考页 | 限流升级 | 同一条重试路径 |
| POST 回 `{"reload":true}` 但复查仍是壳 | cookie 的 Domain 不属于当前 host；或 POST 打到了重定向前的 host | 规范域兜底；**base 必须跟 `r.url`** |
| POST 回 HTML（不是 JSON） | 打到了门面站 | 跨源 hub：`challenge.<apex>` → `www.<apex>` |
| `curl(47)` 重定向循环 | 边缘轮换级不稳定 | 原样重试一次 → `allow_redirects=False` 手动跟 ≤3 跳 |
| POST 后 0.6s 还是壳 | Magnific 系轮换 `ak_bmsc`，1s 后才可读 | 四档复查 0.6 / 1.0 / 1.5 / 2.0s |
| A0 探针 403 / 378B | **硬拒 ≠ 站解不开** | 退回完整 L2i |
| A0 探针进 30 次重定向 | **探针异常 ≠ 站点解不开** | 退回 POST |
| 17KB 真首页被判"没内容" | 字节阈值误杀 | 用 `content_like()`，别改阈值 |
| 6KB 通告页被判 FAIL | 同上 | 记 `gate=passed` + `origin_status` |
| 复查出 401 / 503 | 闸已过，源站自己的事 | `gate=passed`，别再查 token |
| 反复重试仍 403，且同形态成批 | 可能是永久 ACL / GEO（**与瞬时限流字节完全相同**） | 隔一段时间复测；未复测只能记"未通过" |
| 并发 > 8 后 403 变多 | 自己把自己打成限流 | 降到 8 以下 |
| 同一份语料两个通过率 | 分母没剔 Amazon / 用了 server 头 | 只认 `inventory` 的五桶口径 |
| 改了 base 还是很慢 | 下游还在拿入参 URL | **凡是改写 base，全量搜下游** |

### 3.4 验证四步（别跳）

```bash
python tests/test_offline.py                              # 1. 判据没坏（30 条，秒级）
python -m gatekit solve URL                               # 2. 单站真跑
python -m gatekit fetch URL -o /tmp/x.html                # 3. 过闸后真有数（体积/标题）
python -m gatekit inventory --sweep ... --json auto       # 4. 落快照，下轮 --diff
```

判据改一行也要走这四步：**离线 → 单站 → 取数 → 口径**。

---

## 四、遇到没见过的形态怎么办

新形态一定会遇到。方法比结论值钱。

### 4.1 四条铁律

| 原则 | 具体做法 | 反例 |
|---|---|---|
| **阴性对照** | 空 token / 不取壳直接 POST / `pow` 改 0，各跑一遍 | 只测成功路径，分不清"校验了什么"和"什么都没校验" |
| **一次只改一个变量** | 先固定会话、再固定 host、再改路径 | 同时换 IP + 指纹 + UA，出结果也归不了因 |
| **单次 ≠ 结论** | 关键结论 3 次复测；ERR 单独计数并补扫 | 样本轮是通、全量轮是 ERR，只看一份就是假阴性 |
| **字节级验证** | 自洽回环不算数，要和真实响应逐字节比 | "我自己加密自己解密都对"是最骗人的中间结论 |

### 4.2 沉淀三件套（当天做完）

1. **记一条**：结论 + 支撑实验 + **反例**（只写结论的那种，半年后没人敢信）；
2. **能离线测的就加断言**：放进 `tests/test_offline.py`，用落盘的真实响应当夹具；
3. **登记产出**：脚本 / 夹具写清"来源 / 抓取时间 / 代表什么 / 怎么脱敏"。

---

## 五、一次完整走查：`2ndstreet.jp`（C 形）

```bash
# ① 探测：首页 200 / 237KB / shell=False —— 所有只按首页判定的工具都会记"无闸"

# ② 分析：五条路由，每条一个全新会话
/                                200   237,435B  shell=False
/search?category=810032          200     2,297B  shell=True   ← 只有这条
/contact                         200    80,228B  shell=False
/login                           200   237,435B  shell=False
/store                           200   230,322B  shell=False

# ③ 解决：直接把子路由丢给求解器（不绑死 /）
python -m gatekit solve "https://2ndstreet.jp/search?category=810032"
#   → 3.2–3.4s 拿到 695,084B 搜索结果页

# ④ 验证：把它当 C 形样本加进自己的回归
```

**这一站说明三件事**：

1. 探测只打 `/` 是结构性盲区；
2. 分析的核心是**逐路由判**，不是判站点；
3. 解决只需 3 秒——**难的不是求解，是知道该解哪条路由**。

---

返回 [docs 索引](README.md) · [仓库根目录](../README.md)。
