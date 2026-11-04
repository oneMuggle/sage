# 记忆质量优化方案

> 日期：2026-11-04  
> 分支：fix/memory-quality-improvements  
> 状态：进行中

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
# 扩展偏好维度
PREFERENCE_DIMENSIONS = {
    # 原有维度
    "response_length": {"label": "回复长度", "values": ["简短", "适中", "详细"]},
    "tone": {"label": "交互风格", "values": ["友好", "专业", "幽默", "严肃"]},
    "detail_level": {"label": "详细程度", "values": ["简洁", "适中", "全面"]},
    
    # 新增维度
    "code_style": {"label": "代码风格", "values": ["函数式", "面向对象", "混合"]},
    "comment_preference": {"label": "注释偏好", "values": ["无注释", "关键注释", "详细注释"]},
    "explanation_depth": {"label": "解释深度", "values": ["直接给答案", "简要说明", "详细推导"]},
}
```

**优化 2：允许自由文本偏好**
```python
async def _extract_preferences_with_llm(self, messages):
    prompt = """
    分析用户的反馈，提取偏好。输出 JSON：
    {
      "structured": {
        "response_length": "详细",
        "tone": "专业"
      },
      "free_text": [
        {"category": "代码风格", "preference": "偏好函数式编程，避免 class"},
        {"category": "注释", "preference": "关键函数需要 docstring"}
      ]
    }
    """
    
    # 处理自由文本偏好
    for pref in result.get("free_text", []):
        profile_store.add(
            content=f"用户偏好{pref['category']}: {pref['preference']}",
            category="preference",
            importance=6,
            metadata={
                "source_session": session_id,
                "learned_at": now_ts,
            }
        )
```

**优化 3：存储来源上下文**
```python
# 修改写入逻辑，增加元数据
profile_store.add(
    content=f"用户偏好{label}: {value}",
    category="preference",
    importance=6,
    metadata={
        "source_session": session_id,
        "source_turn": turn_id,
        "learned_at": now_ts,
        "confidence": confidence,
    }
)
```

#### 2.2.3 改进去重机制（引入向量相似度）

**文件**：`backend/memory/conflict.py` - `MemoryConflictResolver`

**优化：混合相似度（字面 + 语义）**
```python
def _calculate_similarity(self, content1: str, content2: str) -> float:
    """混合相似度：字面 + 语义"""
    
    # 1. 字面相似度（原有）
    literal_sim = SequenceMatcher(None, content1, content2).ratio()
    
    # 2. 语义相似度（新增）
    try:
        emb1 = self.embedder.embed(content1)
        emb2 = self.embedder.embed(content2)
        semantic_sim = cosine_similarity(emb1, emb2)
    except Exception:
        semantic_sim = 0.0
    
    # 3. 加权组合（中文场景语义权重更高）
    return 0.3 * literal_sim + 0.7 * semantic_sim

# 调整阈值
NOOP_THRESHOLD = 0.88  # 从 0.97 降低（语义相似度高）
UPDATE_THRESHOLD = 0.75  # 从 0.78 降低
```

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
- [ ] **Task 2.1**：改进记忆提取策略（提高门槛 + 重要性过滤）
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
- [ ] **Task 2.3**：增强偏好学习（扩展维度 + 自由文本）
- [ ] **Task 2.4**：改进去重机制（引入向量相似度）
- [ ] **Task 2.5**：编写集成测试验证效果

### Phase 3：增强记忆整合（2 周）
- [ ] **Task 3.1**：强化 MemoryReflectionTask（增加分组大小 + 内容长度）
- [ ] **Task 3.2**：引入记忆巩固机制（主题簇 + 摘要生成）
- [ ] **Task 3.3**：增加记忆质量评分器
- [ ] **Task 3.4**：集成到 MemoryPruningTask
- [ ] **Task 3.5**：编写端到端测试验证效果

### Phase 4：优化用户体验（1 周）
- [ ] **Task 4.1**：在记忆库页面显示"如何使用"提示
- [ ] **Task 4.2**：增加记忆来源追踪（哪次对话产生的）
- [ ] **Task 4.3**：支持用户批量删除低质量记忆
- [ ] **Task 4.4**：增加记忆质量可视化
- [ ] **Task 4.5**：用户测试和反馈收集

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
- `backend/scheduler/evolution.py` — 进化任务
- `backend/memory/user_profile.py` — 画像存储
- `src/widgets/evolution/EvolutionPanel.tsx` — 进化日志显示
- `src/widgets/memory/MemoryBrowser.tsx` — 记忆浏览器

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

**去重测试**：
```python
def test_semantic_deduplication():
    """测试语义去重"""
    memory1 = "用户喜欢简洁回答"
    memory2 = "用户偏好简短回复"
    
    similarity = resolver._calculate_similarity(memory1, memory2)
    
    assert similarity >= 0.88  # NOOP_THRESHOLD
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

**文档版本**：v1.0  
**最后更新**：2026-11-04  
**维护者**：Sage 团队
