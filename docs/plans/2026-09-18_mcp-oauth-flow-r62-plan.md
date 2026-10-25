# r62 批次计划：MCP OAuth 切片 3a——授权编排层（发现→注册→授权→交换）

日期：2026-09-16（分支创建于 main@55e787c0，含切片 1 #984 / 切片 2 #989）
文件面：oauth.py 增编排函数 + 单测；零 UI、零既有行为改动。

## 背景

切片 1 落了纯函数地基，切片 2 落了 token 持有侧（存储/刷新/注入）。
缺失的是**生产者侧编排**：给定 MCP server URL，如何走完
「元数据发现 → 动态注册（RFC 7591）→ 授权 URL → 回调 → code 交换」
产出一条可持久化的 TokenRecord。loopback 回调监听与设置 UI 入口是
切片 3b——本批次把回调获取抽象为注入的 `wait_for_callback` 协程
（测试直传回调 URL；3b 提供本机回听实现），编排本身保持纯逻辑。

## 交付（backend/mcp/oauth.py 增量）

1. `build_dynamic_registration_request(client_name, redirect_uri, scope=None)`：
   RFC 7591 JSON body（grant_types=[authorization_code,refresh_token]、
   response_types=[code]、token_endpoint_auth_method=none 公共客户端）。
2. `parse_registration_response(data)`：client_id 必填；client_secret /
   registration_access_token 可选透传。
3. `exchange_authorization_code(token_endpoint, *, client_id, code,
   redirect_uri, code_verifier, client_secret=None)` → (url, headers,
   form body)（grant_type=authorization_code + PKCE verifier）。
4. `async authorize_mcp_server(server_url, *, redirect_uri, scope=None,
   resource=None, client_name="sage", http_get_json, http_post_json,
   wait_for_callback) -> TokenRecord`：
   - 发现：受保护资源元数据（候选 URL 逐个试，404/失败回退授权服务器
     元数据直查）→ 取 issuer + registration/token/authorization 端点；
   - 注册：registration_endpoint 存在 → 动态注册拿 client_id
     （无 registration_endpoint → OAuthMetadataError，切片 3b 再考虑
     手动填 client_id 的降级 UI）；
   - PKCE pair + state → 授权 URL → `wait_for_callback(url)` →
     校验回调 → code 交换 → parse_token_response → TokenRecord
     （client_id/token_endpoint 回填供切片 2 的刷新链路使用，
     expires_at 由 expires_in 换算）。
   - HTTP 全部注入（http_get_json / http_post_json），与 r57/r60 的
     可测性口径一致。

## 测试（respx/fake 注入）
注册请求形态、注册响应校验（缺 client_id 报错）、交换请求形态（含
verifier/secret 可选）、编排全链路（fake discovery/registration/token
三端点 + 直传回调 URL）产出完整 TokenRecord、回调 state 篡改中止、
无 registration_endpoint 报错。

## 不做
- loopback 回听 / 浏览器拉起 / 设置 UI（切片 3b）；
- 401 触发的自动重授权调度。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
