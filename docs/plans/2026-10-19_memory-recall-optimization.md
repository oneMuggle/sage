# 记忆系统召回优化方案

> **日期**: 2026-10-19  
> **分支**: `feat/memory-recall-optimization`  
> **状态**: 进行中

---

## 1. 背景与目标

### 1.1 问题诊断

当前记忆系统召回命中率低，主要问题：

1. **session_id 过滤过严**：`MemoryAdapter.retrieve()` 严格按 `session_id` 过滤，导致跨会话知识无法召回
2. **向量检索可能未启用或效果差**：默认使用 HashEmbedder（字面哈希），不是真正的语义嵌入
3. **RRF 权重分配不合理**：HashEmbedder 下关键词路与向量路高度重叠，融合价值有限
4. **Episodic 记忆无 FTS5 支持**：只有 LIKE 搜索，性能差且中文分词效果有限
5. **core 槽位预算固定且过小**：检索命中只有 2 条能进入 core，可能截断高重要性结果
6. **向量回填上限过低**：默认 500 条，记忆数量多时部分记忆无向量

### 1.2 优化目标

- **召回命中率提升 50%+**：跨会话知识可被召回
- **检索质量提升**：使用语义嵌入时向量路权重提升
- **性能优化**：Episodic 记忆添加 FTS5 索引
- **可观测性**：添加召回质量监控日志

---

## 2. 技术方案

### 2.1 核心改动

#### **改动 1：放宽 session_id 过滤（软过滤策略）**

**文件**: `backend/adapters/out/memory/adapter.py`

**方案**: 实现"软过滤"——同会话记忆加分，跨会话记忆降分但不完全过滤

```python
# 当前代码（第 195 行）
self.vector_store.search(query, top_k=limit, session_id=session_id)

# 优化后
# 先不按 session 过滤，取 top_k * 3
vec_results = self.vector_store.search(query, top_k=limit * 3)
# 同会话加分，跨会话降分
for vr in vec_results:
    if vr.get("session_id") == session_id:
        vr["score_boost"] = 1.5  # 同会话 +50%
    else:
        vr["score_boost"] = 0.7  # 跨会话 -30%
# 按调整后分数排序，取 top_k
```

**关键词检索同理**：`MemoryManager.recall()` 也需要软过滤

#### **改动 2：动态 RRF 权重（按嵌入器能力）**

**文件**: `backend/adapters/out/memory/adapter.py`

**方案**:
- 如果使用 HashEmbedder（非语义嵌入）：跳向量路，只用关键词
- 如果使用语义嵌入（ONNX/HTTP）：向量权重 0.7-0.8

```python
# 当前代码（第 210-214 行）
base_weights = (
    [0.3, 0.7] if getattr(self.embedder, "is_semantic", False)
    else [0.6, 0.4]
)

# 优化后
if not getattr(self.embedder, "is_semantic", False):
    # HashEmbedder：跳向量路，只用关键词
    fused = keyword_items
else:
    # 语义嵌入：向量权重 0.8
    weights = [0.2, 0.8]
    fused = reciprocal_rank_fusion([keyword_items, vector_items], weights=weights, k=60)
```

#### **改动 3：为 Episodic 记忆添加 FTS5 支持**

**文件**: `backend/memory/episodic.py`

**方案**: 参考 `SemanticMemory` 的实现，添加 FTS5 索引

1. 创建 `memories_episodic_fts` 虚拟表
2. `save()` / `update_tags()` 时同步 FTS 索引
3. `search()` 优先走 FTS5，回退 LIKE

**预计收益**:
- 搜索性能提升 5-10x
- 中文分词效果显著提升

#### **改动 4：动态 core 槽位预算**

**文件**: `backend/adapters/out/memory/adapter.py`

**方案**: 根据检索命中数量动态调整

```python
# 当前代码（第 259-261 行）
_CORE_PROFILE_LIMIT = 3
_CORE_PROJECT_LIMIT = 2
_CORE_RETRIEVED_LIMIT = 2

# 优化后
_CORE_PROFILE_LIMIT = 3
_CORE_PROJECT_LIMIT = 2
# 动态调整：检索命中多时放宽
if len(fused) >= 5:
    _CORE_RETRIEVED_LIMIT = 3
elif len(fused) >= 2:
    _CORE_RETRIEVED_LIMIT = 2
else:
    _CORE_RETRIEVED_LIMIT = 1
```

#### **改动 5：提升向量回填上限**

**文件**: `backend/adapters/out/memory/adapter.py`

**方案**: 默认值从 500 提升到 2000

```python
# 当前代码（第 137 行）
max_backfill = int(os.getenv("SAGE_VEC_BACKFILL_MAX", "500"))

# 优化后
max_backfill = int(os.getenv("SAGE_VEC_BACKFILL_MAX", "2000"))
```

#### **改动 6：添加召回质量监控日志**

**文件**: `backend/adapters/out/memory/adapter.py`

**方案**: 在 `retrieve()` 方法中添加详细日志

```python
logger.info(
    "[retrieval] embedder=%s is_semantic=%s variant=%s weights=%s "
    "keyword_hits=%s vector_hits=%s fused=%s core=%s session_id=%s",
    type(self.embedder).__name__,
    getattr(self.embedder, "is_semantic", False),
    variant,
    weights,
    len(keyword_items),
    len(vector_items),
    len(fused),
    len(core),
    session_id[:8] if session_id else None,
)
```

---

## 3. 实施步骤

### Phase 1: 快速优化（1-2 天）✅ 已完成

- [x] **Task 1**: 放宽 session_id 过滤（软过滤策略）
  - 修改 `MemoryAdapter.retrieve()`
  - 修改 `MemoryManager.recall()`
  - 添加单元测试

- [x] **Task 2**: 动态 RRF 权重（HashEmbedder 跳向量路）
  - 修改 `MemoryAdapter.retrieve()`
  - 添加单元测试

- [x] **Task 3**: 动态 core 槽位预算
  - 修改 `MemoryAdapter.retrieve()`

- [x] **Task 4**: 提升向量回填上限（500 → 2000）
  - 修改 `MemoryAdapter._maybe_start_backfill()`

- [x] **Task 5**: 添加召回质量监控日志
  - 修改 `MemoryAdapter.retrieve()`

### Phase 2: 中期优化（3-5 天）✅ 已完成

- [x] **Task 6**: 为 Episodic 记忆添加 FTS5 支持
  - 修改 `backend/memory/episodic.py`
  - 添加 FTS5 索引创建逻辑
  - 修改 `save()` / `search()` 方法
  - 添加单元测试
  - 性能测试

### Phase 3: 长期优化（可选）🚀

- [ ] **Task 7**: 引入混合检索策略（关键词 + 向量 + 知识图谱）
- [ ] **Task 8**: 添加召回质量评估（离线评估 + 在线评估）

---

## 4. 测试计划

### 4.1 单元测试

- [ ] 软过滤策略测试（同会话加分，跨会话降分）
- [ ] 动态 RRF 权重测试（HashEmbedder 跳向量路）
- [ ] 动态 core 槽位测试
- [ ] Episodic FTS5 搜索测试

### 4.2 集成测试

- [ ] 跨会话知识召回测试
- [ ] 多路检索融合测试
- [ ] 性能测试（Episodic FTS5 vs LIKE）

### 4.3 回归测试

- [ ] 现有记忆系统测试全部通过
- [ ] 无新增 lint 错误

---

## 5. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 软过滤可能导致不相关记忆被召回 | 中 | 降分幅度可调（0.7 → 0.5） |
| FTS5 索引增加写入开销 | 低 | 参考 SemanticMemory，开销可接受 |
| 动态 core 槽位可能不稳定 | 低 | 设置上下限（1-3） |

---

## 6. 验收标准

- [ ] 跨会话知识可被召回（软过滤生效）
- [ ] HashEmbedder 下向量路被跳过（性能提升）
- [ ] 语义嵌入下向量权重提升到 0.8
- [ ] Episodic 记忆搜索性能提升 5x+
- [ ] core 槽位动态调整生效
- [ ] 向量回填上限提升到 2000
- [ ] 召回质量监控日志完整
- [ ] 所有测试通过
- [ ] 无新增 lint 错误

---

## 7. 参考资料

- 代码分析：`backend/adapters/out/memory/adapter.py`
- 代码分析：`backend/memory/manager.py`
- 代码分析：`backend/memory/episodic.py`
- 代码分析：`backend/memory/semantic.py`
- 代码分析：`backend/memory/vector_store.py`
