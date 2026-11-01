# SECURITY

## 报告问题

请通过 GitHub 的 **Security → Report a vulnerability**（私有 Security Advisory）
提交，**不要**开公开 issue。公开 issue 里贴有效 token、cookie 或目标站内容，
等于把别人的会话材料发布出去。

报告时请附：

1. 受影响的版本（`python -m gatekit --version`）与文件；
2. 最小复现（能离线复现最好：一段 body + 期望/实际判定）；
3. 影响范围：是判据误判、凭据泄漏，还是会向非目标域发请求。

## 本项目关心的安全问题

| 类型 | 例子 |
|---|---|
| 凭据落盘 | `fetch -o` 把带 cookie 的会话写进文件、日志打印 token |
| 请求打到错误的主机 | canonical / hub 兜底把 `Set-Cookie` 或 token 发到第三方域 |
| 夹具泄漏 | 提交了未过期的 token、真实账号、个人数据 |
| 依赖风险 | `curl_cffi` 版本被替换 / 供应链 |
| 命令注入 | CLI 参数被拼进 shell（当前实现不调用 shell） |

## 不在范围内

- 目标站自身的漏洞（请按其安全政策报告给站点，不要发到这里）；
- "这个工具能绕过 X"——绕过访问控制不在项目范围内，见
  [BOUNDARIES §5](docs/BOUNDARIES.md)；
- 使用本项目违反目标站条款或当地法律的行为。

## 默认安全设置

- **默认直连**，不会把请求经未知代理转发；
- 不内置任何 cookie、账号或 token；
- 夹具中的 token 均已过期，不能用于重放；
- 网络代码只接受调用方显式给出的 URL / proxy / impersonate。

## 已知取舍（不是漏洞）

`docs/BOUNDARIES.md §3` 列出的启发式误判（40 KB 扫描窗口、20 KB 内容阈值、
CloudFront 202 判定等）是**有意保守**的设计。它们值得报 bug，但请按普通
issue / PR 处理，不需要走私密通道。
