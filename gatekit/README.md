# gatekit/ — 代码结构

一个可安装的 Python 包，按**四层**拆分。每层只回答一个问题，且能单独测。

```text
cli.py  __main__.py  __init__.py     ← 入口 / 懒加载
   │
   ├── interstitial.py ──→ judges.py  ← 求解：取壳、解析、POST、复查、兜底
   ├── client.py ────────→ judges.py  ← 会话：过闸后复用同一会话取页面
   └── inventory.py                   ← 口径：五桶、快照、隔轮 diff
```

| 文件 | 层 | 职责 | 发请求 | 依赖 |
|---|---|------|:---:|---|
| [`judges.py`](judges.py) | 判据 | 壳 / 内容 / 传感器 / 规范域 / 解析 token | ❌ | 标准库 |
| [`interstitial.py`](interstitial.py) | 求解 | L1 多指纹直连 + L2i interstitial 协议 | ✅ | `curl_cffi` |
| [`client.py`](client.py) | 会话 | `unlock()` / `get()`，重锁自动再解 | ✅ | `curl_cffi` |
| [`inventory.py`](inventory.py) | 口径 | `PASS` / `GATE-ONLY` / `FAIL` / `FRONT-WAF` / `ENV-FLIP` | ❌ | 标准库 |
| [`cli.py`](cli.py) | 入口 | `probe` / `solve` / `fetch` / `inventory` | — | 以上全部 |
| [`__init__.py`](__init__.py) | 包 | 懒加载导出；`import gatekit.judges` 不要求装 `curl_cffi` | — | — |

## 三条硬约束

1. **`judges.py` 是纯函数层**：不发请求、不读时钟、不碰文件系统。
   整个离线回归（30 条断言）只依赖它和夹具；
2. **网络代码必须接受 `proxy=None` / `""`**，默认直连。默认死代理会把所有站判死；
3. **不新增运行时依赖**。`curl_cffi` 是唯一例外，因为 TLS 指纹不可替代。

## 常用入口

```python
from gatekit import detect, solve
from gatekit.client import InterstitialClient
from gatekit import judges
```

完整签名与输出字段见 [docs/TOOLS.md §2](../docs/TOOLS.md#2-python-api)。

## 改代码之前

- 判据改动：先在 `tests/test_offline.py` 加一条能复现旧行为错误的断言；
- 新增形态：先让 `classify_sensor` 能**识别**，再谈求解；
- 提交前：`py -3.12 tests/test_offline.py`，30 条必须全绿。

返回 [仓库根目录](../README.md)。
