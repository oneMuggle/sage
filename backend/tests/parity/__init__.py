"""Mock LLM 一致性测试台 (M6 生态扩展)。

模式来源: claw-code ``rust/crates/mock-anthropic-service`` — 用脚本化
场景的 mock 服务器验证真实客户端的线协议解析。本包把它移植为
OpenAI 兼容版: 线程托管的 http.server 说 /v1/chat/completions
(含 SSE 流式), 场景以纯数据定义。
"""
