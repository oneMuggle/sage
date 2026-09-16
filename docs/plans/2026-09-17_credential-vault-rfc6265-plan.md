# AU 系列收口——凭据档案 RFC 6265 合规加固（Round 15）

日期：2026-09-17 ｜ 分支：`feat/credential-vault-rfc6265` ｜ 基线：bd6ce80a

## 背景

`backend/tools/credential_vault.py`（640 行）是登录墙抓取（AU1/AU2/AU4）的安全核心，
已有 854 行单测覆盖主流程。安全审视发现 4 个纵深防御缺口——现有消费端
（web_tool/download_tool 的 hop 门控）恰好挡住了实际利用路径，但模块自身的
公共 API 契约没有兜住，未来调用方一绕过 hop 门控即暴露：

1. **跨主机 Set-Cookie 注入**：`merge_set_cookies` 只校验 cookie 归属域 ∈ 档案域，
   不校验「请求主机 ≈ cookie 域」（RFC 6265 §5.3 step 6）。若调用方传入
   `https://evil.com/x` 的响应 + `Set-Cookie: SID=…; Domain=cnki.net`，
   会被注入 cnki.net 档案（session fixation）。
2. **cookie 名/值不设防**：`save_credential` / `parse_set_cookie` 接受任意字节。
   `cookie_header_for` 拼 `"; ".join(f"{n}={v}")` 时，含 `;` 或控制字符的
   名/值会伪造 Cookie 对 / 破坏头完整性。
3. **`__Host-` / `__Secure-` 前缀不校验**（RFC 6265bis §4.1.3）：浏览器会拒绝
   违规前缀 cookie，我们的解析器照单全收并回存档案。
4. **头部凭据（Authorization 等）附加明文 http**：cookie 通道有 secure 位保护，
   头部通道没有——`resolve_credential(url=…)` 对 `http://` 同样放行，
   Bearer token 可能明文出网。

## 改动

### `backend/tools/credential_vault.py`

- `_clean_cookie`：名不符合 token 文法（复用 `_HEADER_NAME_RE`）→ 丢弃该条；
  值含控制字符（0x00-0x1F / 0x7F）或 `;` → 丢弃。全部丢弃时
  `save_credential` 沿用现有 `ValueError`。
- `parse_set_cookie`：
  - 名非 token / 值含控制字符或 `;` → 返回 `None`；
  - `__Secure-` 前缀（大小写不敏感）缺 `Secure` → `None`；
  - `__Host-` 前缀：缺 `Secure`、带 `Domain`、`Path != "/"` 任一 → `None`。
- `merge_set_cookies`：新增请求主机亲和检查（fail closed，无请求主机拒绝全部）：
  - host_only cookie：`request_host == cookie.domain`；
  - domain cookie：`cookie_domain_matches(request_host, cookie.domain)`。
- `resolve_credential`（KIND_HEADER 且给定 url）：scheme 为 http 且主机非本地
  回环（localhost / 127.0.0.1 / ::1 / *.localhost）→ 新状态 `insecure_scheme`；
  `CredentialResolution` 文档同步。
- 组装端 belt-and-suspenders：`cookie_header_for` 与 `resolve_credential` 的
  cookie 分支拼头时跳过名/值不合法的存量条目（兜住旧档案脏数据）。

### 消费端（最小分支）

- `web_tool.py` / `download_tool.py`：`resolution.status == "insecure_scheme"` →
  返回 `credential_insecure_scheme` 错误（提示改用 https 或本地回环）。

### 测试

- `TestCookieNameValueValidation`：save 丢弃非法条目（全非法 → ValueError）；
  parse 拒绝控制字符。
- `TestCookiePrefixes`：`__Secure-` / `__Host-` 各违规组合 → None；合规通过。
- `TestMergeHostAffinity`：evil.com 响应注入 `Domain=cnki.net` 被拒；
  host_only 精确匹配；无请求 URL 拒绝。
- `TestInsecureScheme`：头部凭据 + http url → `insecure_scheme`；本地回环放行；
  web_fetch / download 报 `credential_insecure_scheme`。

## 纪律

- py3.8：stdlib only，typing 注解沿用模块头 noqa。
- 不动 AU1/AU2/AU4 既有行为；全部为增量收紧。
