# docs/ — 方法论文档

四篇文档，各回答一个问题。**不用从头读到尾**，按你当下的问题挑一篇。

| 文档 | 一句话 | 什么时候读 |
|---|---|---|
| [PLAYBOOK.md](PLAYBOOK.md) | 探测 → 分析 → 解决，拿到一个新域名按什么顺序做决定 | 第一次上手、排查失败 |
| [SITE_FLOW.md](SITE_FLOW.md) | 一条链路上每个包长什么样，五个变体在哪分叉 | 想对照抓包、理解协议 |
| [BOUNDARIES.md](BOUNDARIES.md) | 支持什么、不支持什么、已知缺陷与合规边界 | 评估适用性、提 issue 之前 |
| [TOOLS.md](TOOLS.md) | CLI 参数、Python API、输出字段、退出码 | 写脚本时查表 |

## 推荐阅读顺序

**第一次接触**

1. [PLAYBOOK §0「三分钟」](PLAYBOOK.md#零三分钟) —— 四个阶段各一条命令；
2. [SITE_FLOW §2–§3](SITE_FLOW.md#2-一个壳里有什么zara-实测2122-字节) —— 壳里有什么、时序怎么走；
3. [PLAYBOOK §2.5](PLAYBOOK.md#25-没内容的三种归因最容易写错报告的地方) —— 别把"闸开了但源站没内容"记成求解失败。

**要动手改代码**

1. [TOOLS §2](TOOLS.md#2-python-api) —— 每个函数吃什么、吐什么；
2. [BOUNDARIES §3](BOUNDARIES.md#3-已知缺陷与启发式) —— 哪些行为是有意保守的设计；
3. [CONTRIBUTING](../CONTRIBUTING.md) —— 判据改动必须配离线断言。

**只想知道能不能用**

- [BOUNDARIES §1](BOUNDARIES.md#1-支持的范围) 支持范围；
- [BOUNDARIES §5](BOUNDARIES.md#5-合规先确认你有权限) 合规边界。

## 维护约定

- 文档里的数字必须能由仓库内文件复现：24 行样本、30 条断言、10 份夹具；
- 判据一变，同步改 PLAYBOOK 的判据表、BOUNDARIES 的缺陷表和离线断言；
- 不在这里写"某站能爬"这类扫描结论——站点清单与逐站结论不随仓库发布。

返回 [仓库根目录](../README.md)。
