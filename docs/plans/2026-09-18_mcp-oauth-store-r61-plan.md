# r61 批次计划：MCP OAuth 切片 2——token 存储 + 过期刷新 + http_client 注入

日期：2026-09-16（分支创建于 main@379ae3f3，含切片 1 #984）
文件面：新增 backend/mcp/oauth_store.py；oauth.py 增 2 个纯函数；
http_client.py 注入点 + 1 个可选构造参数；单测。零 UI。

## 背景

切片 1（#984）落了 PKCE/发现/解析地基。本切片打通"token 如何被持有并
生效"：持久化存储、过期判定、刷新请求构造、以及 HttpClientMcpClient
每次请求的 Authorization 头注入。授权回调监听与动态注册（token 记录
的**生产者**）是切片 3——本批次交付消费者侧，token 记录不存在时行为
与现状完全一致（零风险过渡）。

## 交付

1. `backend/mcp/oauth_store.py`：
   - `TokenRecord` dataclass：server_name / access_token / token_type
     (缺省 Bearer) / expires_at (epoch 秒，0=无过期) / refresh_token /
     scope / client_id / token_endpoint（后两者由切片 3 授权时回填，
     刷新要用）；
   - `OAuthTokenStore(root)`：load/save/delete，文件
     `<root>/mcp_oauth_tokens.json`（默认根 = SAGE_USER_DATA_DIR，
     与 mcp_servers.json 同口径；写后即持久化）；
   - `get_oauth_token_store()` 进程级单例（pool 同模式）。
2. `backend/mcp/oauth.py` 增：
   - `is_token_expired(record, now=None, skew_seconds=60)`；
   - `build_refresh_request(token_endpoint, client_id, refresh_token,
     scope=None)` → (url, headers, form 编码 body)（RFC 6749 §6：
     grant_type=refresh_token，form-urlencoded）。
3. `backend/mcp/http_client.py`：
   - `HttpClientMcpClient(..., oauth_store=None)`（None → 全局单例；
     测试注入 tmp store）；
   - `_post` 在 config.headers 合并**之后**注入
     `Authorization: <token_type> <access_token>`——OAuth 令牌覆盖
     静态 PAT（授权动作发生在配置之后，新凭据优先，注释说明）；
   - `start()` 时过期且带 refresh_token + client_id + token_endpoint →
     同步刷新（httpx form POST）并回存；刷新失败 → 删除记录并按
     无 token 继续（fail-open，401 处理留给切片 3 的回调重授权）。

## 测试
- store 往返/删除/损坏 JSON 容错（tmp root）；
- is_token_expired 边界（无过期、skew 内、已过期）；
- build_refresh_request 形态（grant_type/scope 可选/form 编码）；
- http_client：有 token → 注入头；无 token → 与现状一致；静态
  Authorization 存在时被 OAuth 覆盖；过期刷新流程（MockTransport
  返回新 token JSON）+ 刷新失败 fail-open。

## 不做
- 授权回调监听 / 动态注册 / 设置 UI（切片 3）；
- 401 自动重授权（同上）。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
