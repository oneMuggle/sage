# 记忆质量优化（Phase 1–4）

> 日期：2026-11-04 起草 / 2026-11-05 归档 / 2026-11-09 main 侧 port 归档  
> 分支：`fix/memory-quality-improvements`（win7）/ `feat/memory-quality-main-port`（main）  
> 状态：**已完成**  
> PR：
> - win7 [#2878](https://github.com/oneMuggle/sage/pull/2878)（Phase 1–4 全套，release/win7 基线）
> - main [#2967](https://github.com/oneMuggle/sage/pull/2967)（Phase 1–4 main 侧 port）

## main 侧 port 说明（2026-11-09）

main 分支**没有** `backend/memory/lifecycle.py` / `hooks.py` / `embedding_queue.py`，
这三个 win7-only 模块经核实**均非** Phase 1–4 代码的直接依赖（只被 `lifecycle.py` 自身调用）。
因此 main port 采用**结构适配**而非直接 cherry-pick：

| win7 交付物 | main 侧处理 |
|---|---|
| `lifecycle.py` / `hooks.py` / `embedding_queue.py` | ❌ 不 port（main 无等价物，Phase 1–4 不依赖） |
| `manager.aremember_with_conflict_check`（async） | ❌ 不 port（main 无调用方）；只 port 同步路径 `memorize_with_conflict_check` 的已知事实过滤增强 |
| `scheduler/evolution.py` 的 618 行差异 | ⚠️ 只挑 `preference_labels` 相关最小切（约 10–20 行），其余不动 |
| `MemoryQualityScorer` / `feedback_store` / `preference_labels` | ✅ 直接 port |
| 质量/反馈路由、列表 enrichment、Phase 4 前端 | ✅ 直接 port |

py38 兼容护栏：main 侧代码必须能被 cherry-pick 回 `release/win7`，
故 `zip()` 一律不带 `strict=`（3.10+ 专属），改用 `# noqa: B905` 抑制 ruff 告警。

## 实施结果摘要

| Phase | 交付内容 | 核心 commit / PR |
|---|---|---|
| Phase 1 | 提取门槛升级（对话长度 / 重要性评分）+ 否定词插入 NOOP 修复 | `2a90a9628` |
| Phase 2 | 冲突消解（`aremember_with_conflict_check`）+ 已知事实过滤 | `feature/memory-quality-improvements` early commits |
| Phase 3 | 主题簇巩固 + 低质量记忆软失效 + `MemoryQualityScorer` | `19629a2da` |
| Phase 4 | 质量可视化 / 批量清理 / 来源追踪 / 反馈 / 使用提示 | `9a2db1ff3` |
| 同步 | 合并上游 release/win7 28 个 commit，解决 4 处冲突 | `b6080a431` |


## 一、背景与目标

### 1.1 问题诊断

用户反馈 Sage 的记忆系统相比 Claude Code 等主流 AI 应用存在以下问题：

#### 问题 1：记忆碎片化严重
- **根因**：
  - `existing_facts[:20]` 截断导致 LLM 无法感知全量记忆
  - 对话长度门槛过低（用户消息 ≥ 20 字符即触发）
  - 关键词降级提取不考虑已有记忆
- **效果**：大量低价值、重复的记忆被创建

#### 问题 2：奇怪的 "response_length:detai" 记忆
- **根因**：机器键名直接拼入用户可读内容 + 显示层截断
- **格式问题**："用户偏好 response_length: detailed" 混用中英文，可读性差

#### 问题 3：偏好描述过于简单
- **根因**：
  - 固定三维度（response_length / tone / detail_level）
  - 枚举值限制（只有 "detailed"、"friendly" 等）
  - 丢失来源上下文（哪次对话学到的）
- **效果**：偏好描述缺乏丰富度和可操作性

#### 问题 4：去重效果差
- **根因**：`SequenceMatcher` 是字符级相似度，对中文语义不敏感
- **效果**：语义重复的记忆无法被有效合并（如"用户喜欢简洁回答" vs "用户偏好简短回复"）

#### 问题 5：进化日志显示不一致
- **Bug 1**：`EvolutionPanel` 检查 `'completed'`，后端写 `'success'` → 所有记录显示灰色
- **Bug 2**：`EvolutionPanel` 时间戳把秒当毫秒 → 日期显示为 1970 年
- **Bug 3**：错误静默吞掉，用户无感知

### 1.2 优化目标

1. **提升记忆质量**：减少碎片化，增强结构化
2. **改进用户体验**：修复显示 bug，增强可读性
3. **增强智能程度**：引入语义去重，改进偏好学习
4. **对标主流应用**：参考 Claude Code、ChatGPT 的最佳实践

---

## 二、技术方案

### 2.1 阶段 1：修复已知 Bug（P0，1 周）

#### 2.1.1 修复进化日志显示问题

**文件**：`src/widgets/evolution/EvolutionPanel.tsx`

**Bug 1：Status 值不匹配**
```typescript
// L96: 检查错误的状态值
- if (log.status === 'completed') {
+ if (log.status === 'success') {
```

**Bug 2：时间戳格式错误**
```typescript
// L108: 把秒当毫秒
- <span>{new Date(log.created_at).toLocaleDateString()}</span>
+ <span>{new Date(log.created_at * 1000).toLocaleDateString()}</span>
```

**Bug 3：错误静默吞掉**
```typescript
// L41: 添加用户可见的错误提示
- } catch (error) {
-   console.error('获取进化日志失败:', error);
- }
+ } catch (error) {
+   setError(error instanceof Error ? error.message : '加载失败');
+ }
```

**Demo 数据修复**：`src/shared/api/demoFixturesSessionsAndAgents.ts`
```typescript
// L202: 与后端保持一致
- status: 'completed'
+ status: 'success'
```

#### 2.1.2 修复偏好显示格式

**文件**：`backend/scheduler/evolution.py`

**L656-659：改为中文标签映射**
```python
# 新增常量
PREFERENCE_LABELS = {
    "response_length": "回复长度",
    "tone": "交互风格", 
    "detail_level": "详细程度",
}

PREFERENCE_VALUE_LABELS = {
    "response_length": {
        "short": "简短",
        "medium": "适中",
        "long": "较长",
        "detailed": "详细",
    },
    "tone": {
        "friendly": "友好",
        "professional": "专业",
        "humorous": "幽默",
        "formal": "严肃",
    },
    "detail_level": {
        "brief": "简洁",
        "medium": "适中",
        "comprehensive": "全面",
    },
}

def _translate_preference_value(key: str, value: str) -> str:
    """翻译偏好值为中文"""
    return PREFERENCE_VALUE_LABELS.get(key, {}).get(value, value)

# 修改写入逻辑
profile_store.add(
    content=f"用户偏好{PREFERENCE_LABELS.get(key, key)}: {_translate_preference_value(key, value)}",
    category="preference",
    importance=6,
)
```

### 2.2 阶段 2：提升记忆质量（P1，2 周）

#### 2.2.1 改进记忆提取策略

**文件**：`backend/memory/extractor.py`

**优化 1：提高提取门槛**
```python
# L90-91: 提高门槛
- if len(user_message) < 20 and len(assistant_message) < 50:
+ if len(user_message) < 50 and len(assistant_message) < 100:
    return []
```

**优化 2：增加重要性过滤**
```python
# 新增高价值信号检测
HIGH_VALUE_SIGNALS = [
    r"我是(.*?)专家",  # 用户身份
    r"(不要|永远不)(做|用)",  # 强烈偏好
    r"我们(决定|选择)",  # 重要决策
    r"(项目|系统)使用",  # 项目事实
    r"(喜欢|偏好|习惯)",  # 明确偏好
]

def should_extract(self, user_message: str, assistant_message: str) -> bool:
    """只提取高价值信息"""
    # 用户消息包含高价值信号
    if any(re.search(pattern, user_message) for pattern in HIGH_VALUE_SIGNALS):
        return True
    
    # 助手回复包含重要技术决策
    if re.search(r"(建议|推荐|最佳实践)", assistant_message):
        return True
    
    return False
```

**优化 3：改用向量检索找相关已知事实**
```python
# L116-119: 替换截断逻辑
async def extract(self, user_message, assistant_message, existing_facts, ...):
    # 用当前对话的 embedding 检索最相关的 top 10 已知事实
    query = f"{user_message} {assistant_message}"
    relevant_facts = await self.vector_store.search(
        query=query,
        limit=10,
        min_similarity=0.7
    )
    
    # 传给 LLM 的是最相关的事实，而不是随机的前 20 条
    prompt = EXTRACTION_PROMPT.format(
        user_message=user_message[:1000],  # 增加截断长度
        assistant_message=assistant_message[:1000],
        existing_facts="\n".join([f["content"] for f in relevant_facts]),
        tool_observations=tool_observations[:1000],
    )
```

#### 2.2.2 增强偏好学习

**文件**：`backend/scheduler/evolution.py` - `PreferenceLearningTask`

**优化 1：扩展偏好维度**
```python
# 扩展偏好维度（标签与合法取值统一收敛到 backend/memory/preference_labels.py）
PREFERENCE_DIMENSION_LABELS = {
    "response_length": "回复长度",
    "tone": "交互风格",
    "detail_level": "详细程度",
    # 新增维度
    "code_style": "代码风格",
    "comment_preference": "注释偏好",
    "explanation_depth": "解释深度",
}
```

**优化 2：允许自由文本偏好**
```python
async def _analyze_preferences_with_llm(self, llm, messages) -> Tuple[Dict, List[Dict]]:
    prompt = """
    分析用户的反馈，提取偏好。输出 JSON：
    {
      "structured": {"response_length": "short"},
      "free_text": [
        {"category": "代码风格", "preference": "偏好函数式编程，避免 class"}
      ]
    }
    """
    # 返回 (structured, free_text)
```

**优化 3：存储来源上下文** — ❌ **未实施**
`UserProfileStore.add()` 没有 `metadata` 参数（签名固定为
`content / category / importance`），无法逐条挂溯源字段。
溯源改由语义记忆层的 `source_session_id` / `source_turn_id` /
`memory_category` 承担（见 Task 2.0）。

#### 2.2.3 改进去重机制（引入向量相似度）

**文件**：`backend/memory/conflict.py` - `MemoryConflictResolver`
**状态**：✅ 已实施（Task 2.4）—— 实施细节与初稿有偏差，原因见下

**最终设计：三条独立判定带**

| 带 | 条件 | 判定 | 语义 |
|---|---|---|---|
| NOOP | 字面 ≥ 0.97 | 丢弃新事实，复用旧 ID | 字面近重复必然是同一条事实 |
| UPDATE | 字面 ∈ [0.78, 0.97) | 写新行 + 旧行失效 | 同一事实的不同措辞 |
| UPDATE | 语义 ≥ 0.90 | 写新行 + 旧行失效 | 语义等价但措辞迥异 |
| ADD | 其余 | 写新行 | — |

关键约束：**语义相似只触发 UPDATE，永不触发 NOOP**。
语义近但取值相反的一对（"用户住在上海市浦东区" / "用户住在北京市朝阳区"）
判 NOOP 会把过时事实留在库里；判 UPDATE 才能让最新事实生效。
UPDATE 同时完成了去重（两条塌缩成一条有效记忆）。

**为什么否掉初稿的加权公式**

初稿是 `0.3 * literal + 0.7 * semantic`，NOOP 0.88 / UPDATE 0.75。
代入实测字面相似度：

| 记忆对 | 字面 | 语义 | 加权 | 初稿判定 | 正确判定 |
|---|---|---|---|---|---|
| 用户喜欢使用 ruff 格式化 / 用户**不**喜欢使用 ruff 格式化 | 0.968 | 0.95 | 0.955 | NOOP ❌ | UPDATE |
| 用户住在上海市浦东区 / 用户住在北京市朝阳区 | 0.600 | 1.00 | 0.880 | NOOP ❌ | UPDATE |
| 用户喜欢简洁回答 / 用户偏好简短回复 | 0.500 | 0.85 | 0.745 | ADD ❌ | UPDATE |

两处失效：

1. **NOOP 被语义污染（致命）** —— 前两行取值相反却判 NOOP，新事实被丢弃、
   过时事实留在库里。单一加权值无法区分"同一事实的不同措辞"和
   "取值相反的事实"；这是数据正确性问题，不是阈值调参能解决的。
2. **去重召回不稳** —— 第三行要语义 ≥ 0.857 才够得着 UPDATE 阈值
   （`0.3×0.5 + 0.7s ≥ 0.75`），真实改述常在 0.85 上下，临界；
   同时 NOOP 带从 0.97 外扩到 0.88，"字面中等 + 语义高"的一整类记忆
   都会被判 NOOP。

改为三条独立带后：字面带阈值完全不动（0.97 / 0.78，行为零变更），
语义另开一条只管 UPDATE 的带，语义与字面互不干扰。

**辅助方法**

- `_calculate_similarity(a, b)` —— 混合相似度，取 `max(字面, 语义)`。
  保留初稿的调用形态，满足验收用例 `>= 0.88`（语义命中时）。
- `_annotate_semantic(content, candidates)` —— 批量编码（1 次新内容 +
  1 次 `encode_batch` 候选），余弦写入 `Candidate.semantic_similarity`。

**opt-in：缺省零行为变更**

语义路径只在 `embedder.is_semantic == True` 时开启。
缺省 `HashEmbedder.is_semantic == False` → 整条语义路径关闭，
判定结果与改造前逐位一致。只有用户显式配置 ONNX（`SAGE_EMBEDDER=onnx`）
或 HTTP 模型端点（`SAGE_EMBEDDER=model`）时语义去重才真正生效。

**嵌入器共享**

ONNX 语义模型约 40 MB，`MemoryAdapter` 与冲突消解器各自
`create_embedder()` 会把同一份模型加载两遍。新增
`embedder_factory.get_shared_embedder()` / `set_shared_embedder()` 进程级单例；
`MemoryManager` 侧传**工厂函数引用**而非实例 —— 用户热切换嵌入模式后
resolver 下次判定立即用上新实例，无需重建。

**已知限制**

1. 候选召回仍是 FTS5（OR 分词查询），改述对靠共同 token
   （如"用户"）召回；召回排序不按相关度，真改述排在候选窗口外的情形
   本轮不覆盖。
2. ~~**字面 NOOP 带会被「否定词插入」骗过**~~ —— 已由 Task 2.6 修复：
   长句插一个字只损失 2/(2n+1) 相似度，31 字句插「不」实测字面
   0.984 ≥ 0.97，改造前会判 NOOP 丢弃新事实。语义带救不了 —— 否定句
   的余弦同样高（≈0.95）。现在 NOOP 前比对两侧否定极性，极性相反时
   改判 UPDATE（写新行 + 旧行失效）。

### 2.3 阶段 3：增强记忆整合能力（P2，2 周）

#### 2.3.1 强化 MemoryReflectionTask

**文件**：`backend/scheduler/evolution.py` - `MemoryReflectionTask`

**优化 1：增加分组大小**
```python
# L1399: 增加分组大小
- LLM_GROUP_LIMIT = 40
+ LLM_GROUP_LIMIT = 80  # 更多记忆一起合并
```

**优化 2：增加内容截断长度**
```python
# L1406: 增加内容长度
- LLM_CONTENT_TRUNC = 160
+ LLM_CONTENT_TRUNC = 300  # 更完整的上下文
```

**优化 3：改进 LLM 合并提示词**
```python
prompt = """
你是记忆整理专家。下面是同一主题的多条记忆，请：
1. 合并语义重复的记忆为一条精炼的事实
2. 删除过时或错误的记忆
3. 保留高价值、独特的记忆

输入记忆：
{memories_text}

输出 JSON 数组：
[
  {{"op": "MERGE", "ids": [1, 3, 5], "content": "合并后的精炼事实", "category": "user_pref"}},
  {{"op": "KEEP", "id": 2, "reason": "独特且重要"}},
  {{"op": "INVALIDATE", "id": 4, "reason": "与记忆#1冲突且已过时"}}
]
"""
```

#### 2.3.2 引入记忆巩固机制

**新增方法**：`_consolidate_related_memories()`
```python
async def _consolidate_related_memories(self):
    """将相关记忆组织成主题簇"""
    
    # 1. 按 category 分组
    memories_by_category = await self._group_by_category()
    
    # 2. 在每个类别内，用向量相似度聚类
    for category, memories in memories_by_category.items():
        clusters = self._cluster_by_similarity(memories, threshold=0.75)
        
        # 3. 每个簇生成一个主题摘要
        for cluster in clusters:
            if len(cluster) >= 3:  # 至少 3 条相关记忆
                summary = await self._generate_topic_summary(cluster)
                
                # 4. 创建"主题记忆"，关联原始记忆
                await self.create_summary_memory(
                    content=summary,
                    category=f"{category}_summary",
                    source_memory_ids=[m["id"] for m in cluster],
                    importance=7,
                )
```

#### 2.3.3 增加记忆质量评分器

**新文件**：`backend/memory/quality_scorer.py`
```python
class MemoryQualityScorer:
    """记忆质量评分器"""
    
    def calculate_quality_score(self, memory: dict) -> float:
        """
        计算记忆质量分（0-1）
        
        维度：
        1. 清晰度（是否完整、可读）
        2. 重要性（importance 字段）
        3. 新鲜度（recency）
        4. 使用频率（access_count）
        5. 独特性（与其他记忆的相似度）
        """
        
        # 1. 清晰度（长度适中、无截断）
        clarity = self._score_clarity(memory["content"])
        
        # 2. 重要性
        importance = memory.get("importance", 5) / 10
        
        # 3. 新鲜度（半衰期 60 天）
        days_old = (time.time() - memory["created_at"]) / 86400
        recency = 0.5 ** (days_old / 60)
        
        # 4. 使用频率
        access_count = memory.get("access_count", 0)
        usage = min(access_count / 10, 1.0)
        
        # 5. 独特性
        uniqueness = self._score_uniqueness(memory)
        
        # 加权组合
        quality = (
            0.25 * clarity +
            0.25 * importance +
            0.20 * recency +
            0.15 * usage +
            0.15 * uniqueness
        )
        
        return quality
    
    def should_delete(self, memory: dict) -> bool:
        """判断是否应该删除"""
        quality = self.calculate_quality_score(memory)
        
        # 质量分 < 0.3 且超过 90 天未访问 → 删除
        days_since_access = (time.time() - (memory.get("accessed_at") or memory["created_at"])) / 86400
        
        return quality < 0.3 and days_since_access > 90
```

**集成到 MemoryPruningTask**：
```python
# backend/scheduler/evolution.py - MemoryPruningTask

async def _prune_low_quality_memories(self):
    """清理低质量记忆"""
    scorer = MemoryQualityScorer()
    
    cursor = await self.db.execute("""
        SELECT * FROM memories_episodic
        WHERE is_valid = 1
    """)
    
    memories = await cursor.fetchall()
    
    deleted_count = 0
    for memory in memories:
        if scorer.should_delete(memory):
            await self._invalidate_memory(
                memory["id"],
                reason=f"低质量记忆自动清理（quality={scorer.calculate_quality_score(memory):.2f}）"
            )
            deleted_count += 1
    
    return deleted_count
```

---

## 三、实施步骤

> 下文是 **win7 侧原始实施记录**，保留完整决策过程（含被推翻的方案与原因）。
> main 侧 port 的对应差异见文首「main 侧 port 说明」；凡涉及
> `lifecycle.py` / `aremember_with_conflict_check` 的条目，main 侧走的是
> 同步路径 `memorize_with_conflict_check`，其余条目两侧一致。

### Phase 1：修复已知 Bug（1 周）
- [x] **Task 1.1**：修复 `EvolutionPanel` 的 status 值不匹配（`STATUS_DISPLAY` 映射表 + 未知值回落原值）
- [x] **Task 1.2**：修复 `EvolutionPanel` 的时间戳格式（秒 → 毫秒 `* 1000`）
- [x] **Task 1.3**：修复偏好显示格式（新增 `backend/memory/preference_labels.py` 中文标签映射）
- [x] **Task 1.4**：添加错误提示和重试机制（`error` state + 错误 UI + 重试按钮）
- [x] **Task 1.5**：修复 Demo 数据的状态值（`demoFixturesSessionsAndAgents.ts` 5 处 `'completed'` → `'success'`）
- [x] **Task 1.6**：编写单元测试验证修复（后端 7 + 前端 6 + 既有 4 个断言更新）

**实施偏差说明**：偏好标签常量未内联在 `evolution.py`，而是抽到独立模块
`backend/memory/preference_labels.py`——因为 `evolution.py`（写入侧）与
`legacy_memory_routes.py`（更新侧）都需要同一份映射，内联会重复且易漂移。

### Phase 2：提升记忆质量（2 周）
- [x] **Task 2.0**：写入路径接入冲突消解（根因修复）
  - `MemoryManager` 新增 `aremember_with_conflict_check` 异步方法：
    冲突判定（`resolve_conflicts`）与 `apply_update` 整体放进 `run_in_executor`，
    不阻塞事件循环；ADD 路径回落 `aremember` 以保留 `source_turn_id` /
    `source_message_id` / `memory_category` 溯源字段
  - `lifecycle._persist_fact` 改走新方法：NOOP 复用既有 id、UPDATE 取代旧行、
    ADD 正常追加；sqlite 异常时退回 `aremember` 不丢事实
  - 新增 6 条专项回归测试（`test_aremember_with_conflict_check.py`）：
    ADD / NOOP / UPDATE / 短内容直写 / resolve 失败兜底 / traceability 透传
  - 既有 79 条记忆相关测试全绿；ruff 全绿
  - **实施偏差**：原计划下调阈值（0.97→0.88 / 0.78→0.75），
    调查后发现字面相似度对中文语义不敏感（jieba-token Dice 约 0.25），
    改为仅在语义 embedder 可用时启用混合相似度（Task 2.4）
- [x] **Task 2.1**：改进记忆提取策略（提高门槛 + 重要性过滤）
  - `MemoryExtractor._should_extract(user_message, assistant_message)` 双向
    门槛：类属性 `_USER_MSG_THRESHOLD = 30` / `_ASSISTANT_MSG_THRESHOLD = 80`
    两侧都低于阈值时默认跳过（纯寒暄不再浪费提取器），但命中
    `HIGH_VALUE_KEYWORDS`（用户身份 / 禁令 / 决策 / 显式偏好 等 40+ 关键词）
    时强制放行——既压住"好的谢谢"式的碎片，又不误伤"我喜欢 ruff"这类
    短但高价值的信息
  - `HIGH_VALUE_KEYWORDS` 用子串匹配（不用正则）：中文分词边界不稳定，
    正则 `\b` 反而漏；子串匹配性能更好、更鲁棒
  - 新增 10 条专项测试（`test_memory_extractor.py::TestExtractionGate`），
    覆盖：短寒暄跳过 / 短+高价值放行 / 助手侧信号放行 / 禁令放行 /
    长消息放行 / 单侧长放行 / 空消息跳过 / 子串匹配 / 端到端短路 LLM /
    端到端仍进 LLM
  - 既有 79 条记忆相关测试全绿；ruff 全绿
  - **实施偏差**：原计划把阈值一次性从 20/50 抬到 50/100（激进策略），
    改为温和 30/80；高价值信号检测原计划用正则，改为子串匹配——中文
    场景正则边界不稳定反而漏
- [x] **Task 2.2**：抽取时提供相关已知事实（替代原「向量检索」方案）
  - `lifecycle._collect_known_facts`：用 `MemoryManager.recall`（FTS5 + jieba）
    按本轮用户消息取 top-8 的 episodic/semantic 事实，`run_in_executor` 不阻塞
    事件循环；任何异常静默降级为空列表，绝不中断记忆写入
  - `lifecycle._extract_facts`：签名探测 `existing_facts` kwarg，旧的两参
    extractor（如 `test_lifecycle.py` 的 `BrokenExtractor`）自动回退两参调用
  - `extractor._select_existing_facts`：token 相关性过滤（无交集丢弃）+
    `EXISTING_FACTS_CHAR_BUDGET=1200` 字符预算（单条超长截断加省略号，
    不突破预算）
  - 新增 11 条专项测试（`test_lifecycle_known_facts.py`）；既有 76 条记忆
    相关测试全绿；ruff 全绿
  - **实施偏差**：原计划用「向量检索 + `min_similarity=0.7`」，但项目默认
    embedder 是 `HashEmbedder`（`is_semantic=False`），向量路在该配置下会被
    直接跳过。改用 `MemoryManager.recall` 的 FTS5 关键词路，语义 embedder
    可用时 `recall` 内部会自动叠加向量召回，无需另开分支
- [x] **Task 2.3**：增强偏好学习（扩展维度 + 自由文本）
  - **维度扩展**：3 → 6，新增 `code_style`（函数式/面向对象/混合）、
    `comment_preference`（无注释/关键注释/详细注释）、
    `explanation_depth`（直接给答案/简要说明/详细推导）；
    标签与合法取值统一收敛到 `backend/memory/preference_labels.py`
    （单一真相源），parser 白名单由 `PREFERENCE_VALUE_LABELS` 派生，
    不再各写一份（曾因两处不同步漏掉新维度）
  - **自由文本偏好**：LLM 输出改为嵌套格式
    `{"structured": {...}, "free_text": [{"category", "preference"}]}`，
    `_parse_preference_json` 同时兼容旧扁平格式；
    自由文本条目做必填校验 + 截断（category ≤20 字 / preference ≤120 字），
    写入 `memories_semantic`（content + summary）与 `user_profile`
    （category="preference"）
  - **关键词路径**：`_analyze_preferences` 覆盖 6 个维度的关键词，
    只返回**有证据**的维度（无命中即不落库）
  - **实施偏差**：原计划保留 3 维基线默认值，改为「仅证据」策略 ——
    `preferences` 表是 `ON CONFLICT(key) DO UPDATE`，写入默认值会覆盖
    用户此前学到的偏好（如曾说「回答简短点」的用户会被重置为 medium）。
    `legacy_memory_routes.py` 按 `key LIKE 'pref_%'` 读取，缺失维度不显示，
    无需补默认值
  - 新增 13 条专项测试（`test_preference_learning_llm.py`：
    嵌套/扁平格式解析、自由文本校验与截断、仅自由文本也落库、
    关键词 6 维命中、无信号返回空）+ 既有 39 条偏好相关测试全绿；
    evolution + memory 套件 112 条全绿；ruff 全绿
- [x] **Task 2.4**：改进去重机制（引入向量相似度）
  - 语义相似度只触发 UPDATE（绝不 NOOP）—— NOOP 会把"上海/北京"这类
    取值相反的事实判成重复，过时数据留在库里；UPDATE 既取代旧事实
    又完成去重
  - 否掉初稿的 `0.3/0.7` 加权 + NOOP 0.88/UPDATE 0.75：
    加权公式下"用户住在上海市浦东区"/"用户住在北京市朝阳区"
    得 0.880 → 判 NOOP（过时事实留存）；改述对字面 0.5 时要语义 ≥ 0.857
    才够得着 UPDATE 阈值。改为三条独立带，字面阈值零变更
  - `conflict.py`：`SEMANTIC_UPDATE_THRESHOLD = 0.90` +
    `SEMANTIC_TARGET_MARGIN = 0.02` + `_cosine_similarity`
    + `_calculate_similarity`（max(字面, 语义)）+ `_annotate_semantic`；
    `Candidate.semantic_similarity`。裕度是评审期补的：语义分对模板化
    短句普遍偏高（"喜欢用 Python"/"喜欢用 Rust" 常 >0.90），不设裕度
    会一次失效多条互不相关的事实 —— 只塌缩与最高分相差 ≤0.02 的近似并列候选。
  - 字面 NOOP 在 `_annotate_semantic` 之前短路（省掉整批编码，HTTP 端点下最贵），
    但配了 `llm_decide` 时不短路（LLM 钩子可把近重复升级为 UPDATE）
  - `adapters/out/memory/adapter.py`：`_resolve_conflict` 的同步冲突判定
    移到 `run_in_executor` —— `SAGE_EMBEDDER=model` 时嵌入走 HTTP，
    阻塞调用会卡满事件循环（默认 10s 超时）；与
    `aremember_with_conflict_check` 的做法一致
  - `embedder_factory.py`：`get_shared_embedder()` /
    `set_shared_embedder()` 进程级单例（ONNX 模型 40 MB，避免重复加载）
  - `embedder.py`：`ModelEmbedder` 补 `is_semantic = True` —— 原缺此标记，
    HTTP 嵌入端点的部署形态语义去重与向量检索**双双失效**
  - 接线：`MemoryManager(embedder=...)` → resolver；`registry.py` 与
    `core/legacy/agent.py` 传工厂函数引用（支持热切换）；
    `adapters/out/memory/adapter.py` 改用共享实例并在 `reconfigure` 时替换
  - `_current_embedder` 先认实例形态（`hasattr(source, "encode")`）再退回
    按工厂调用 —— Mock 的自动属性也可调用，先 `callable()` 会误路由
  - opt-in：`HashEmbedder.is_semantic == False` → 语义路径整条关闭，
    缺省配置行为与改造前逐位一致
  - 新增 21 条专项测试（`test_memory_conflict_semantic.py`：语义改述
    → UPDATE、NOOP 带不被语义污染、嵌入器异常降级、工厂函数热切换、
    HashEmbedder 不开启语义路径、ModelEmbedder 语义标记、端到端换行 +
    supersedes 链、阈值上下沿、近似并列候选只塌缩最高分、余弦边界、
    `encode_batch` 条数不符时整体放弃）；conflict + memory 相邻套件
    945 条全绿（`-k "memory or conflict or lifecycle or preference"`）；
    preference/recall 集成套件 29 条全绿；ruff 全绿
- [x] **Task 2.5**：编写集成测试验证效果
  - 新增 `backend/tests/integration/test_memory_quality_pipeline.py`（7 条），
    驱动真实写入链 `MemoryLifecycleManager.on_turn_complete` → `MemoryManager`
    → SQLite，验证跨任务组合后的用户可见效果：
    语义改述跨轮次塌缩成一条（碎片化收敛）、取值相反事实判 UPDATE 且
    最新事实生效、缺省 HashEmbedder 下两条并存（opt-in 行为零变更）、
    嵌入器故障仍逐条落库、无关事实不被误合并、Task 2.2 的已知事实
    进入下一轮 `existing_facts`
  - 夹具对先断言字面相似度 < 0.78 —— 保证用例确实在测语义路径，
    而不是被字面 UPDATE 带顺带通过
- [x] **Task 2.6**：修复字面 NOOP 的否定词插入误判（独立任务）
  - `conflict.py` 新增 `_has_negation` / `_negation_flipped`：
    中英文否定词识别（不/没/无/非/未/别/勿、not/no/never/without/n't）
  - 字面 NOOP 带只接受否定极性相同的候选；极性相反的字面近重复
    （实测长句 0.988）显式归入 UPDATE 带 —— 不能只否决 NOOP，
    否则会掉到 ADD 产生两条并存
  - 误报（"非常/无论/未来"）只会把 NOOP 降级成 UPDATE，不丢事实
  - 新增 5 条用例（含前提断言 0.988 ≥ 0.97、端到端换行、同极性仍 NOOP）；
    记忆/冲突/生命周期/偏好相邻套件 1109 passed / 21 skipped

### Phase 3：增强记忆整合（2 周）
- [x] **Task 3.1**：强化 MemoryReflectionTask（增加分组大小 + 内容长度）
- [x] **Task 3.2**：引入记忆巩固机制（主题簇 + 摘要生成）
- [x] **Task 3.3**：增加记忆质量评分器
- [x] **Task 3.4**：集成到 MemoryPruningTask
- [x] **Task 3.5**：编写端到端测试验证效果

### Phase 4：优化用户体验（1 周）
- [x] **Task 4.1**：在记忆库页面显示"如何使用"提示
- [x] **Task 4.2**：增加记忆来源追踪（哪次对话产生的）
- [x] **Task 4.3**：支持用户批量删除低质量记忆
- [x] **Task 4.4**：增加记忆质量可视化
- [x] **Task 4.5**：用户测试和反馈收集

---

## 四、风险评估与依赖

### 4.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 向量检索性能下降 | 记忆提取变慢 | 增加缓存，限制检索数量 |
| LLM 合并质量不稳定 | 可能丢失重要记忆 | 保留原始记忆，只标记为 superseded |
| 质量评分阈值不当 | 误删重要记忆 | 保守阈值，用户可恢复 |

### 4.2 依赖

- **向量存储**：需要 `vector_store.py` 支持批量检索
- **Embedder**：需要 `embedder.py` 支持中英文混合嵌入
- **LLM 服务**：需要 LLM 配置可用（合并、摘要生成）

### 4.3 兼容性

- **数据库 schema**：无需修改，复用现有字段
- **API 接口**：无需修改，复用现有端点
- **前端组件**：需修改 `EvolutionPanel.tsx`、`MemoryBrowser.tsx`

---

## 五、预期效果

| 指标 | 当前 | 优化后 | 提升 |
|------|------|--------|------|
| 记忆碎片化程度 | 高 | 低 | -60% |
| 重复记忆比例 | 30% | 10% | -67% |
| 偏好描述丰富度 | 3 维度 | 10+ 维度 | +233% |
| 记忆质量分均值 | 0.5 | 0.75 | +50% |
| 进化日志显示准确率 | 0%（EvolutionPanel） | 100% | +100% |

---

## 六、参考

- **Claude Code**：MEMORY.md 索引 + 独立文件存储，强调可读性和用户控制
- **ChatGPT Dreaming**：后台异步整理，自动合并和遗忘
- **Cursor**：项目级隔离，支持提升为团队规则
- **GitHub Copilot**：仓库级持久理解，跨 Agent 共享

---

## 七、附录

### 7.1 关键文件清单

- `backend/memory/extractor.py` — 事实提取
- `backend/memory/conflict.py` — 冲突消解
- `backend/memory/consolidation.py` — 主题簇巩固
- `backend/memory/manager.py` — 同步路径已知事实过滤
- `backend/memory/quality_scorer.py` — 五维质量评分（main 新增）
- `backend/memory/feedback_store.py` — `memories_feedback` 表读写（main 新增）
- `backend/memory/preference_labels.py` — 机器 key → 中文标签映射（main 新增）
- `backend/api/legacy_memory_quality_routes.py` — `/memory/quality-candidates` + `/memory/batch-delete`（main 新增）
- `backend/api/legacy_memory_feedback_routes.py` — `/memory/{id}/feedback`（main 新增）
- `backend/api/legacy_memory_list_routes.py` — 列表 `quality_score` 注入
- `backend/scheduler/evolution.py` — 进化任务
- `backend/memory/user_profile.py` — 画像存储
- `src/widgets/evolution/EvolutionPanel.tsx` — 进化日志显示
- `src/widgets/memory/MemoryBrowser.tsx` — 记忆浏览器（质量条 / 选择模式 / 反馈按钮 / 来源会话）
- `src/widgets/memory/MemoryUsageHint.tsx` — 记忆库使用提示（main 新增）
- `src/widgets/memory/useSessionInfo.ts` — 来源会话标题 hook（main 新增）

### 7.2 测试用例

**记忆提取测试**：
```python
def test_extract_high_value_memory():
    """测试高价值记忆提取"""
    user_msg = "我是 TypeScript 专家，喜欢函数式编程"
    assistant_msg = "好的，我会直接给你高级方案"
    
    facts = extractor.extract(user_msg, assistant_msg, ...)
    
    assert len(facts) >= 1
    assert any("TypeScript" in f["content"] for f in facts)

def test_skip_low_value_memory():
    """测试低价值对话不提取"""
    user_msg = "好的"
    assistant_msg = "有什么其他问题吗？"
    
    facts = extractor.extract(user_msg, assistant_msg, ...)
    
    assert len(facts) == 0
```

**去重测试**（Task 2.4 落地后 —— 语义命中时混合相似度 ≥ 0.88；
语义路径仅在 `is_semantic=True` 的嵌入器下开启）:
```python
def test_semantic_deduplication():
    """测试语义去重"""
    memory1 = "用户喜欢简洁回答"
    memory2 = "用户偏好简短回复"

    similarity = resolver._calculate_similarity(memory1, memory2)

    assert similarity >= 0.88
```

**偏好学习测试**：
```python
def test_extract_free_text_preference():
    """测试自由文本偏好提取"""
    messages = [
        {"role": "user", "content": "我希望代码有详细注释"},
        {"role": "assistant", "content": "好的，我会添加注释"},
    ]
    
    prefs = await preference_task._extract_preferences_with_llm(messages)
    
    assert "free_text" in prefs
    assert any("注释" in p["preference"] for p in prefs["free_text"])
```

---

## 八、进化执行与补跑（2026-11-17）

### 8.1 根因

用户 Win7 端约 300 条记忆长期未合并/修剪。排查确认三层叠加：

1. **调度与桌面生命周期不匹配**：进化任务默认 cron 在 02:00–05:30，
   应用关闭/系统睡眠即错过；`misfire_grace_time=300`，启动后不补跑。
2. **时间戳单位失配**：`memories_episodic` / `memories_semantic` /
   `sessions` 写入毫秒，而 `DailySummaryTask` / `MemoryPruningTask` /
   `ImportanceReevaluationTask` / `MemoryConsolidationTask` 的阈值按秒比较。
   后果：每日摘要恒 0 会话、30 天修剪永不命中、重要度从不衰减。
   单测按秒造数，掩盖了 bug。
3. **门槛与职责不处理正常记忆**：`max_memories=1000`；硬删除只针对
   `importance<=1/<=3`；质量软失效要求 `<0.3` 且 90 天未访问；
   `MemoryReflectionTask` 只看近 7 天、每表 120 条；`memory_consolidation`
   实际只做晋升/衰减，不合并重复。

### 8.2 修复

- 新增 `backend/memory/time_utils.py`：`now_ms()` / `to_ms()` 作为毫秒
  单一真相源；`evolution_log.created_at` 仍为秒（前端契约）。
- 新增 schema migration v18：把 `sessions` / `messages` /
  `memories_episodic` / `memories_semantic` / `memories_evolution_log`
  中历史秒级时间戳归一为毫秒（`evolution_log` 保持秒）。
- 进化任务阈值统一毫秒；每日摘要改为按
  `COALESCE(last_message_at, updated_at, created_at)` 筛“今天有活动”的
  会话，并对同一会话当天已有 `daily_summary` 去重（启动补跑/重启安全）。
- 新增 `backend/scheduler/evolution_maintenance.py`：
  - 读 `evolution_log` 最近 success/skipped 记录，按日报 26h / 周报 8d
    计算逾期任务；
  - 启动后 90 秒补跑一次，并注册 `system/evolution-catchup`
    （`7,37 * * * *`）每 30 分钟检查；
  - 记忆反思/固化/技能巡检等重任务要求 `IdleDetector` ≥ DEEP；
  - 聚合写 `evolution_type='maintenance_catchup'`、`trigger_type='catch_up'`
    日志，便于区分补跑与 cron。
- `MemoryReflectionTask` 增加 `scan_mode`（`recent` / `backlog` / `both`，
  默认 `both`）与滚动游标 `reflection_backlog_cursor_ms`：每轮额外扫描
  旧记忆（每表默认 80 条），数周覆盖全部存量；有语义嵌入器时近重复阈值
  0.92，否则保持字面 0.97。
- 设置 → 进化页新增手动运行（记忆反思/修剪/固化），展示任务统计；
  `memoryApi.runEvolutionTask(name)` 通用封装。后端
  `/scheduled/evolution/{name}/run` 会把 `ConsolidationResult`（int 子类）
  与 int 型任务结果归一化为 `{promoted, decayed, total}` / `{total}`，
  避免 FastAPI 序列化成裸数字。
- 记忆固化的重要度衰减与修剪/重评估一致，豁免 `environment` 标签记忆。

### 8.3 验证

```bash
# 后端（release/win7，Python 3.8 环境）
pytest backend/tests/unit/test_time_utils.py \
       backend/tests/unit/test_evolution_tasks.py \
       backend/tests/unit/test_evolution_maintenance.py \
       backend/tests/unit/test_memory_reflection_p4.py \
       backend/tests/integration/test_memory_phase3_pipeline.py -q

# 前端
npx vitest run src/shared/api/__tests__/memoryConsolidation.test.ts \
  src/widgets/evolution/__tests__/EvolutionPanel.status.test.tsx
npm run typecheck
```

### 8.4 后续（P2/P3）

- 记忆管理中心：按主题/类别聚合、编辑/合并/删除/固定/忘记、来源追踪；
- 记忆健康看板：总数、重复率、90 天未用占比、上次合并时间；
- 时序实体图（参考 Zep/Graphiti）与评估集（recall@k、用户删除率）。

---

## 九、P0 修复 PR-A（2026-11-24）

> main：[#3275](https://github.com/oneMuggle/sage/pull/3275)；
> win7：[#3277](https://github.com/oneMuggle/sage/pull/3277)

### 9.1 背景

内网 sage 部署后记忆系统出现 4 个症状：记忆条目持续膨胀（476 条且不降）、
只有情景记忆、用户偏好退化成字符串拼接
（`"用户偏好详细程度：detailed"`）、低质量候选 tab 恒空。

排查落到 8 处根因，其中 2 处是 PR 合并后代码审查新发现的缺陷
（编号 7 / 8），一并修掉。

### 9.2 修复清单

| # | 症状 / 根因 | 修复 | 涉及文件 |
|---|---|---|---|
| 1 | `detail_level` 枚举串号：`"详细"` 映射到 `detailed`，应为 `comprehensive` | 修 `detail_prefs` 映射表 | `backend/scheduler/evolution.py` |
| 2 | recall 路径不更新 `accessed_at` / `access_count` → 固化任务的 `>=5` 永不触发 | `get_recent()` 命中后执行 `_touch_access()` | `backend/memory/episodic.py`、`backend/memory/semantic.py` |
| 3 | `lifecycle.py` 硬编码 `memory_type="episodic"`，事件载荷与实际写入层不符（**仅 win7**） | 改用 `_resolve_layer_for_event()` | `backend/memory/lifecycle.py` |
| 4 | `MemoryQualityScorer.should_delete` 无任何调用方 | 接入 `MemoryPruningTask` 的质量合并 + 低质量软失效两条路径 | `backend/scheduler/evolution.py` |
| 5 | 低质量门槛过苛刻（`<0.3` 且 90 天未访问） | `LOW_QUALITY_THRESHOLD` 0.3 → **0.4**；`STALE_DAYS` 90 → **30** | `backend/memory/quality_scorer.py` |
| 6 | LLM 不可用时进化任务仍标 `success`（假成功） | `BaseEvolutionTask._resolve_llm` 统一提权，无 LLM 写 `skipped_no_llm` | `backend/scheduler/evolution.py` |
| 7 | **近重复组长选反**：`_rank_key` 数值项未取负，升序排序把最差的那条副本选成组长 | 数值项取负；`created_at` 经 `_as_millis` 归一后再比较 | `backend/memory/quality_scorer.py` |
| 8 | **近重复整组被抹平**（仅 win7）：低质量软失效只保护"组内仅剩一条有效"者，组大于质量合并上限（100）时保护落空，组长连同剩余副本一起被废 | 规则 6 无条件跳过近重复组的组长 | `backend/scheduler/evolution.py` |

### 9.3 两条修剪路径的分工

`MemoryPruningTask` 里与记忆质量相关的两条规则必须分工明确，顺序也不能反：

| 规则 | 动作 | 触发条件 | 组长待遇 |
|---|---|---|---|
| 5 质量合并 | 软失效（`invalid_at` + `is_valid=0`）+ 清向量 | 质量分低 **且** 长期未访问 **且** 组内存在更优副本 | 永不删 |
| 6 低质量软失效 | 软失效（`invalid_at` + `is_valid=0`） | 质量分低 **且** 长期未访问 | 跳过（见 9.4） |

规则 5 必须**排在规则 6 之前**：合并按组判定、组长受保护；若先软失效，
整组会被一起抹平，重复内容就此丢失。

### 9.4 "是不是组长"不能用 `leaders.get(id) == id` 判定

`find_duplicate_leaders` 把每条记忆映射到所在近重复组的组长，
**没有近重复的记忆映射到自己**。因此：

- `leaders.get(id) == id` 为真，可能是组长，**也可能是独条**；
- 用它当"组长保护"判据 → 独条记忆永远不会被软失效，规则 6 形同虚设。

正确判据是"**有没有别的记忆映射到它**"：

```python
group_leaders = {
    leader for member, leader in leaders.items() if member != leader
}
```

### 9.5 组的大小不该决定内容的生死

缺陷 8 的具体机理：

1. 组内 120 份近重复 → 规则 5 删满单次上限 `_PRUNE_QUALITY_DELETE_MAX = 100`
   条副本后停手，组里还剩组长 + 19 份副本有效；
2. 规则 6 的"仅剩一条有效"保护此时落空（有效成员是 20 条，不是 1 条）；
3. 组长与剩余副本一起被软失效 → **整组内容从检索中消失**。

而同样内容只有 3 份时，规则 5 删光副本、规则 6 保护唯一幸存者 → 留下 1 份。
**同一份内容的生死取决于组的大小，而非内容本身的质量** —— 这是缺陷的实质。

修法（规则 6 无条件跳过组长）后，任何规模的近重复组都会留下组长一份。

### 9.6 时间戳归一

`memories_episodic.created_at` 一律写毫秒，但历史遗留行可能是秒级。
`_rank_key` 里若直接比较，秒级值（~1.8e9）永远小于毫秒值（~1.8e12），
"更新鲜优先"就失效 —— 更新的那条反而被当成副本删掉。
故比较前统一经 `scoring._as_millis` 归一（< 1e11 视为秒）。

### 9.7 双分支差异

| 特性 | main | release/win7 |
|---|---|---|
| `backend/memory/lifecycle.py` | ❌ 不存在（走 `adapters/out/memory/adapter.py` 的 `classify_memory_type("auto", ...)`，本就正确） | ✅ 存在，缺陷 3 在此修 |
| 规则 6（低质量软失效） | ❌ 未实现（`evolution.py` 仅 2015 行，只有规则 5） | ✅ 已实现（2636 行） |
| 缺陷 8（整组被抹平） | 不适用 | ✅ 在此修 |

缺陷 7（组长方向反）两分支共有，两个分支都已修。

### 9.8 验证

```bash
# main（Python 3.10）
pytest backend/tests/unit/test_memory_quality_scorer.py \
       backend/tests/unit/test_evolution_tasks.py \
       backend/tests/integration/test_memory_quality_enrichment.py -q
# 68 passed

# release/win7（Python 3.8）
pytest backend/tests/unit/test_memory_quality_scorer.py \
       backend/tests/unit/test_evolution_tasks.py \
       backend/tests/integration/test_memory_quality_pipeline.py \
       backend/tests/integration/test_memory_quality_routes.py \
       backend/tests/integration/test_memory_quality_enrichment.py -q
# 108 passed
```

回归测试：

- `test_duplicate_leader_is_the_best_copy` —— 组长 = 组内最优副本；
- `test_duplicate_leader_prefers_fresher_when_importance_ties` —— 重要性持平时取更新鲜的；
- `test_duplicate_leader_normalizes_second_level_timestamps` —— 秒级时间戳归一；
- `test_duplicate_leader_maps_unique_memory_to_itself` —— 独条映射到自己（9.4 的前提）；
- `test_quality_prune_never_wipes_whole_duplicate_group` —— 120 份近重复至少留一条（仅 win7）。

---

**文档版本**：v1.3
**最后更新**：2026-11-24
**维护者**：Sage 团队
