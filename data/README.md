# data/ — 夹具与本地语料

这个目录分两半：**随仓库发布的夹具**，和**只留在本地的研究语料**。

```text
data/
├── fixtures/          # ✅ 随仓库发布
│   ├── MANIFEST.md    #    来源、时间、字节数、sha256
│   ├── real/          #    7 份真实响应（已脱敏）
│   └── synthetic/     #    3 份构造响应
├── full/              # ❌ 本地全量语料（.gitignore）
├── local/             # ❌ 本地临时产物（.gitignore）
├── corpus_sweep*.json # ❌ 批量扫描结果（.gitignore）
├── inventory_*.json   # ❌ 口径快照（.gitignore）
└── *.html / *.json    # ❌ 其他运行产物（.gitignore）
```

## fixtures/ 是什么

| 子目录 | 内容 | 用途 |
|---|---|---|
| [`real/`](fixtures/real/) | 7 份真实响应：zara / flaticon / nh-hotels 壳、wurth crypto 墙、amazon CloudFront 202、trustpilot AWS WAF、zara 内容摘录 | 钉住判据；正负样本都有 |
| [`synthetic/`](fixtures/synthetic/) | 3 份构造响应：小页、大页、compact 传感器 | 覆盖阈值边界 |

每份夹具的来源、抓取时间、字节数、sha256 与"代表什么"都登记在
[MANIFEST.md](fixtures/MANIFEST.md)。token 均已过期，**不能重放**。

## 为什么全量语料不发布

全量语料包含扫描得到的站点清单、逐站判定与真实会话材料。发布它等于发布
一份"谁在用 Akamai、哪里能过"的地图，既超出协议研究的必要范围，也可能
涉及目标站条款。仓库只保留**每种形态各一张**的脱敏样本。

规则见 [BOUNDARIES §6](../docs/BOUNDARIES.md#6-数据政策)，
`.gitignore` 的实际排除项见 [仓库根目录的 .gitignore](../.gitignore)。

## 新增夹具

1. 只保留响应正文，不提交 `Cookie` / `Set-Cookie` 的有效值；
2. 确认不含个人数据；
3. 在 `MANIFEST.md` 登记来源、时间、字节数、sha256；
4. 大文件截断到 ≤64 KB，并写明截断方式；
5. 跑 `py -3.12 tests/test_offline.py`。

返回 [仓库根目录](../README.md)。
