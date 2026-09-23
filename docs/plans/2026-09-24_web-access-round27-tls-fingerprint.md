# 网页访问 Round 27：AB3 TLS/HTTP2 指纹（可选依赖，main only）（2026-09-24）

- **上游文档**：Round 5 §AB3（P2 可选，main only，win7 不引入）；AB4 stealth 口径
- **范围**：后端 + 前端开关（tls_transport.py 新模块 / web_tool.py / requirements-optional.txt / NetworkTab.tsx + i18n）

## 0. 结论速览

静态抓取的最后一项对抗性缺口：站点仅凭 TLS/HTTP2 握手指纹（JA3 等）即可
把 httpx 请求识别为脚本客户端。R27 以 **httpx 自定义 transport** 形态接入
curl_cffi（Chrome 指纹），策略校验/重定向编排/AB5 重试/响应缓冲零改动。

## 设计

1. 新模块 `tls_transport.py`：
   - `fingerprint_enabled()`：读 `web_access_config.tls_fingerprint`
     （默认关；任何失败静默回退关闭）；
   - `CurlImpersonateTransport(httpx.BaseTransport)`：`handle_request` 经
     curl_cffi 发请求（`impersonate="chrome"`、`allow_redirects=False`——
     重定向编排仍在 web_tool 逐跳完成；应用级代理经 `load_proxy_config`
     透传给 curl，环境变量代理在指纹模式不生效）；
   - `build_fingerprint_transport(verify)`：curl_cffi 未安装 → 记一次日志
     返回 None（调用方回落标准 httpx 传输，行为与 R26 前一致）；
2. `web_tool._get_with_redirects`：构建 client 时按开关注入 transport；
3. 依赖：requirements-optional.txt 增 `curl_cffi>=0.7`（默认不装；
   release/win7 不装）；
4. 前端：设置页"静态抓取 TLS 指纹伪装（实验性）"开关 + i18n；
5. 测试：假 curl_cffi 模块注入——响应映射/指纹参数钉死/代理透传/
   回退路径；web_tool 集成——开关决定 transport 注入与否。

## 口径

与 AB4 stealth 相同：只做"不主动暴露自动化"，不做验证码破解、不绕过
明确的 robots/ToS 拒绝；403 升级链失败后仍以指引结束，不无限重试。
