# MemoryExtractor 复用当前 Session LLM Provider

## 背景
`_build_lifecycle_extractor()` 和 legacy `ChatService._extract_and_store_memory()` 当前使用默认 `HttpxLLMAdapter()`，没有继承当前对话传入的 `llm_config` / provider URL。内网 OpenAI-compatible endpoint 因此可能出现主对话走内网、后台 extractor 仍走默认 OpenAI 的不一致。

## 后续目标
让 extractor 通过显式注入的 session/provider LLM client 运行，并为 provider 切换、异步提取和失败降级补充单测与集成测试。

## 本次不做
本 follow-up 不修改当前修复中的 memory-tool wiring、Win7 certifi 依赖或 SSL bootstrap。
