# tests/ — 30 条离线断言

一个文件、不依赖 pytest、不联网、不读 cookie。返回码 0/1，可直接进 CI。

```bash
py -3.12 tests/test_offline.py        # 30/30 passed
py -3.12 tests/test_offline.py -v     # 逐条打印
```

## 覆盖什么

| 模块 | 断言内容 |
|---|---|
| `judges.py` | `is_interstitial` / `parse_interstitial` / `content_like` / `path_entropy` / `looks_classic` / `classify_sensor` / `shell_path` / `cookie_domain_mismatch` / `canonical_remap` |
| `inventory.py` | 五桶分类、`build_snapshot`、`compare`、`latest_sweep` 的 smoke-run 防护、`report` 输出 |
| 真实事故回归 | 6 KB 扫描窗口漏掉 6.9 KB 壳；17.6 KB 真首页被长度阈值误杀 |

## 不覆盖什么

- 任何会打开 socket 的代码（`interstitial.py` / `client.py` 的真站行为）；
- 实时挑战（token 一次性、依赖网络与边缘状态，不可重复）；
- 数据集采集脚本（`datasets/`，需要外网与 akamai.com）。

真站回归属于使用者自己的环境，**不随仓库发布**。

## 加一条断言

1. 先在 `data/fixtures/real/` 放一份能复现问题的响应（脱敏规则见
   [CONTRIBUTING](../CONTRIBUTING.md)）；
2. 在 `tests/test_offline.py` 对应分节加一个 `@case("...")` 装饰的函数，写明**旧行为为什么错**；
3. 跑全量，30+ 条必须全绿；
4. 若夹具改变，更新 [MANIFEST](../data/fixtures/MANIFEST.md) 的字节数与 sha256。

返回 [仓库根目录](../README.md)。
