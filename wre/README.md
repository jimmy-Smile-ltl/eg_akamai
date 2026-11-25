# wre 专题：proofofbots/web-re-toolkit 的 Akamai 实践

这是 `eg_akamai` 下的独立子专题，记录对第三方工具
[`proofofbots/web-re-toolkit`](https://github.com/proofofbots/web-re-toolkit)
（PyPI `wre-client-akamai` 3.1.1，MIT）的安装、选站、批量测试与结论。

**它不是 gatekit 的一部分，也不改变 gatekit 的支持范围。** gatekit 仍然只做
interstitial `bm-verify`；wre 面向的是 classic V2/V3 sensor，两者互补、不重叠。
本专题存在的意义，是把"这个工具到底能干什么、代价多大、在哪里失效"变成
一份可复查的证据，而不是二手宣传。

测试日期 **2026-11-25**，Windows 11 x64 / Python 3.12.3 / 国内网络直连、
无代理、串行访问公开首页。结果只代表该时点的观察。

---

## 结论速览

| 问题 | 答案 |
|---|---|
| 能安装吗 | ✅ PyPI wheel，带 61MB `wred.exe` sidecar；直连 PyPI 易断流，清华镜像一次成功 |
| 覆盖 classic V2/V3 sensor 吗 | ✅ 是它的主目标；官方另称 pixel ✅、PoW 未实测、interstitial ❌ |
| 在真实站上效果如何 | **27 个 protected 站中 3 个**产出 validated `_abck`（11.1%） |
| 有真实的页面增量吗 | **2 个确凿**：APA 酒店 4/4、akamai.com 2/2，均 curl 403 → 200 |
| 能解 interstitial / bm-verify 吗 | ❌ 完全不覆盖，直接报 `Unsupported` |
| 官方 demo 能跑吗 | ❌ Lee County 从本机 403，脚本没有执行机会 |
| 代价 | 61MB 二进制、单进程 200MB+ 内存、成功 6–10s、失败最长 125s |

一句话：**工具是真的，能力也是真的，但泛化成功率约 11%，真正"curl 403 → 200"
的增量案例只有个位数。** 官方验证过的 Xero / Lee County 是最好样本，不是市场平均。
268 名单之外另验证了 Xero 登录页与 akamai.com，两者都产出了 validated `_abck`。

---

## 先读哪里

| 文件 | 内容 |
|---|---|
| [`REPORT.md`](REPORT.md) | 完整测试报告：方法、268 站扫描、27 站求解、失败分类、实验与合规 |
| [`report.html`](report.html) | 可视化版（本地打开）：268 行台账、筛选/搜索、分段统计 |
| [`results/results_all.csv`](results/results_all.csv) | 268 站总表，一行一站，含 verdict 与 increment |
| [`scripts/`](scripts/) | 全部测试脚本，共享 `_paths.py` |

可视化页的数据由 `scripts/build_visual_data.py` 从 `results_all.csv` 生成到
`report_data.js`，不手工维护第二份台账。

---

## 目录结构

```text
wre/
├── README.md                 # 本页
├── REPORT.md                 # 完整报告
├── report.html               # 可视化报告（可离线打开）
├── report_data.js            # 268 行台账数据（构建产物，随页面一起用）
├── requirements.txt          # wre-client-akamai==3.1.1
├── scripts/                  # 14 个脚本 + _paths.py
└── results/                  # discover / solve / repeat 原始 JSON 与总表
```

**不随仓库发布**：隔离 venv、`wred.exe`（61MB）、`_report_rows.json`、
任何 cookie jar / HAR / session 快照。

---

## 复现

```bash
# 1. 隔离环境（仓库不包含 venv 与二进制）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r wre/requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120

# 激活（cmd: .venv\Scripts\activate.bat；PowerShell: .venv\Scripts\Activate.ps1；
# Git Bash / Unix: source .venv/Scripts/activate）
# 以下命令均假设已激活 .venv

# 2. 单站：先 curl 对照，再 discover + solve + 复查
python wre/scripts/probe.py  https://www.apahotel.com/ solve
python wre/scripts/verify.py https://www.ibm.com/

# 3. 批量 discovery（读 datasets/akamai_customers/sites.csv）
python wre/scripts/screen2.py 0 70

# 4. 对 protected 站批量 solve（含 curl 对照）
python wre/scripts/solve_batch2.py 0 6

# 5. 复跑与重建
python wre/scripts/repeat2.py
python wre/scripts/make_report_data.py
python wre/scripts/build_visual_data.py
```

脚本可从仓库根目录或 `wre/` 下运行；输出固定写到 `wre/results/`。
需要 `curl` 在 PATH 上（对照实验用），Windows 用 `NUL`、其他平台用
`/dev/null`，`_paths.py` 已处理。仅 Windows x64 实测，其他平台未验证。

判定口径：

| 判定 | 条件 |
|---|---|
| `validated` | `_abck` field[1] == `"0"` 且 `validated=True` |
| `unvalidated` | `_abck` 仍为 `-1`，但同 session 页面 200 |
| `increment` | curl 403（或 000）→ wre recheck 200 |
| `failed` | solve 报错 / 超时 / 被 403 |

---

## 与 gatekit 的边界

| 维度 | gatekit | wre |
|---|---|---|
| 靶子 | interstitial `bm-verify` 协议 | classic V2/V3 sensor / pixel |
| 手段 | curl_cffi 单请求 + 协议 POST | V8 realm + 设备/行为/传输仿真 |
| 依赖 | 仅 curl_cffi | 61MB sidecar + V8 |
| interstitial | ✅ 主方案 | ❌ `Unsupported` |

interstitial 语料（107 个 `bm-verify` 壳）继续交给 gatekit；wre 只对
"classic obfuscated sensor + curl 403 + 能产出 payload"的少数站有意义。

---

## 数据与合规

- 样本取自本仓库公开数据集 `datasets/akamai_customers/sites.csv`（2026-09-17 快照，
  268 主机），另加 7 个公开补充样本；只访问公开首页；
- 串行、每站一次 GET，并发 ≤ 2；未登录、未触达付费内容 / 个人数据；
- 匿名首页会话 cookie 只在内存使用，**结果文件只保存状态码与 `_abck` 状态位，
  不保存 cookie 值、token、正文或 HAR**；
- 台账是本专题的一次性评估证据，不是通用扫描语料，也不用于声明 gatekit 的能力；
- 工具输出只作为测试记录，不用于生产采集。使用前请自行确认授权与当地法律要求。

详见 [`REPORT.md`](REPORT.md) §12 与仓库根目录
[`docs/BOUNDARIES.md`](../docs/BOUNDARIES.md)。
