# examples/ — 24 行样本账本

`sample_sweep.json` 是从一次真实批量扫描（2026-10-31 ~ 11-01，直连、`curl_cffi`
`impersonate="chrome"`、并发 ≤8）里**原样摘出**的 24 行，覆盖五种桶中的每一种。
它不是构造数据，也不是"最好成绩"：摘录时没有剔除失败行。

## 1. 为什么只有 24 行

全量语料（数百行、每行带完整探测轨迹）留在本地 `data/` 下，`.gitignore` 明确
排除。公开仓库只需要让人**能跑出同一组数字**，不需要把别人的站点清单和逐站
结论一起发布。

这 24 行足以验证：

- 分母口径（`FRONT-WAF` / `ENV-FLIP` 被排除）；
- `PASS` 与 `GATE-ONLY` 的区分；
- `inventory` 的统计、快照与 diff 渲染。

## 2. 字段

| 字段 | 含义 |
|---|---|
| `host` | 扫描的主机名（不带 scheme） |
| `status` / `len` | 最终一次响应的状态码与正文字节数 |
| `ok` | 拿到内容（`content_like == True`） |
| `gate` | `"passed"`：闸开了但没拿到内容；`null`：未单独记录 |
| `origin_status` | 过闸后源站的状态码（401/503 等） |
| `via` | 走通的变体（`A0` / `standard` / `qparam` / `canonical` / `hub`） |
| `vendor` | 探测时看到的边缘厂商；`vendor.vendor != "akamai"` 的行不参与分母 |
| `err` | 人类可读的失败原因（仅失败行） |
| `secs` | 该行耗时 |

最小行只需 `host` + 判定字段，`inventory.classify` 对其余字段容错。

## 3. 跑一遍

```bash
python -m gatekit inventory --sweep examples/sample_sweep.json
```

预期输出（数字固定，格式可能随版本微调）：

```
[sweep] examples/sample_sweep.json
  gated hosts 24: Akamai-native 20 / front AWS WAF 2 / DNS flip 2 (probe saw Akamai, re-run)
  Akamai-native 20 -> content PASS 17 / gate-only 3 / fail 0
  gate 20/20 = 100.0%   content 17/20 = 85.0%
```

写快照并隔轮对比：

```bash
python -m gatekit inventory --sweep examples/sample_sweep.json --json auto
python -m gatekit inventory --diff data/inventory_<时间戳>.json
```

## 4. 怎么读这三个数字

| 数字 | 含义 | 不该被读成 |
|---|---|---|
| 24 | 摘录行数 | "全网只有 24 个站" |
| 20 | Akamai-native（分母） | 成功率的分母之外还有 4 行：2 个 AWS WAF、2 个 DNS 摆动 |
| 100% 过闸 | 20 个站全部通过挑战 | "20 个站都有内容"——其中 3 个是 `GATE-ONLY` |
| 85% 有内容 | 17/20 | 求解器的上限；另外 3 个是源站本身没内容（维护页 / 短通告） |

## 5. 边界

- 这是**一次**扫描，不是基准测试；站点行为、DNS、边缘厂商都会变；
- 行里的时间是 2026-11-01，复跑请用当前时间重新生成，而不是直接重放；
- 站点清单只包含公开可访问的主页，不涉及登录、付费墙或个人数据；
- 不在仓库里的字段（逐请求 trace、cookie 名、验证回执）是刻意剔除的。
