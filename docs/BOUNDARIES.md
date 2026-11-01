# BOUNDARIES — 范围、失败模式与合规

> 一个工具的价值一半在"能做什么"，另一半在"明确不做什么"。
> 这份文档把两半都写下来，避免把"墙"误记成"失败"，也避免越界。

---

## 1. 支持的范围

| 能力 | 状态 | 说明 |
|---|---|---|
| 识别 interstitial 壳 | ✅ | `is_interstitial`，前 40KB 双标记 |
| 解析 token / pow / 端点 | ✅ | JSON 与 meta refresh 两种形态 |
| standard POST 协议 | ✅ | `/_sec/verify?provider=interstitial` |
| A0 / A / B 变体 | ✅ | A0 用一次性会话探测 |
| canonical 域兜底 | ✅ | `Set-Cookie Domain` → ccTLD→`.com` |
| cross-origin 门面 | ✅ | `challenge.<apex>` → `www.<apex>` |
| 过闸后取页面 | ✅ | `InterstitialClient`，重锁自动再解 |
| 五桶口径与快照对比 | ✅ | 见 PLAYBOOK §2.5 |
| 16 种响应形态的识别 | 部分 | 见下表"仅识别" |
| classic sensor / JS 环境 | ❌ | 明确不支持 |
| reCAPTCHA / crypto PoW | ❌ | 只识别、报告，不解 |
| PX / Cloudflare / DataDome / AWS WAF | ❌ | 只识别为"别家"，不参与分母 |
| 登录 / 付费墙 / 人机验证 | ❌ | 不在范围 |

### 1.1 "仅识别"的形态

`classify_sensor` 会给出 `sensor` 与 `evidence`，但不会尝试解决：

- `compact_v3`：正常页上的压缩传感器（不是闸）；
- `classic`：经典 sensor 路径（需要 JS 环境）；
- `challenge_recaptcha` / `challenge_crypto`：Akamai 自家的验证页
  （`id="sec-cpt-if"`，`provider` 区分），是**墙**——`classic` 的随机脚本
  路径很容易把它误判成 classic sensor，所以分类器在路径启发式之前先标它；
- `self_captcha`：站方自建的 "Bot or Not" 页面；
- `akamai_denied_page` / `akamai_rate_limit`：拒绝/限流页（可重试，但不是挑战）。

`gatekit solve` 遇到非 interstitial 的判定会跳过 L2i，并在 `trace` 里写明
`skip(sensor=...)` 或 `unsupported`，**不会假装成功**。

---

## 2. "解决"的三种结果

报告里必须分开写，否则结论会被带偏：

| 结果 | 含义 | 该记成 |
|---|---|---|
| `ok=true` | 拿到真内容（`content_like`） | 成功 |
| `gate=passed` + `ok=false` | 挑战开了，源站回 401 / 503 / 短通告 | **不是求解失败** |
| 复查仍是壳 / 连接失败 | 闸没开 | 失败 |

`inventory` 把前两种分别记为 `PASS` 与 `GATE-ONLY`，二者都计入"过闸"。
把 `GATE-ONLY` 算作失败，会让人去查 token——而 token 根本没问题。

---

## 3. 已知缺陷与启发式

这些是**当前实现的有意取舍**，不是意外：

| 位置 | 行为 | 风险 / 什么时候会错 |
|---|---|---|
| `is_interstitial` | 只扫前 40KB，子串匹配 | 壳被推到 40KB 之后会漏；正文恰好包含两个词会误判（概率低） |
| `content_like` | >20KB 直接算内容 | 一个 21KB 的拦截页若不含 block marks 会被误判为内容 |
| `content_like` | 小页要求 `<title>` + >800 字 | 极简落地页 / 纯图片页会被判"无内容"（已知，故意保守） |
| `hard_block` | 4xx 且 <2KB | 真正的短错误页也会触发重试；最多两次 |
| `cloudfront_draw` | `server` 含 cloudfront 或 202+<4KB | 其他 CDN 的 202 会被误判为 DNS 摆动 |
| `path_entropy` / `looks_classic` | 大小写切换计数 | 只用于"是否值得进入 classic 专题"，不参与求解 |
| `cookie_domain_mismatch` | 只看 `Set-Cookie` 的 `Domain=` | 多个 Set-Cookie 时取第一个不匹配的 |
| `canonical_remap` | `Domain=` 与 ccTLD→`.com` 两种候选 | 品牌域与 ccTLD 无关时会猜错（如 `.co.uk` → `.com`） |
| A0 探测 | 发一次带空 qparam 的请求 | 对极少数站可能有副作用（会换会话，不会污染主会话） |
| `inventory.latest_sweep` | 按 mtime + 行数阈值 | 行数阈值可配置；显式 `--sweep` 始终优先 |

**判据改动必须配一条离线断言**，并跑 `tests/test_offline.py`。没有断言的
"修复"在下一轮很容易被改回去。

---

## 4. 稳定性

- 本仓库按**观测到的形态**实现，不依赖任何未公开的算法；
- Akamai 可能随时调整壳结构、端点、pow 表达式和复查时序；
- 壳的结构一旦变化，最先坏的是 `parse_interstitial`，其次是 `is_interstitial`；
- 离线夹具是 2026-11-01 抓取的，**token 已过期**，只用于判据测试，
  不能拿去重放（也不应该）。

维护建议：

1. 每季度重新抓一份壳，更新 `data/fixtures/real/`，跑离线回归；
2. 新形态先加"识别"，再谈"解决"；
3. 版本号遵循语义化：判据变化 → minor；协议变化 → minor；纯文档 → patch。

---

## 5. 合规：先确认你有权限

这是**协议研究与互操作性工具**。允许的用途包括：

- 安全研究、教学、CTF；
- 对自己拥有或**获得书面授权**的目标做测试；
- 公开数据的合规采集，且遵守目标站服务条款与 `robots.txt`。

明确禁止的用途：

- 绕过登录、付费墙、验证码或访问控制；
- 采集个人信息、凭证、支付数据；
- 规避计费、限流或地理授权限制；
- 对目标站造成压力（并发保持个位数，遇 403 就退）。

不同司法辖区对"绕过技术措施"的规定不同，例如：

- 中国：《刑法》第 285 条第 3 款（非法侵入/获取计算机信息系统数据）、
  《网络安全法》第 27 条；
- 美国：Computer Fraud and Abuse Act；
- 欧盟：各成员国对 Directive 2001/29/EC 第 6 条的 implementation。

**这些只是提示，不是法律意见。** 发请求之前，先确认授权与当地法律。
使用者对自己的行为负责；作者不对任何使用后果负责。

本项目与 Akamai Technologies 无关联，未获其授权或背书。

---

## 6. 数据政策

仓库里**只有**：

- 框架代码；
- 方法论文档；
- 10 份夹具（7 份真实响应 + 3 份构造响应）；
- 24 行真实结果摘录（`examples/sample_sweep.json`）；
- akamai.com 官网公开客户案例清单（`datasets/akamai_customers/`，304 条
  元数据 / 268 个主机，不含正文、PDF 或逐站检测结果）。

仓库里**没有**：

- 全量语料与批量扫描结果（本地生成，`.gitignore` 排除）；
- 扫描得到的站点清单与逐站结论；
- 任何有效 cookie、token、会话材料；
- 个人数据、账号、支付信息；
- 目标站的私有接口或未公开文档。

夹具的脱敏标准：

1. 不保留 `Cookie` / `Set-Cookie` 字段中的有效值；
2. token 只保留结构，不保证可用（抓取后即过期）；
3. 不包含邮箱、电话、姓名、地址；
4. 保留必要的品牌与文案，用于判据识别。

提交新夹具前请按同一标准自查，并在
[`data/fixtures/MANIFEST.md`](../data/fixtures/MANIFEST.md) 登记来源、
抓取时间、体积、sha256。

---

## 7. 报告新形态

遇到本文档没写的响应，请附：

1. **完整响应头**（可删 cookie 值）+ 前 64KB 正文；
2. 抓取时间、URL、使用的 TLS 指纹；
3. 你预期的判定 vs 实际判定（`probe` 的输出）；
4. 阴性对照做了哪些（空 token / 不取壳 / pow=0）。

不要附：有效 cookie、账号、个人数据、目标站的私有内容。

---

返回 [docs 索引](README.md) · [仓库根目录](../README.md)。
