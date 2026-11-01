# SITE_FLOW — 一条链路上每个包长什么样

> 读法：先看 §1 的角色，再看 §2 的壳，然后 §3 的时序。§4 之后是变体和坑。
> 判断规则见 [PLAYBOOK.md](PLAYBOOK.md)；这里只描述**请求与响应本身**。

---

## 1. 角色：谁在说话

一个 interstitial 链路里固定有四个角色：

| 角色 | 典型 URL / 头 | 干什么 |
|---|---|---|
| **边缘（Akamai）** | 任意站点域名 | 没有有效状态时返回壳；有状态时透传源站 |
| **挑战页** | `GET /` 等真实路径 | 200 + 2–7KB 壳，内含 token 与提交脚本 |
| **验签端点** | `POST /_sec/verify?provider=interstitial` | 收 `{bm-verify, pow}`，返回 JSON 回执 |
| **源站** | 壳放行后才出现 | 真内容，或 401 / 503 / 短通告 |

有时还多一个 **门面站**：真正的内容与验签端点在另一个域（`challenge.<apex>`
→ `www.<apex>`），当前域只负责把挑战 iframe 嵌进来（§4.5）。

---

## 2. 一个壳里有什么（zara 实测，2,122 字节）

去掉无用标签后，壳只有四样东西：

```html
<!-- ① 回跳地址：过闸后浏览器要去哪，通常带 locale 前缀 -->
<meta http-equiv="refresh" content="5; URL='/'">

<!-- ② 同步 XHR：把 token 提交上去 -->
<script>
  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/_sec/verify?provider=interstitial", false);
  xhr.send(JSON.stringify({ "bm-verify": "<268 字符>", "pow": 2272089155 }));
</script>

<!-- ③ 算术题：pow = 1793514655 + Number("4785" + "74500") -->
<script>
  var i = 1793514655;
  var j = i + Number("4785" + "74500");
</script>

<!-- ④ 品牌/错误提示（与协议无关，只用于人眼） -->
```

三个实测数字：

| 站点 | 壳体积 | token 长度 | pow |
|---|---|---|---|
| zara.com | 2,122 B | 268 | 2272089155 = 1793514655 + 478574500 |
| flaticon.com | 6,924 B | 308 | 2751614010 = 1793514656 + 958099354 |
| nh-hotels.com | 2,253 B | — | —（`meta refresh` 指向 `/en`） |

**`pow` 不是哈希难题**，只是把两段数字**先当字符串拼接、再转数字相加**。
写成 Python 就是：

```python
pow_value = int(i) + int(prefix_str + suffix_str)
```

`gatekit.judges.parse_interstitial()` 同时读 JSON 与 meta refresh 两种形态：
优先 JSON（标准 base64），退化时读 query（URL-safe base64）。

### 2.1 壳的指纹

- 体积 **2–7 KB**（Magnific 层到 6.9 KB）；
- 前 40 KB 内出现 `bm-verify`，且出现 `_sec/verify` 或 `interstitial`；
- **HTTP 200**，`Content-Type: text/html`；
- 页面本身几乎不含可见正文。

---

## 3. 请求时序（standard 变体）

```
client                          edge                         origin
  |  GET /target                    |                            |
  |------------------------------->|                            |
  |  200 text/html, 2-7KB shell    |                            |
  |<-------------------------------|                            |
  |                                |                            |
  |  [parse token / pow / endpoint]|                            |
  |                                |                            |
  |  POST /_sec/verify?provider=interstitial                   |
  |  {"bm-verify": "...", "pow": N}                            |
  |------------------------------->|                            |
  |  200 {"reload": true}          |   (边缘记下本会话状态)       |
  |<-------------------------------|                            |
  |                                |                            |
  |  sleep 0.6s, GET /target       |                            |
  |------------------------------->|--------------------------->|
  |  200 真内容                     |<---------------------------|
  |<-------------------------------|                            |
```

要点：

1. **同一个会话**取壳 → POST → 复查。挑战状态挂在边缘的会话上，换会话等于重来；
2. POST 的回执可能是 `{"reload": true}`、`{"location": "..."}`，也可能直接是 HTML
   （后者说明打错了域，见 §4.5）；
3. 复查要**分四档**：0.6 / 1.0 / 1.5 / 2.0 秒。Magnific 系会轮换 `ak_bmsc`，
   0.6s 时还是壳、1s 后才可读；
4. 回执里若给了 `location`，复查就跟着它走，而不是原来的 URL。

### 3.1 状态挂在哪

| 东西 | 谁写 | 后续请求怎么带 |
|---|---|---|
| `_abck` / `ak_bmsc` / `bm_sz` | POST 的回执（`Set-Cookie`） | 浏览器/会话自动带 |
| 挑战通过标记 | 边缘，按会话 + cookie + IP 记 | 同会话即可 |
| `bm-verify` token | 壳 | **一次性**，POST 后作废 |

两个由此推出的规则：

- **cookie 的 `Domain` 必须放得下**。若回执写 `Domain=.zara.com`，而你在
  `www.zara.it`，浏览器不会保存这个 cookie，复查永远是壳 → 换规范域（§4.4）；
- **不同会话不要混用 token**。壳给的是 A 会话的 token，POST 却用 B 会话，
  边缘会当无效。

---

## 4. 五个变体怎么分叉

### 4.1 A0：参数存在即放行

```
全新会话 → GET /?bm-verify=   （值为空）→ 200 真内容
```

- 不看 token，只看参数在不在；
- **必须用一次性会话探测**：在 B 型站上发 qparam 会 403 并弄脏会话；
- 命中后，后续每个请求都要带 `?bm-verify=`（客户端里的 `self.a0`）。

### 4.2 A：qparam 容忍 / token 不校验

```
GET / → 壳 → （可选）POST 任意值 → GET /?bm-verify=<随便> → 内容
```

zara、iberdrola 属于这一类。**不代表可以省掉 POST**：它的意义是兜底，
（顺序见 PLAYBOOK §3.2）。

### 4.3 B：只认 POST

```
GET / → 壳 → POST 正确 token → 复查 → 内容
先发 qparam → 403，随后 POST 也失效（会话被污染）
```

flaticon、bike24 属于这一类。这是**兜底顺序不能反**的直接原因。

### 4.4 canonical：别名域存不下 cookie

症状组合（任一）：

- POST 回 `{"reload": true}`，但复查还是壳；
- 回执的 `Set-Cookie: Domain=.bike24.com`，而请求在 `www.bike24.net`；
- `POST /_sec/verify` 在别名域直接 404。

动作：换规范域，路径用壳里 `meta refresh` 给的语言前缀：

```
https://www.zara.it/  →  https://www.zara.com/it/
https://www.nh-hotels.de/  →  https://www.nh-hotels.com/en
```

候选顺序：**先信服务端自己说的 `Domain=`**，再按 ccTLD → `.com` 猜。

### 4.5 cross-origin：门面站

症状：POST 回来的是**另一份 HTML 壳**，不是 JSON。

```
壳里出现 https://challenge.<apex>/...
→ POST 到门面域只会再给壳
→ 去 https://www.<apex> + 壳里的 refresh path 解真正的闸
```

iconfinder → magnific 是这一类。`wrong_origin` 是很强的信号，
应当**排在其他兜底之前**（qparam 在这类站必然白跑）。

---

## 5. 判定器落在链路的哪一步

| 时序位置 | 函数 | 回答 |
|---|---|---|
| 收到响应 | `judges.is_interstitial` | 是壳吗？ |
| 收到响应 | `judges.content_like` | 是内容吗？ |
| 收到响应 | `judges.classify_sensor` | interstitial / compact / classic / 自建验证？ |
| 解析壳 | `judges.parse_interstitial` | token / pow / 端点是什么？ |
| POST 回执 | `client._verdict` | `reload` / `location` / HTML（打错域） |
| 复查 | `judges.content_like` + `is_interstitial` | 开了没？有内容吗？ |
| 回执 cookie | `judges.cookie_domain_mismatch` | 该换规范域吗？ |
| 202 / 小页 | `judges.cloudfront_draw` / `hard_block` | 是环境问题还是真拒绝？ |

`judges.py` 里所有函数都不发请求、不读时钟、不碰文件，因此可以离线钉死。

---

## 6. 阴性对照矩阵

怀疑某一步"其实没校验什么"时，按这张表各跑一遍（每条都要**全新会话**）：

| 对照 | 操作 | 若仍成功，说明 |
|---|---|---|
| 空 token | POST `{"bm-verify": ""}` | token 值未校验（A 型） |
| 不取壳 | 直接 POST 编造的 token | 同上，或端点未挂 |
| `pow = 0` | POST 正确 token + `pow: 0` | 算术题未校验 |
| 空 qparam | `GET /?bm-verify=` | A0 型 |
| 错误 `Origin` | POST 带别的 `Origin` | 未校验来源（少见） |
| 不查 cookie | 清 cookie 后复查 | 状态是否真的靠 cookie |

只测成功路径，就分不清"校验了什么"和"什么都没校验"。

---

## 7. 请求级的坑

| 坑 | 现象 | 处理 |
|---|---|---|
| 状态码幻觉 | 壳与内容都是 200 | 永远看 body |
| 6 KB 窗口 | flaticon 的 `_sec/verify` 在 6,110B | 扫前 40KB |
| 复查太早 | 0.6s 仍是壳 | 四档复查到 2.0s |
| qparam 污染 | B 型站先发 qparam 后 POST 失效 | 顺序固定：POST 最先 |
| base 没跟 `r.url` | POST 打到重定向前的 host | 用最终 URL 重建 base |
| apex 挂起 | `curl(28)`，www 正常 | 换 www，连接超时 8s |
| DNS 摆动 | Amazon 族一会 Akamai 一会 CloudFront | 新会话重试，口径记 `ENV-FLIP` |
| 重定向循环 | `curl(47)` | 重试一次 → 手动跟 ≤3 跳 |
| 并发过高 | 成批 403 小页 | 并发 ≤8 |

---

## 8. 复现

```bash
# 看壳（zara 是 A 型；flaticon 是 B 型）
python -m gatekit probe https://www.zara.com/
python -m gatekit probe https://www.flaticon.com/

# 解闸
python -m gatekit solve https://www.zara.com/

# 过闸后取一条深层路径
python -m gatekit fetch "https://2ndstreet.jp/search?category=810032" -o search.html

# 离线回放夹具：不联网也能看到壳长什么样
python -c "import sys;sys.path.insert(0,'.');from gatekit import judges
print(judges.parse_interstitial(open('data/fixtures/real/zara_shell.html',encoding='utf-8').read()))"
```

---

## 9. 这条链路之外

- **classic sensor**（`_abck` + `/akam/` 脚本 + `_bm` 传感数据）：需要按站补 JS
  环境，本项目**不含**；
- **reCAPTCHA / crypto PoW 挑战**：`classify_sensor` 会识别并报告，但**不解**；
- **CloudFront / PX / CF / DataDome**：识别为别家，不参与分母；
- **登录态 / 付费墙**：不在范围内。

判断标准始终是：**有没有一个可执行的通关动作**（有 token 能提交、有端点能
POST）。没有，就只是墙。
