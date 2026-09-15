# 记忆-学习循环 Round 1 实施计划（对标 hermes-agent）

> 日期: 2026-09-10 · 分支: `feat/memory-loop-round1` · 基于 main @ 2b10ab0d
> 来源: hermes-agent 对标分析（第一梯队「快赢」项）
> Win7 对齐: 本批全部为**新功能**，按 `docs/technical/31-win7-lts.md` §2 **不进 release/win7**；
> 代码遵循 `backend/ruff.toml` 的 py38 兼容注解约定（typing.List/Optional，
> scripts/py38_compat_rewrite.py 保持两分支注解一致），便于未来修复类 cherry-pick。

## 背景

对标 NousResearch/hermes-agent 发现的三个第一梯队差距：

1. 记忆向量检索用的是 `HashEmbedder`（字符 n-gram 哈希，无语义），
   RRF 融合（`memory/fusion.py`）中权重 0.6 的向量路实质失效；
   而 wiki 子系统已有 OpenAI 兼容 embedding HTTP 管线可复用。
2. agent 主循环（`core/legacy/agent.py run_loop`）缺少空响应守卫与
   工具复读守卫（hermes: `turn_empty_response.py` / `repetition_guard.py`）。
   溢出预检 RT2 已存在，本批不重复建设。
3. 偏好学习（`scheduler/evolution.py PreferenceLearningTask`）是关键词
   LIKE 扫描 + 硬编码映射，脆弱且召回窄（hermes: agent 自主整理 USER.md）。

## 批次任务

### A. 真实语义向量接入记忆检索

- **A1 `backend/memory/embedder.py`** — 新增 `ModelEmbedder`：
  - OpenAI 兼容 `POST {base_url}/embeddings`（httpx 同步 Client，复用
    wiki 的 `EMBED_BASE_URL/EMBED_API_KEY/EMBED_MODEL` 环境变量约定，
    缺省回退 `LLM_BASE_URL/LLM_API_KEY`）。
  - `encode_batch` 批量编码；失败语义：抛 `EmbedderError`，由 VectorStore
    既有 try/except 降级（向量路缺席，关键词路兜底）。
  - **熔断**：连续失败 ≥3 次后熔断 300s（快速失败，避免检索路径每次
    都吃 HTTP 超时——`test_event_loop_blocking` 500ms 延迟门禁）。
  - 工厂 `create_embedder()`：`SAGE_EMBEDDER=model|hash` 显式选择；
    未显式时配置了 embedding 端点即用 model，否则 hash（零依赖兜底）。
- **A2 `backend/memory/vector_store.py`** — 维度迁移与回填：
  - `_init_table` 检测存量 `memories_vec` 表维度与 embedder 不一致时
    DROP + 重建（向量是可再生的派生索引，主表是事实源），并告警。
  - 新增 `_available` 标志（扩展加载失败时 add/search/backfill 全部 no-op）。
  - 新增 `backfill_from_tables(limit)`：从 `memories_episodic` +
    `memories_semantic` 批量重嵌存量记忆（`SAGE_VEC_BACKFILL_MAX` 默认 500）。
- **A3 `backend/adapters/out/memory/adapter.py`** — 接线：
  - `create_embedder()` 替换硬编码 `HashEmbedder(dimensions=256)`。
  - `retrieve()`/`store()` 中的向量读写挪到 `run_in_executor`，
    避免 HTTP 阻塞事件循环。
  - init 时检测 `count() < 主表行数` 即后台守护线程跑一次 backfill
    （一次性，防重入标志）。
- 测试: `backend/tests/unit/test_memory_embedder_model.py`、
  `backend/tests/unit/test_vector_store_dimension.py`（monkeypatch httpx）。

### B. agent 循环守卫（对标 hermes）

- **B1 空响应守卫**（`run_loop`，`if not response.tool_calls` 之前）：
  - 无工具调用且 content 为空白 → 注入 system 提示后 `continue` 重试，
    最多 `SAGE_EMPTY_RESPONSE_MAX_RETRIES`（默认 2，0=关闭保持旧行为）；
    耗尽后 DONE + 兜底文案（不 FAILED，前端有可见反馈）。
  - 流式路径安全性：仅在未发任何 CONTENT_DELTA 时重试（空响应本就无增量）。
- **B2 工具复读守卫**（串行与并行分发前统一检查）：
  - 按 `(tool_name, 规范化参数)` 签名计数；达到软限
    （`SAGE_TOOL_REPEAT_SOFT_LIMIT` 默认 3）注入 system 提醒「已重复调用」；
    达到硬限（默认 5）拦截执行，返回合成错误 tool result 引导模型换路。
  - hermes 对应物是 nudge + guardrail，拦截文案面向模型可自察。
- 测试: `backend/tests/unit/test_agent_loop_guards.py`（沿用
  `test_agent_run_loop.py` 的 AsyncMock side_effect 模式）。

### C. 偏好学习 LLM 化

- `backend/scheduler/evolution.py PreferenceLearningTask`：
  - LLM 客户端：注入优先，缺省走 `orchestration/llm_factory.
    load_llm_config_from_settings()`（与 planner/subagent 同模式），不可用
    则降级纯关键词路径。
  - 采样升级：LLM 可用时取近 7 天用户消息（`llm_sample_limit` 默认 100），
    不再受关键词 LIKE 预过滤；提示词要求只输出有明确证据的稳定偏好 JSON，
    宽容解析；与关键词结果合并。
  - 持久化不变（semantic 记忆 + preferences 表 + evolution_log 审计）。
  - 顺手清理 line 510 死表达式。
- 测试: `backend/tests/unit/test_preference_learning_llm.py`。

## 验收

- [ ] `cd backend && pytest tests/unit/test_memory_embedder_model.py tests/unit/test_vector_store_dimension.py tests/unit/test_agent_loop_guards.py tests/unit/test_preference_learning_llm.py` 全绿
- [ ] 相关存量测试不回归（memory/agent/evolution 相关文件）
- [ ] `ruff check backend/` 干净
- [ ] CI（backend 覆盖率 ≥80% 门禁）绿
- [ ] PR 描述注明「新功能，不 cherry-pick 到 release/win7」

## 不做（Round 2 候选）

- 后台 review fork（无人值守记忆/技能审阅触发升级）
- 会话级全文搜索（FTS5 + LLM 综合）
- curator 设施（审计台账/单条回滚/provenance）
- 压缩谱系、docker 沙箱执行、双 chat 栈收敛
