# R148：上下文 Token 预算 + 记忆安全扫描器单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；wiki 上下文预算 / Hermes 三级威胁扫描
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`wiki/context_budget.py`（110 行，上下文 token 预算分配：70% 截断 +
四段比例 + 单页硬上限 + estimate_tokens + truncate_pages 逐页截断）
与 `memory/safety.py`（138 行，记忆写入前的三级威胁扫描：注入/敏感
信息/持久化攻击，strict 才启用第三级）此前零测试。

## 覆盖矩阵（约 21 例）

### `backend/tests/unit/wiki/test_context_budget.py`（9 例）

1. compute 默认 8192 → total 5734 及四段分配精确值、per_page_cap；
2. model_max_tokens 超 DEFAULT_MAX_TOKENS 时按 8192 封顶；小值按比例
   缩放；3. estimate_tokens = ceil(len/3)；4. truncate_pages：预算内
   不截断、超页上限截断（truncated=True、长度 = min(full, cap,
   remaining)*3）、预算耗尽后后续页面丢弃、PageChunk 字段。

### `backend/tests/unit/memory/test_safety.py`（12 例）

1. 良性内容全级别不拦截；2. 空内容放行；3. 注入模式："ignore previous
   instructions" / "you are now a" / "[INST]" → blocked、threat high、
   reason 前缀"疑似 prompt 注入"；4. 敏感信息：api_key=/sk-/ghp_36/
   PRIVATE KEY → blocked"疑似敏感信息泄露"；5. 持久化模式（"always
   respond" 等）仅 strict 拦截（threat medium），all/context 级放行；
6. scan_write 即 strict；7. get_scanner 单例。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
