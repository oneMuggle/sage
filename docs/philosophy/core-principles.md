# 核心原则详解

> 本文档深入阐述 Sage 的 4 个核心原则，提供具体场景案例与检查清单。

---

## 1. 记忆优先 (Memory First)

### 原则本质

Sage 的核心价值主张是**成为用户的第二大脑**。这意味着：
- 用户的每一次交互都可能成为未来有用的记忆
- 系统默认假设"应该记住"，除非用户明确说"不要记"
- 但记忆不是无脑堆积，而是有结构的、可检索的、可演化的

### 实践指南

#### ✅ 正确做法

**1. 智能过滤**

不是所有信息都值得记住。好的过滤策略：

```python
class MemoryFilter:
    """智能记忆过滤器"""
    
    def should_remember(self, message: str, context: dict) -> bool:
        """判断是否值得记住"""
        # 事实性信息 - 记住
        if self._is_factual(message):
            return True
        
        # 用户偏好 - 记住
        if self._is_preference(message):
            return True
        
        # 重复信息 - 跳过
        if self._is_duplicate(message, context):
            return False
        
        # 临时信息 - 跳过
        if self._is_temporary(message):
            return False
        
        # 默认记住
        return True
    
    def _is_factual(self, message: str) -> bool:
        """检测事实性信息"""
        patterns = [
            r"我叫.*",
            r"我住在.*",
            r"我的.*是.*",
            r"我喜欢.*",
        ]
        return any(re.search(p, message) for p in patterns)
```

**2. 结构化存储**

记忆应该有清晰的分类和标签：

```python
@dataclass
class Memory:
    """结构化的记忆实体"""
    id: str
    content: str
    memory_type: MemoryType  # EPISODIC, SEMANTIC, PROCEDURAL
    tags: List[str]          # 标签便于检索
    importance: float        # 重要度 0-1
    created_at: datetime
    last_accessed: datetime
    access_count: int        # 访问次数（用于衰减）
```

**3. 隐私保护**

用户必须完全控制自己的记忆：

```python
class MemoryPrivacy:
    """记忆隐私控制"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.settings = self._load_privacy_settings()
    
    def can_remember(self, content: str) -> bool:
        """检查是否可以记住该内容"""
        # 敏感信息默认不记住
        if self._contains_sensitive_info(content):
            return self.settings.remember_sensitive
        
        # 默认允许
        return True
    
    def export_all(self) -> dict:
        """导出所有记忆（用户权利）"""
        return {
            "memories": self._get_all_memories(),
            "exported_at": datetime.utcnow().isoformat(),
            "format": "json"
        }
    
    def delete_all(self):
        """删除所有记忆（用户权利）"""
        self._delete_all_memories()
        log.info(f"All memories deleted for user {self.user_id}")
```

#### ❌ 反模式

**1. 无脑记录所有信息**

```python
# ❌ 错误：记住所有对话，导致记忆爆炸
async def process_message(message: str):
    await memory.store(message)  # 包括"嗯"、"好的"等无意义信息
```

**2. 黑盒记忆**

```python
# ❌ 错误：用户不知道什么被记住了
async def process_message(message: str):
    await memory.store(message)
    # 没有日志，没有通知，用户不知情
```

**3. 不可删除**

```python
# ❌ 错误：记忆一旦存储就无法删除
def store_memory(memory: Memory):
    db.insert(memory)
    # 没有 delete 接口
```

### 检查清单

在实现任何记忆相关功能时，确认：

- [ ] 是否有智能过滤（不是所有信息都值得记住）
- [ ] 记忆是否有清晰的结构（类型、标签、重要度）
- [ ] 用户能否查看自己所有的记忆
- [ ] 用户能否删除特定记忆
- [ ] 用户能否导出所有记忆
- [ ] 用户能否关闭记忆功能
- [ ] 敏感信息是否有特殊处理

---

## 2. 渐进式自演化 (Progressive Self-Evolution)

### 原则本质

Sage 应该能从交互中学习，不断优化对用户的理解和响应质量。但这种演化必须是：
- **透明的**：用户知道 Agent 学到了什么
- **可控的**：用户可以批准或拒绝学习
- **可逆的**：用户可以撤销学习结果

### 实践指南

#### ✅ 正确做法

**1. 显式学习请求**

```python
class LearningManager:
    """学习管理器"""
    
    async def propose_learning(self, observation: Observation) -> LearningProposal:
        """提出学习建议，等待用户批准"""
        lesson = await self._extract_lesson(observation)
        
        proposal = LearningProposal(
            lesson=lesson,
            confidence=self._calculate_confidence(observation),
            evidence=[observation],
            status="pending"
        )
        
        # 通知用户
        await self._notify_user(proposal)
        
        return proposal
    
    async def approve_learning(self, proposal_id: str):
        """用户批准学习"""
        proposal = await self._get_proposal(proposal_id)
        proposal.status = "approved"
        await self._store_lesson(proposal.lesson)
        await self._notify_user(f"已学习: {proposal.lesson.summary}")
    
    async def reject_learning(self, proposal_id: str, reason: str):
        """用户拒绝学习"""
        proposal = await self._get_proposal(proposal_id)
        proposal.status = "rejected"
        proposal.rejection_reason = reason
        await self._notify_user(f"已拒绝学习: {proposal.lesson.summary}")
```

**2. 学习日志**

```python
class LearningLog:
    """学习日志（可审计）"""
    
    async def record(self, event: LearningEvent):
        """记录学习事件"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event.type,  # PROPOSED, APPROVED, REJECTED, REVOKED
            "lesson": event.lesson.summary,
            "confidence": event.confidence,
            "user_action": event.user_action,
        }
        await self._store_log(log_entry)
    
    async def get_history(self, user_id: str) -> List[dict]:
        """获取学习历史"""
        return await self._query_logs(user_id)
```

**3. 学习撤销**

```python
class LearningRevocation:
    """学习撤销机制"""
    
    async def revoke_learning(self, lesson_id: str, reason: str):
        """撤销已学习的内容"""
        lesson = await self._get_lesson(lesson_id)
        
        # 标记为已撤销
        lesson.status = "revoked"
        lesson.revoked_at = datetime.utcnow()
        lesson.revocation_reason = reason
        
        await self._update_lesson(lesson)
        
        # 记录撤销事件
        await self._log_revocation(lesson_id, reason)
        
        # 通知用户
        await self._notify_user(f"已撤销学习: {lesson.summary}")
```

#### ❌ 反模式

**1. 静默学习**

```python
# ❌ 错误：静默更新模型，用户不知情
async def update_model(interaction: Interaction):
    await model.update(interaction)
    # 没有通知用户，没有日志
```

**2. 不可逆学习**

```python
# ❌ 错误：学习结果无法撤销
async def learn(lesson: Lesson):
    await model.permanently_update(lesson)
    # 没有撤销机制
```

### 检查清单

在实现任何学习功能时，确认：

- [ ] 学习前是否通知用户
- [ ] 用户是否能批准或拒绝学习
- [ ] 学习结果是否能撤销
- [ ] 是否有完整的学习日志
- [ ] 用户能否查看所有学习历史
- [ ] 用户能否关闭学习功能
- [ ] 学习失败时是否有回滚机制

---

## 3. 透明可控 (Transparent & Controllable)

### 原则本质

Sage 的所有自动化行为都必须建立在用户信任之上。这意味着：
- **可审计**：每一步都有日志
- **可解释**：能说明为什么这样做
- **可回滚**：能撤销已执行的操作

### 实践指南

#### ✅ 正确做法

**1. 完整的审计日志**

```python
class AuditLog:
    """审计日志"""
    
    async def log_action(self, action: Action, context: dict):
        """记录操作"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action.name,
            "actor": context.get("actor", "system"),
            "parameters": action.parameters,
            "reason": context.get("reason"),
            "result": None,  # 稍后更新
        }
        
        log_id = await self._store_log(log_entry)
        return log_id
    
    async def update_result(self, log_id: str, result: dict):
        """更新操作结果"""
        await self._update_log(log_id, {"result": result})
    
    async def get_logs(self, user_id: str, filters: dict) -> List[dict]:
        """查询日志"""
        return await self._query_logs(user_id, filters)
```

**2. 可解释的决策**

```python
class ExplainableDecision:
    """可解释的决策"""
    
    def __init__(self, decision: str, reasons: List[str]):
        self.decision = decision
        self.reasons = reasons
    
    def explain(self) -> str:
        """生成解释"""
        explanation = f"决策: {self.decision}\n\n原因:\n"
        for i, reason in enumerate(self.reasons, 1):
            explanation += f"{i}. {reason}\n"
        return explanation

# 使用示例
decision = ExplainableDecision(
    decision="推荐用户阅读《Python 高级编程》",
    reasons=[
        "用户最近在学习 Python 高级特性",
        "用户的技能水平适合这本书",
        "这本书评价很高（4.8/5）",
    ]
)
print(decision.explain())
```

**3. 操作回滚**

```python
class RollbackManager:
    """操作回滚管理器"""
    
    async def execute_with_rollback(self, operation: Callable) -> RollbackToken:
        """执行操作并记录回滚信息"""
        # 记录操作前的状态
        before_state = await self._capture_state()
        
        try:
            # 执行操作
            result = await operation()
            
            # 记录回滚信息
            token = RollbackToken(
                operation_id=str(uuid.uuid4()),
                before_state=before_state,
                executed_at=datetime.utcnow()
            )
            await self._store_rollback_info(token)
            
            return token
        except Exception as e:
            # 自动回滚
            await self._rollback(before_state)
            raise
    
    async def rollback(self, token: RollbackToken):
        """手动回滚"""
        await self._rollback(token.before_state)
        log.info(f"Rolled back operation {token.operation_id}")
```

#### ❌ 反模式

**1. 黑盒自动化**

```python
# ❌ 错误：自动执行操作，没有日志
async def auto_optimize():
    await optimize_memory()
    await cleanup_unused()
    await update_indexes()
    # 用户不知道发生了什么
```

**2. 不可逆操作**

```python
# ❌ 错误：永久删除，无法恢复
def delete_data(id: str):
    db.execute(f"DELETE FROM table WHERE id = {id}")
    # 没有备份，没有回滚
```

### 检查清单

在实现任何自动化功能时，确认：

- [ ] 是否有完整的审计日志
- [ ] 是否能解释为什么这样做
- [ ] 是否能回滚已执行的操作
- [ ] 用户能否查看操作历史
- [ ] 操作失败时是否有自动回滚
- [ ] 用户能否禁用自动化功能

---

## 4. 简单胜于复杂 (Simple Over Complex)

### 原则本质

优先选择简单方案，除非复杂性能证明其价值。这意味着：
- **易于理解**：新开发者能快速上手
- **易于测试**：每个模块可独立测试
- **易于演进**：修改一处不影响全局

### 实践指南

#### ✅ 正确做法

**1. 简单直接的实现**

```python
# ✅ 好的设计：简单的余弦相似度
def calculate_similarity(query: str, memory: str) -> float:
    """计算两段文本的相似度（余弦相似度）"""
    vec1 = embed(query)
    vec2 = embed(memory)
    return cosine_similarity(vec1, vec2)
```

**2. 渐进式复杂度**

```python
# ✅ 好的设计：从简单开始，按需升级
class SimilarityCalculator:
    """相似度计算器（渐进式复杂度）"""
    
    def __init__(self, method: str = "cosine"):
        self.method = method
    
    def calculate(self, text1: str, text2: str) -> float:
        """计算相似度"""
        if self.method == "cosine":
            return self._cosine_similarity(text1, text2)
        elif self.method == "semantic":
            # 仅在用户明确需要时使用
            return self._semantic_similarity(text1, text2)
        else:
            raise ValueError(f"Unknown method: {self.method}")
```

**3. 清晰的模块边界**

```python
# ✅ 好的设计：清晰的模块职责
# memory/storage.py - 只负责存储
class MemoryStorage:
    def save(self, memory: Memory): ...
    def load(self, id: str) -> Memory: ...
    def delete(self, id: str): ...

# memory/retrieval.py - 只负责检索
class MemoryRetriever:
    def search(self, query: str, top_k: int) -> List[Memory]: ...
    def rank(self, memories: List[Memory]) -> List[Memory]: ...

# memory/evolution.py - 只负责演化
class MemoryEvolution:
    def consolidate(self, memories: List[Memory]) -> Memory: ...
    def prune(self, memories: List[Memory]) -> List[Memory]: ...
```

#### ❌ 反模式

**1. 过度设计**

```python
# ❌ 错误：过度抽象
class SimilarityStrategy(Protocol):
    def calculate(self, text1: str, text2: str) -> float: ...

class CosineSimilarityStrategy(SimilarityStrategy): ...
class EuclideanSimilarityStrategy(SimilarityStrategy): ...
class ManhattanSimilarityStrategy(SimilarityStrategy): ...
class SemanticSimilarityStrategy(SimilarityStrategy): ...
# ... 10 种策略，但只用 1 种

class SimilarityCalculatorFactory:
    def create(self, strategy: str) -> SimilarityStrategy: ...
# 过度设计，增加复杂度
```

**2. 魔法行为**

```python
# ❌ 错误：隐式依赖，黑盒逻辑
def process(data):
    result = magic_function(data)  # 不知道 magic_function 做了什么
    return result
```

### 检查清单

在设计任何功能时，确认：

- [ ] 是否有更简单的实现方式
- [ ] 新开发者能否在 30 分钟内理解代码
- [ ] 每个模块是否有清晰的单一职责
- [ ] 是否有不必要的抽象层
- [ ] 是否能用 100 行代码完成（而不是 1000 行）

---

## 总结

Sage 的 4 个核心原则是相辅相成的：

1. **记忆优先** - 定义了我们做什么（记住用户信息）
2. **渐进式自演化** - 定义了我们如何学习（透明、可控、可逆）
3. **透明可控** - 定义了我们如何工作（可审计、可解释、可回滚）
4. **简单胜于复杂** - 定义了我们如何构建（简单、清晰、易维护）

遵循这些原则，我们才能构建一个**有记忆、有温度、可信赖**的 AI 助手。
