# r60 批次计划：MCP OAuth 授权流切片 1——纯函数库层（PKCE/发现/解析）

日期：2026-09-16（分支创建于 main@c267457a）
文件面：新增 backend/mcp/oauth.py + backend/tests/unit/test_mcp_oauth.py；
零网络、零依赖（stdlib only）、零既有代码改动。

## 背景

「MCP OAuth 完整授权流」是 L 级 backlog。完整链路 = 发现（RFC 8414/9728）
→ 动态注册 → 授权码流 + PKCE（RFC 7636）→ 回调校验 → token 存储与刷新
→ http_client 头注入。后两段需要存储/网络/进程间回调（后续切片），本切片
先落**全部纯函数地基**——与 r57 同模式：依赖显式、单测完备、零产品耦合。

## 交付（backend/mcp/oauth.py，仅 stdlib：hashlib/base64/secrets/urllib）

1. PKCE：`generate_code_verifier`（RFC 7636 §4.1：43–128 字符非保留集）、
   `code_challenge_s256`（BASE64URL(SHA256(verifier)) 去填充）、
   `generate_pkce_pair`、`generate_state`（secrets.token_urlsafe）。
2. 发现 URL 构造：
   - `build_authorization_server_discovery_urls(server_url)`（RFC 8414 §3：
     well-known 段插入 host 与 path 之间；根路径回退根形式）
   - `build_protected_resource_discovery_urls(server_url)`（RFC 9728 同构）
3. 元数据解析：`parse_authorization_server_metadata`（issuer/
   authorization_endpoint/token_endpoint 必填校验）、
   `parse_protected_resource_metadata`（resource + authorization_servers）；
   形状非法 → OAuthMetadataError。
4. 授权 URL：`build_authorization_url`（response_type=code、S256、可选
   scope/resource(RFC 8707)）。
5. 回调与 token：`validate_authorization_callback`（error 参数 →
   OAuthAuthorizeError；state 不匹配 → OAuthStateError；返回 code）、
   `parse_token_response`（access_token 必填、expires_in 可选、refresh_token
   可选）。

## 测试（~16 例，全本地可跑）
verifier 字符集/长度边界/唯一性、challenge 公式对拍 hashlib、state 长度、
发现 URL（根/path 两种 server_url × 两类元数据）、元数据缺失/非 dict 报错、
授权 URL 参数与可选项、回调成功/state 不匹配/error 拒绝、token 响应
正常/缺 access_token/expires_in 透传。

## 后续切片（不在本批）
- 切片 2：token 持久化 + 刷新 + http_client 头注入接线；
- 切片 3：loopback 回调监听 + 设置 UI 授权入口。

## Win7 对齐
新功能（库层），不 cherry-pick 到 release/win7。
