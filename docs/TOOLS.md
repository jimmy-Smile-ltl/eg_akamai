# TOOLS — 命令、API 与输出字段

> 所有命令都可以从仓库根目录直接跑（`python -m gatekit ...`），
> 也可以用 `pip install -e .` 后直接 `gatekit ...`。
> Windows 下若 `python` 指向坏的解释器（例如残留的 Anaconda），用 `py -3.12`。

---

## 1. 命令行

```
gatekit [--version] <command> [options]
```

### 1.1 `probe` — 一次请求，只看被判成什么

```bash
python -m gatekit probe URL [--proxy P] [--impersonate chrome]
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `URL` | — | 可以是路径，如 `https://site/search?q=1` |
| `--proxy` | 直连 | `http://host:port`；没有就不要填 |
| `--impersonate` | `chrome` | `curl_cffi` 指纹：`chrome` / `chrome124` / `safari` / `firefox` / `edge` |

输出（JSON）：

```json
{
  "url": "https://www.zara.com/",
  "status": 200,
  "len": 2122,
  "sensor": "interstitial",
  "locked": true,
  "evidence": ["interstitial_shell"],
  "challenge": {
    "token_len": 268,
    "pow": 2272089155,
    "endpoint": "/_sec/verify?provider=interstitial"
  }
}
```

`sensor` 取值：`interstitial` / `challenge_recaptcha` / `challenge_crypto` /
`compact_v3` / `classic` / `self_captcha` / `null`。只有 `interstitial` 会被
`solve` 尝试；`challenge_*` 是 Akamai 自家的验证码/PoW 墙，只报告不解。
退出码：拿到任何响应即 0；连接失败 1。

### 1.2 `solve` — 按成本从低到高跑

```bash
python -m gatekit solve URL [--layers L1,L2i] [--proxy P] [--impersonate chrome]
```

| 层 | 做什么 | 成本 |
|---|---|---|
| `L1` | 多指纹直连（`chrome` → `chrome124` → `safari` → `firefox` → `edge`） | 1–5 次请求 |
| `L2i` | interstitial 协议（取壳 → A0 → POST → 复查 → 兜底） | 3–15 次请求 |

输出（节选）：

```json
{
  "url": "https://www.zara.com/",
  "solved": true,
  "layer": "L2i",
  "sensor": "interstitial",
  "trace": ["detect:200/interstitial", "L1:...", "L2i:200"],
  "detail": {
    "ok": true,
    "gate": "passed",
    "variant": "standard",
    "status": 200,
    "len": 641405,
    "token_len": 268,
    "pow": 2272089155,
    "verify_status": 200,
    "verify_json": {"reload": true}
  }
}
```

`detail` 里需要特别注意的字段：

| 字段 | 含义 |
|---|---|
| `ok` | 拿到内容（`content_like`） |
| `gate` | `passed` / `shell` / `unknown`；与 `ok` **分开看** |
| `origin_status` | 闸过了但源站没内容时的状态码（401/503） |
| `variant` / `fallback` | 走通的是哪条路（`A0` / `standard` / `qparam` / `canonical` / `hub`） |
| `a0_err` / `canonical_err` / `hub_err` | 兜底尝试的失败原因（排查用） |

退出码：`solved=true` → 0；否则 1。

### 1.3 `fetch` — 过闸后用同一会话取页面

```bash
python -m gatekit fetch URL [-o FILE] [--proxy P] [--impersonate chrome]
```

- `unlock()` 先开闸；`get()` 取目标路径；
- 取数过程中若重新返壳，会自动再解一次（`stats.relock` 计数）；
- `-o` 把正文写入文件（UTF-8，坏字节替换）。

输出：

```json
{
  "url": "https://2ndstreet.jp/search?category=810032",
  "gate": {"ok": true, "variant": "standard", "...": "..."},
  "status": 200,
  "len": 695084,
  "variant": "standard",
  "stats": {"get": 4, "unlock": 1, "relock": 0},
  "saved": "search.html"
}
```

退出码：`gate.ok && status < 400` → 0；否则 1。

### 1.4 `inventory` — 五桶口径 / 快照 / 对比

```bash
python -m gatekit inventory [--sweep FILE] [--data-dir DIR] [--json auto] [--md FILE]
python -m gatekit inventory --diff SNAP_A [SNAP_B]
```

| 参数 | 说明 |
|---|---|
| `--sweep` | 指定 sweep JSON；不填则取 `data/` 下最新的 `corpus_sweep*.json`（≥20 行） |
| `--data-dir` | sweep 与快照的目录，默认 `./data`（可用环境变量 `GATEKIT_DATA`） |
| `--json auto` | 写快照到 `data/inventory_<YYYYmmdd_HHMM>.json` |
| `--json PATH` | 写到指定路径 |
| `--md FILE` | 另存 Markdown 表 |
| `--diff A B` | 对比两份快照；只给 A 时 B 取最新 |

输出（仓库自带的 24 行样本）：

```
[sweep] examples/sample_sweep.json
  gated hosts 24: Akamai-native 20 / front AWS WAF 2 / DNS flip 2 (probe saw Akamai, re-run)
  Akamai-native 20 -> content PASS 17 / gate-only 3 / fail 0
  gate 20/20 = 100.0%   content 17/20 = 85.0%
```

sweep 行格式（与 `solve` 的结果兼容，最小只需 `host` + 判定字段）：

```json
{"host": "www.example.com", "status": 200, "len": 51234,
 "ok": true, "gate": "passed", "err": "",
 "vendor": {"vendor": "akamai"}}
```

五桶见 [PLAYBOOK §2.5](PLAYBOOK.md)；分母 = 行数 − `FRONT-WAF` − `ENV-FLIP`。

---

## 2. Python API

### 2.1 判据（零依赖）

```python
from gatekit import judges
```

| 函数 | 输入 | 输出 |
|---|---|---|
| `is_interstitial(body)` | `str \| None` | `bool` |
| `parse_interstitial(html)` | `str` | `{"bm_verify", "pow", "endpoint"} \| None` |
| `content_like(body)` | `str \| None` | `bool` |
| `path_entropy(seg)` | `str` | `bool` |
| `looks_classic(path, page_path="")` | `str, str` | `bool` |
| `classify_sensor(body, page_path="")` | `str, str` | `{"sensor", "locked"?, "challenge"?, "sensor_path"?, "evidence"}` |
| `shell_path(html)` | `str` | `str \| None` |
| `cookie_domain_mismatch(resp, host)` | 响应对象, `str` | `str \| None`（不匹配的 Domain） |
| `canonical_remap(url, shell_html, resp=None)` | `str, str, resp?` | `list[str]` |
| `cloudfront_draw(resp)` / `hard_block(resp)` | 响应对象 | `bool` |

### 2.2 网络

```python
from gatekit import detect, solve
from gatekit.interstitial import solve_interstitial, direct_get
```

| 函数 | 用途 |
|---|---|
| `detect(url, proxy=None, impersonate="chrome")` | 一次 GET + 分类，不重试 |
| `direct_get(url, proxy=None)` | L1 多指纹矩阵 |
| `solve_interstitial(url, proxy=None, impersonate="chrome")` | 只跑 L2i 协议 |
| `solve(url, proxy=None, layers=("L1","L2i"), do_detect=True, ...)` | 分层调度 |

### 2.3 客户端

```python
from gatekit.client import InterstitialClient

c = InterstitialClient(base, proxy=None, impersonate="chrome", timeout=45)
c.unlock(path="/")            # -> dict(ok, variant, ...)
status, html = c.get(path)    # 自动带 A0 参数 / 自动再解
c.stats                       # {"get": n, "unlock": n, "relock": n}
```

`base` 是 origin（如 `https://www.example.com`），不带路径。
`proxy=None` / `""` 表示直连——**默认直连**，避免默认死代理把所有站判死。

### 2.4 口径

```python
from gatekit import inventory as inv

inv.classify(row)                         # -> PASS / GATE-ONLY / FRONT-WAF / ENV-FLIP / FAIL
inv.build_snapshot(rows, sweep_path)      # -> dict
inv.compare(a, b)                         # -> {"added", "gone", "good", "bad", "other"}
inv.report(rows, sweep_path)              # -> str
inv.diff_text(a, b)                       # -> str
inv.latest_sweep(None, data_dir="data")   # -> path | None（跳过 smoke run）
inv.save_snapshot(snap, "auto", data_dir="data")
```

---

## 3. 退出码

| 命令 | 0 | 1 |
|---|---|---|
| `probe` | 有响应（无论判定） | 连接失败 |
| `solve` | `solved=true` | 未解出 |
| `fetch` | 过闸且状态 <400 | 过闸失败或目标 4xx/5xx |
| `inventory` | 正常输出 / diff 完成 | 参数或文件错误 |

`fetch` 在"闸开了、源站 401"时返回 1，但输出里的 `gate.ok` 为真——脚本里应
**分开读** `gate.ok` 与 `status`，不要只看退出码。

---

## 4. 夹具与样本

| 路径 | 内容 |
|---|---|
| `data/fixtures/real/` | 7 份真实响应（壳 / 负样本 / 内容摘录） |
| `data/fixtures/synthetic/` | 3 份构造响应（小页 / 大页 / compact 传感器） |
| `data/fixtures/MANIFEST.md` | 来源、抓取日期、体积、sha256、代表什么 |
| `examples/sample_sweep.json` | 24 行真实结果摘录，覆盖五种桶 |
| `datasets/akamai_customers/` | akamai.com 公开客户清单与采集/检测脚本；不参与 gatekit 判据 |

离线回放示例：

```python
import io
from gatekit import judges
html = io.open("data/fixtures/real/flaticon_shell.html", encoding="utf-8").read()
print(judges.is_interstitial(html))       # True
print(judges.parse_interstitial(html))    # token 308 / pow 2751614010
```

---

## 5. 测试

```bash
python tests/test_offline.py        # 30 条，不联网
python tests/test_offline.py -v     # 逐条打印
```

不依赖 pytest；返回码 0/1，可直接进 CI。真站回归**不随仓库发布**——它需要
网络和实时挑战，属于使用者自己的环境。

---

返回 [docs 索引](README.md) · [仓库根目录](../README.md)。
