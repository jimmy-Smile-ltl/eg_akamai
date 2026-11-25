# proofofbots/web-re-toolkit 实测报告

> 被测：`wre-client-akamai` 3.1.1（proofofbots/web-re-toolkit，MIT）
> 测试日期：2026-11-25 · 环境：Windows 11 / Python 3.12.3 / 国内网络直连（无代理）
> 样本：`datasets/akamai_customers/sites.csv` 全部 **268 个 Akamai 公开客户主机**，另加 7 个补充样本
> 归属：`eg_akamai/wre/` 专题 —— 第三方工具评估，不改变 gatekit 的支持范围
> 记录目的：判断该工具能否用于 Akamai classic sensor 站，以及与 gatekit（interstitial）的边界

---

## 1. 摘要

| 问题 | 答案 |
|---|---|
| 能安装吗 | ✅ PyPI `wre-client-akamai` 3.1.1，有 win_amd64 wheel；清华镜像 11MB/s |
| classic V2/V3 sensor 能过吗 | **部分**：27 个 protected 站中 **3 个**产出 validated `_abck`（11.1%） |
| 有真实页面增量吗 | **2 个确凿**：APA 酒店 3/3（403→200，482KB）、akamai.com 2/2（403→200，219KB） |
| 解 interstitial / bm-verify 吗 | ❌ 完全不覆盖（zara / flaticon / nh-hotels 均 `Unsupported`） |
| 官方 demo 能跑吗 | ❌ 官方 Lee County 脚本从本机 403，`answered 403 before any script ran` |
| 代价 | 61MB 二进制、单进程 200MB+ 内存、成功 6–10s、失败最长 125s |

**一句话**：工具是真的，能力是真的，但泛化成功率约 11%，且真正"curl 403 → 200"的增量案例只有个位数。它验证过的 Xero / Lee County 是最好样本，不是市场平均水平。

---

## 2. 被测对象

| 项 | 值 |
|---|---|
| GitHub | `proofofbots/web-re-toolkit`，MIT，Rust |
| PyPI | `wre-client-akamai` 3.1.1 → `wre-runtime` 3.1.1 |
| 二进制 | `site-packages/wre_client_akamai/bin/x86_64-pc-windows-msvc/wred.exe`，**61,314,560 bytes** |
| 架构 | 本地 sidecar（`wred`）+ V8 realm 执行厂商 sensor 脚本 + 录制的 Mac 设备/行为/传输指纹 |
| 官方覆盖 | V2/V3 sensor ✅、pixel ✅、PoW 实现但未验证、**interstitial/bm-verify ❌**、access-denied 非独立 solver |
| 官方验证站 | 仅 Xero login、Lee County search |

---

## 3. 测试方法

统一四步口径（每站一次 GET，串行，低并发）：

```text
1. curl 裸测         Chrome UA、无 cookie
                     → 403/000 才说明存在"裸请求会被拒"的保护
2. wre discover      protected=True + sensor=obfuscated 才算候选
3. wre solve         产出 _abck、posts、telemetry
4. wre request       同 session GET 复查，记录 status / 长度
```

判定口径：

| 判定 | 条件 |
|---|---|
| `validated` | `_abck` field[1] == `"0"` 且 `validated=True` |
| `unvalidated` | `_abck` 仍为 `-1`，但同 session 页面 200 |
| `increment` | curl 403（或 000）→ wre recheck 200 |
| `failed` | solve 报错 / 超时 / 被 403 |

---

## 4. 安装记录

```bash
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install wre-client-akamai \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120
```

- 直连 PyPI：`ReadTimeoutError`（files.pythonhosted.org 断流）
- 清华镜像：22.8MB wheel，10.9MB/s，一次成功
- 解压后 `wred.exe` 61MB（V8 静态链接）
- 启动耗时 0.3–3.7s；首次运行无额外下载
- 记录位置：`eg_akamai/wre/`（本仓库子专题）；隔离 venv 与 61MB 二进制不随仓库发布

---

## 5. 扫描结果（268 站）

| 项 | 数量 |
|---|---|
| discover 总数 | 268 |
| `protected=True` | **27（10.1%）** |
| 其中 `sensor=obfuscated` | 21 |
| 其中 `sensor=sensor`（非 obfuscated） | 6：panasonic、crownmedia、britishcouncil、lacity、esky、rosebikes |
| 无保护 / 连接失败 | 241 |

27 个 protected 站：

`digital.panasonic.co.jp`（kind=sensor）、`www.ana.co.jp`、`www.apahotel.com`、`bmo.com`、`www.bio-techne.com`、`corporate.crownmedia.com`（sensor）、`mailchimp.com`、`www.douglas.de`、`www.emc.com`、`www.esky.com`（sensor）、`www.guardicore.com`、`www.ibm.com`、`starhealth.in`、`www.britishcouncil.org`（sensor）、`www.domain.com.au`、`www.gia.edu`、`www.lacity.org`（sensor）、`www.itv.com`、`www.kleinanzeigen.de`、`www.princess.com`、`www.riachuelo.com.br`、`www.rosebikes.de`（sensor）、`www.tokopedia.com`、`www.usnews.com`、`www.xcaret.com`、`www.xero.com`、`www.yatra.com`

---

## 6. 求解结果（27 站）

### 6.1 `_abck` validated（3 个 + 复现）

| 站点 | curl | `_abck` | 复查 | 复现 |
|---|---|---|---|---|
| **www.ibm.com** | 303 | **0** | 200 / 214,173 | **3/3**（6.0–7.6s，214,173 字节一致） |
| **www.britishcouncil.org** | 000 | **0** | 200 / 101,830 | **2/3**（第二次 -1，页面不变） |
| **www.tokopedia.com** | 200 | **0** | 200 / 113K | **3/3** |

补充样本（不在 268 名单内）：

| 站点 | curl | `_abck` | 复查 | 说明 |
|---|---|---|---|---|
| `login.xero.com` | 200（-L 同值） | **0** | 200 / 43,195 | 页面无增量；仅证明 sensor 能算成 0 |
| `www.akamai.com` | **403** | 0（1/2） | 200 / 219K | **确有增量**；第二次 -1 但页面仍 200 |

### 6.2 真实页面增量（curl 403 → wre 200）

| 站点 | increment | `_abck` | 复查 | 复现 |
|---|---|---|---|---|
| **www.apahotel.com** | **403→200** | -1 | 200 / 482,454（首测）/ 482,440（3 次复跑） | **4/4 页面 200**，复跑 size 逐字节一致 ✅ |
| **www.akamai.com** | **403→200** | 0（1/2） | 200 / 219K | 2/2 页面 200 ✅ |
| www.riachuelo.com.br | 403→200 | -1，posts=0 | 200 | 1/1；posts=0 可疑 |
| www.xcaret.com | 403→200 | solve 报 `sandbox stalled` | 200 | 1/1；可能为假象 |

`000→200`（curl 本身连不上，不能确认是工具带来的增量）：britishcouncil、yatra、bio-techne、itv、usnews。

### 6.3 `_abck` 未验证但页面 200（8 个）

mailchimp、ANA、APA、guardicore、kleinanzeigen、riachuelo、xero.com 主站、yatra。
其中 ANA 发了 **183 个 posts** 仍 `-1`（空转）。

### 6.4 solve 失败（16 个，59%）

| 类型 | 站点 |
|---|---|
| `the sensor produced no payload`（5） | bio-techne、crownmedia、lacity、rosebikes、usnews |
| solve 超时 125s（4） | bmo、domain.com.au、gia.edu、esky |
| solve 被 403 拒（3） | starhealth.in（curl 308，复查 403）、douglas.de（curl 400）、emc.com（curl 301） |
| `the sandbox stalled`（3） | itv.com、princess.com、xcaret |
| 脚本执行错误（1） | digital.panasonic.co.jp |

补充样本失败：

| 站点 | 现象 |
|---|---|
| `www.adidas.com/us` | `answered 403 before any script ran`（IP 层拒绝，脚本没机会执行） |
| `matrix.leeclerk.org`（官方 demo 站） | 同上；**官方 demo 脚本在本机不可用** |
| `www.zara.com` / `www.flaticon.com` / `www.nh-hotels.com` | `Unsupported: names no Akamai sensor script`（interstitial 壳内无 sensor 脚本） |

---

## 7. 关键实验

### 7.1 通过靠 TLS/H2 指纹，不靠 cookie

APA 酒店：从 wre session 导出完整 Cookie 头（2192 字符，含 `HCSESSIONID`、`visitorid`、`_abck`、`bm_sz`）交给普通 curl：

```text
curl 无 cookie     -> 403
curl + wre cookie -> 403
```

**结论**：`wreq-util` 的传输层指纹才是通过原因；这也解释了 `_abck` 仍是 `-1` 时页面照样 200。

### 7.2 `_abck` validated 不稳定

| 站点 | 成功率 |
|---|---|
| IBM | 3/3 |
| Tokopedia | 3/3 |
| British Council | 2/3 |
| Xero login | 2/2 |
| akamai.com | 1/2 |

同站同参数复现，`_abck` 结果存在随机性；页面 200 反而更稳定。

### 7.3 PoW 分支从未触发

所有站的 `_abck` field[4] 均为 `-1`，与官方文档"PoW 实现了但未在真实站验证"一致。

### 7.4 官方 demo 与实际可用性的差距

官方 demo（`examples/python/akamai_search.py`）代码完整，但依赖的 Lee County 从本机 403；换成 Xero / IBM / British Council 才能跑通。**"demo 完整"≠"任意站可用"**。

---

## 8. 与 gatekit 的边界

| 维度 | gatekit（eg_akamai） | wre |
|---|---|---|
| 靶子 | interstitial `bm-verify` 协议 | classic V2/V3 sensor / pixel |
| 手段 | curl_cffi 单请求 + 协议 POST | V8 realm + 设备/行为/传输仿真 |
| 依赖 | 仅 curl_cffi | 61MB sidecar + V8 |
| 验证样本 | 24 行 + 107 壳 | 268 站实测 3/27 validated |
| interstitial | ✅ 主方案 | ❌ Unsupported |

**结论**：两者互补、不重叠。interstitial 语料（107 个 `bm-verify` 壳）继续交给 gatekit；wre 只对"classic obfuscated sensor + curl 403 + 能产出 payload"的少数站有意义。

---

## 9. 复现步骤

```bash
# 安装到任意隔离环境（仓库不包含 venv 与 61MB wred.exe）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r wre/requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120

# 激活后再执行后续命令
# cmd: .venv\Scripts\activate.bat · PowerShell: .venv\Scripts\Activate.ps1
# Git Bash / Unix: source .venv/Scripts/activate

# 单站：先 curl 对照，再 discover + solve + 复查
python wre/scripts/probe.py  https://www.apahotel.com/ solve
python wre/scripts/verify.py https://www.ibm.com/

# 批量 discovery（读 datasets/akamai_customers/sites.csv）
python wre/scripts/screen2.py 0 70

# 对 protected 站批量 solve（含 curl 对照）
python wre/scripts/solve_batch2.py 0 6

# 稳定性复跑，重建总表与可视化数据
python wre/scripts/repeat2.py
python wre/scripts/make_report_data.py
python wre/scripts/build_visual_data.py
```

所有脚本都能从仓库根目录运行，输出固定写到 `wre/results/`。

---

## 10. 脚本清单

全部位于 `wre/scripts/`，共用 `_paths.py` 定位 `results/` 与 `datasets/`。

| 脚本 | 用途 |
|---|---|
| `probe.py <url> [discover\|solve]` | 单站 discover / solve |
| `verify.py <url>` | solve + 同 session 复查 + 标记检测 |
| `batch.py` | 固定 5 站批量 discover（早期样本） |
| `screen.py` | 51 个日本/欧洲候选 discover |
| `screen2.py <offset> <limit>` | 读 sites.csv 批量 discover，支持增量 |
| `solve_batch.py` | 旧批次 solve |
| `solve_batch2.py <offset> <limit>` | 带 curl 对照的批量 solve，结果可增量追加 |
| `repeat.py` / `repeat2.py` | 稳定性复跑（APA / akamai.com / IBM / BC / Tokopedia） |
| `cookie_probe.py` | cookie vs TLS 对照实验 |
| `make_report_data.py` | 合并全部 JSON → `results/results_all.csv` |
| `build_visual_data.py` | `results_all.csv` → `report_data.js`（可视化台账） |
| `official_demo.py` | 官方 Lee County demo（本机 403 不可用） |
| `summary.py` | 快速打印 protected / solve 汇总 |
| `_paths.py` | 共享路径常量（不是实验脚本） |

---

## 11. 数据文件

均位于 `wre/results/`（可视化页在 `wre/` 根目录）。

| 文件 | 内容 |
|---|---|
| `results_all.csv` | **268 站总表**（host / curl / abck / recheck / verdict / increment） |
| `screen_results.json` | 51 个候选 discover 原始记录 |
| `screen2_results.json` | 217 个候选 discover 原始记录（累计 268） |
| `solve_results.json` | 旧批次 5 站 solve |
| `solve2_results.json` | 27 个 protected 站 solve（含 curl 对照） |
| `repeat_results.json` / `repeat2_results.json` | APA / akamai.com / IBM / BC / Tokopedia 复跑 |
| `../report.html` + `../report_data.js` | 可视化版报告与 268 行台账数据 |
| `../requirements.txt` | 固定到 `wre-client-akamai==3.1.1` |

`results_all.csv` 列：`host, url, industry, location, screen_status, protected, sensor, curl, abck, validated, posts, solve_secs, recheck, increment, verdict, note`

隔离 venv、`wred.exe` 与原始 `_report_rows.json` 不随仓库发布。

---

## 12. 限制与合规

- 全部样本来自 akamai.com 官网公开 customer story 列表（`sites.csv` 快照 2026-09-17），只访问公开首页；
- 串行、每站一次 GET，并发 ≤2，未登录、未触达付费内容/个人数据；
- 匿名首页会话 cookie 仅在内存中使用，未落盘；
- 不 vendor 二进制；venv 与 `wred.exe` 不随仓库发布；台账只作为本专题证据，不用于声明 gatekit 的支持范围；
- 本专题不改变 gatekit 对 classic sensor / interstitial 的边界；
- 工具输出（`abck` 等）只作为测试记录，不用于生产采集。

---

*报告生成：2026-11-25 · 专题位置 `eg_akamai/wre/`*
