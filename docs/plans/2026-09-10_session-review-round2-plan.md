# 会话搜索 + 审阅触发升级 Round 2 实施计划（对标 hermes-agent）

> 日期: 2026-09-10 · 分支: `feat/session-search-review` · 基于 main @ 90c6acf6
> 来源: hermes-agent 对标分析（第二梯队）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。
> 冲突规避: `feat-p10-retrieval-tuning` worktree 正在改 adapter/embedder，
> 本批不触碰这两个文件。

## 背景

Round 1（PR #595）补齐了语义向量与循环守卫；#596 落地了 OnnxEmbedder。
本轮继续补 hermes 两个差异化能力：

1. **会话级全文搜索**（hermes: "session search" FTS5 + agent 综合）——
   Sage 的记忆库只存"抽取出的记忆条目"，用户问"上次我们怎么解决那个
   构建报错"时无法召回原始对话。
2. **审阅触发升级**（hermes: background review fork 决定"该不该存"）——
   现状是"≥4 次工具调用"的粗规则，既漏掉 2~3 步的小流程，也无法
   判断复杂回合是否真的值得沉淀。

## 批次任务

### A. `session_search` 工具（跨会话对话检索）

- **A1 `backend/data/message_search.py`**（新）: `MessageSearchIndex`
  - FTS5 虚拟表 `messages_fts`（jieba 分词入库，复用
    `memory/chinese_tokenizer` 与 `memory/semantic.py` 的建表/同步模式，
    避免 external-content 触发器的历史 malformed 根因）
  - `index_message()`（幂等，先删后插）、`search(query, session_id,
    limit)`（FTS MATCH 优先，异常回退 LIKE）、`rebuild_all()`
- **A2 `backend/data/database.py`**: init 时创建 `messages_fts` 表
- **A3 `backend/data/session_repo.py`**: 4 处 messages INSERT 后挂钩
  `index_message`（新增消息 + fork/复制路径）
- **A4 `backend/tools/session_search_tool.py`**（新）: READ 级工具，
  返回 `{session_id, message_id, role, created_at, snippet}` 列表；
  综合由 agent 自身完成（省一次 LLM 调用）。注册进 registry +
  `domain/tool_names.py`
- 测试: `backend/tests/unit/test_message_search.py`、
  `backend/tests/unit/test_session_search_tool.py`

### B. 审阅触发升级（保留 Sage 人工审批哲学，吸收 hermes 无人值守判断）

- **B1 `backend/skills/review_service.py`**: 新增
  `async should_generate(context) -> (bool, reason)` —— LLM JSON 初筛
  （"这轮对话是否产生值得沉淀的可复用流程？"）；LLM 不可用 → False
  （宁缺勿滥，与 generate_draft 同样依赖 LLM）
- **B2 `backend/skills/review_queue.py::_process_event`**:
  `context.needs_screening=true` 时先初筛，False 则跳过起稿（记日志）
- **B3 `backend/application/services/chat_service.py`**:
  入队阈值 4 → 2（`REVIEW_ENQUEUE_TOOL_CALL_THRESHOLD = 2`），
  2~3 次工具调用的回合带 `needs_screening=true`；用户可见的
  SKILL_NUDGE 维持 ≥4 不变（避免打扰升级）
- 效果: 2~3 步小流程进入 LLM 初筛漏斗（hermes review fork 的判断力），
  复杂回合照旧直达起稿；审批闸口不变
- 测试: `backend/tests/unit/test_review_screening.py`

## 验收

- [ ] 新测试全绿 + 相关存量测试不回归
- [ ] `ruff check backend/` 干净
- [ ] CI（backend 覆盖率 ≥80%）绿
- [ ] PR 注明「新功能，不 cherry-pick 到 release/win7」

## Round 3 候选（记录）

- curator 设施（技能/记忆审计台账 + 单条回滚 + provenance）
- 压缩谱系（fork_session 派生子会话）
- docker 沙箱执行后端
- hex/legacy 双 chat 栈收敛
