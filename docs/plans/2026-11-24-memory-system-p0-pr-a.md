# 记忆系统 P0 修复 PR-A：机制接通与枚举串号

> 状态：进行中
> 创建：2026-11-24
> 分支：feat/memory-system-p0-pr-a

## 背景与目标

内网 sage 部署的记忆系统出现 4 个严重问题：

1. **记忆条目越来越多**：476 条且持续膨胀，进化机制未有效修剪/合并。
2. **只有情景记忆**：语义记忆、工作记忆、会话摘要几乎从未生成。
3. **用户偏好是字符串拼接**：`"用户偏好详细程度：detailed"` 而非学习到的结构化画像。
4. **低质量候选 tab 为空**：质量分机制存在但未接入删除路径。

根因诊断：

- `detail_level` 的枚举串号 bug（`"详细"→"detailed"` 应为 `"comprehensive"`）。
- recall 路径不更新 `accessed_at` / `access_count`，导致 consolidation 的 `>=5` 永远不触发。
- `lifecycle.py` 硬编码 `memory_type="episodic"`，extractor 返回的 memory_type 不生效。
- `MemoryQualityScorer.should_delete` 方法存在但无任何调用方。
- 低质量候选阈值 0.3 + 90 天太苛刻。
- 进化任务 LLM 不可用时标 `success`（假成功）。

本 PR 做 PR-A 的 6 个 bug fix + 机制接通任务，预计 1 周工作量。

## 涉及的文件与模块

| 文件 | 模块 | 改动 |
|------|------|------|
| `backend/scheduler/evolution.py:847` | preference_learning | 修 detail_level 枚举映射 |
| `backend/memory/episodic.py` | recall 路径 | 更新 accessed_at / access_count |
| `backend/memory/semantic.py` | recall 路径 | 更新 accessed_at / access_count |
| `backend/memory/lifecycle.py:317` | lifecycle 写入 | **win7-only**：`MemoryWriteEvent` 不再硬编码 episodic |
| `backend/memory/quality_scorer.py` | should_delete | 接入删除路径 |
| `backend/scheduler/evolution.py` | 全部任务 | 无 LLM 时标 skipped_no_llm |

## 技术方案

### 修改 1：修 detail_level 枚举串号

```python
# backend/scheduler/evolution.py:847
# BEFORE
detail_prefs = {"详细": "detailed", "简单": "brief", "复杂": "comprehensive"}
# AFTER
detail_prefs = {"详细": "comprehensive", "简单": "brief", "中等": "medium"}
```

### 修改 2：recall 路径更新 accessed_at / access_count

在 `episodic.py` / `semantic.py` 的 `get_recent()` 方法中，对召回的记忆行执行 UPDATE：

```python
def get_recent(self, limit=20, session_id=None):
    records = self._query_recent(limit, session_id)
    # 新增：更新 accessed_at / access_count
    for r in records:
        self._touch_access(r["id"])
    return records
```

`_touch_access()` 执行 `UPDATE accessed_at = now_ms, access_count = access_count + 1 WHERE id = ?`。

### 修改 3：lifecycle.py 不再硬编码 episodic（仅 win7 分支）

> **说明**：`backend/memory/lifecycle.py` 在 main 分支不存在，本修改仅在 `release/win7` 实施。
> main 分支的等价路径（`backend/adapters/out/memory/adapter.py:MemoryAdapter.store`）
> 已正确使用 `classify_memory_type("auto", importance, content)` 路由，无需修改。

```python
# backend/memory/lifecycle.py:317 (release/win7)
# BEFORE
await self._hooks.emit(
    "memory_written",
    MemoryWriteEvent(
        memory_id=memory_id,
        content=fact.get("content", ""),
        memory_type="episodic",  # 硬编码 — 下游审计/UI 看到的是固定标签
        ...
    ),
)
# AFTER
await self._hooks.emit(
    "memory_written",
    MemoryWriteEvent(
        memory_id=memory_id,
        content=fact.get("content", ""),
        memory_type=_resolve_layer_for_event(fact, importance, content),
        ...
    ),
)
# 写入路径 _persist_fact → aremember_with_conflict_check 已走 classify_memory_type，
# 此处只修事件载荷里 memory_type 字段的语义。
```

> 注：extractor 实际不返回 `memory_type` 字段（`backend/memory/extractor.py` 仅返回
> `content/importance/category/tags`），所以本修复是把事件 payload 的 `memory_type`
> 与 `_persist_fact` 内部实际写入的 layer 对齐，而不是"按 extractor 声明路由"。

### 修改 4：should_delete 接入删除路径

在 `MemoryPruningTask` 中新增逻辑：当 `quality_score < 0.3 AND created_at < 30d` 时调用 `should_delete()` 并执行删除。

```python
# backend/scheduler/evolution.py MemoryPruningTask
if self.scorer.should_delete(record):
    self.episodic_store.delete(record["id"])
```

### 修改 5：低质量候选阈值调整

```python
# backend/memory/quality_scorer.py
LOW_QUALITY_THRESHOLD = 0.3  → 0.4
STALE_DAYS = 90  → 30
```

### 修改 6：进化任务无 LLM 时标 skipped_no_llm

```python
# backend/scheduler/evolution.py 全部任务
if not llm_available:
    return {"status": "skipped_no_llm", "reason": "LLM not available"}
```

## 实施步骤

- [x] 步骤 1：修 detail_level 枚举串号（`"详细"→"comprehensive"` 等）
- [x] 步骤 2：recall 路径更新 accessed_at / access_count（`episodic.py` / `semantic.py`）
- [x] 步骤 3：lifecycle.py 不再硬编码 episodic —— **仅 release/win7**，main 分支已正确走 `classify_memory_type`；cherry-pick PR-A 后在 win7 侧实施
- [x] 步骤 4：should_delete 接入删除路径（`MemoryPruningTask` 质量合并 + leader 保护）
- [x] 步骤 5：低质量候选阈值调整（`0.3/90d → 0.4/30d` + 前端阈值常量 `QUALITY_LOW_THRESHOLD` 统一接入 `MemoryBrowser.tsx` / `MemoryItemCard.tsx` QualityBar 色带 + IPC 默认）
- [x] 步骤 6：进化任务无 LLM 时标 skipped_no_llm（`BaseEvolutionTask._resolve_llm` DRY 提权 + DailySummary/SkillConsolidation 写 skipped_no_llm 日志；PreferenceLearning/MemoryReflection 因有降级路径，仅在 description 后缀说明）
- [x] 步骤 7：编写单元测试（`test_evolution_tasks.py` quality_merge + skipped_no_llm 断言；`test_curator_provenance.py::test_no_provider_is_noop` 追加日志断言；`EvolutionPanel.status.test.tsx` 新增 `skipped_no_llm` 用例 → 8 用例全绿）
- [ ] 步骤 8：集成测试（启动后端 + curl 验证）
- [ ] 步骤 9：代码审查（code-reviewer agent）
- [ ] 步骤 10：PR 合并 + cherry-pick 到 release/win7 + 在 win7 实施修改 3（lifecycle.py 事件 payload 不再硬编码 episodic）

## 风险评估与依赖

### 风险

1. **修改 2（recall 更新 access_count）可能影响性能**：每次 recall 都执行 UPDATE。测试：recall 100 次，延迟 < 50ms。
2. **修改 3（lifecycle 类型路由）可能让 semantic 突然增多**：extractor 默认给 importance=5-6，不再进 semantic。需灰度观察。
3. **修改 4（should_delete 接入）可能删除过多**：阈值 0.3 + 30d 较苛刻，但首次运行可能删除大量低质量记忆。建议先 dry-run 模式（只打印不删除）。
4. **修改 6（进化任务状态）需前端兼容**：`evolution_log` 出现新状态 `skipped_no_llm`，前端需识别。

### 依赖

- 无外部依赖。
- 不新增 Python 包。
- 不改 SQLite schema。

## 验证标准

1. `curl /api/v1/memory/list` 返回的 `total` 不再只增不减。
2. `curl /api/v1/memory/quality-candidates` 返回非空列表。
3. `evolution_log` 出现 `status=skipped_no_llm` 条目。
4. 用户偏好不再出现 `"用户偏好详细程度：detailed"`。
5. recall 路径执行后，`access_count` 自增。
