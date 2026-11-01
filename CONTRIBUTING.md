# CONTRIBUTING

> 这个仓库的重心是**判据**，不是覆盖面。一个能解释清楚的失败形态，比十个
> "我这边能跑"的站点更有价值。

---

## 1. 可以提什么

| 类型 | 欢迎程度 | 说明 |
|---|---|---|
| 新的响应形态（附脱敏抓包） | ⭐⭐⭐ | 尤其是判据判错的：请附期望 vs 实际 |
| 判据 bug / 误判 | ⭐⭐⭐ | 必须附一个能离线复现的最小 body |
| 文档修正（流程、字段、结论） | ⭐⭐⭐ | 特别是"为什么"写错的地方 |
| 新的变体解法（A0/A/B/canonical/hub 之外） | ⭐⭐ | 先开 issue 描述现象，再写代码 |
| classic sensor / captcha / PX / CF / DataDome 求解 | ❌ | 超出范围，见 [BOUNDARIES](docs/BOUNDARIES.md) |
| 站点清单、"能爬 XX 站"的 PR | ❌ | 不收录语料 |

## 2. 提交判据改动

判据在 `gatekit/judges.py`，全部是纯函数。改它必须同时做到：

1. **加一条离线断言**（`tests/test_offline.py`），写明旧行为为什么错；
2. 跑 `python tests/test_offline.py`，30+ 条必须全绿；
3. 在 PR 描述里贴出：改动前的判定、改动后的判定、用的输入是哪份夹具。

没有断言的"修复"在下一轮很容易被改回去。

## 3. 添加夹具

1. 抓包后**只保留响应正文**，不要提交 `Cookie` / `Set-Cookie` 的有效值；
2. 确认不含个人数据（邮箱、电话、姓名、账号、订单）；
3. 在 `data/fixtures/MANIFEST.md` 登记：来源 URL、抓取时间（UTC+8）、
   字节数、sha256、代表什么；
4. 大文件截断（建议 ≤64 KB），并在登记表里写明截断方式；
5. 如果夹具会改变既有断言，更新断言而不是删掉断言。

复核：

```bash
python - <<'PY'
import hashlib, glob, os
for p in sorted(glob.glob("data/fixtures/**/*.html", recursive=True)):
    b = open(p, "rb").read()
    print(f"{os.path.basename(p):32s} {len(b):7d}  {hashlib.sha256(b).hexdigest()}")
PY
```

## 4. 代码风格

- Python 3.9+；只用标准库 + `curl_cffi`；
- `judges.py` **不得**引入网络、时钟、文件系统依赖——它是离线可测的基础；
- 网络代码放 `interstitial.py` / `client.py`，并且要能接受 `proxy=""`（直连）；
- 不新增运行时依赖，除非有不可替代的理由（TLS 指纹是唯一已有的例外）。

## 5. 不要做的事

- 不要提交全量扫描结果、cookie jar、HAR、session 快照；
- 不要在 CI 里跑真站（挑战依赖实时 token 与网络，结果不可重复）；
- 不要为了"支持更多站"放宽 `content_like` 或加白名单——先写清判据；
- 不要在 PR 里贴有效 token、真实账号或目标的私有接口。

## 6. 调试一个新形态的顺序

1. `python -m gatekit probe URL` —— 先看被判成什么；
2. 判据看起来不对 → 保存 body 到 `data/fixtures/real/`，写一条断言复现；
3. 判据对但求解失败 → 看 `solve` 输出里的 `trace` / `variant` / `*_err`；
4. 走到兜底仍失败 → 按 [BOUNDARIES §7](docs/BOUNDARIES.md) 附材料开 issue。

提交前最后跑一次：

```bash
python tests/test_offline.py
python -m gatekit inventory --sweep examples/sample_sweep.json
```
