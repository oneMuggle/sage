# 记忆系统集成到 ChatService (方案 A)

**日期**: 2026-06-19  
**目标**: 将记忆功能集成到六边形架构的 ChatService,替代 Legacy Agent  
**预计时间**: 3 周 (15 个工作日)

---

## 背景

### 当前问题
- ❌ Legacy Agent (`backend/core/legacy/agent.py`) 有完整的记忆功能
- ❌ ChatService (`backend/application/services/chat_service.py`) 没有记忆功能
- ❌ 生产环境实际使用 Legacy Agent (API_MODE=legacy)
- ❌ 六边形架构的核心服务缺少记忆,违背"记忆型 AI 助手"定位

### 目标状态
- ✅ ChatService 集成完整的记忆功能
- ✅ 生产环境切换到 API_MODE=hex
- ✅ Legacy Agent 标记为 deprecated
- ✅ 测试覆盖率 ≥ 80%

---

## 实施步骤

### Phase 1: MemoryPort 协议定义 (Week 1, Day 1-2)

#### 1.1 定义 MemoryContext 数据类

**文件**: `backend/domain/memory.py` (新建)

```python
"""Memory Domain Models"""
from dataclasses import dataclass
from typing import Any


@dataclass
class MemoryContext:
    """记忆上下文 - 用于注入到 LLM prompt"""
    working: list[dict[str, Any]]
    episodic: list[dict[str, Any]]
    semantic: list[dict[str, Any]]
    
    @property
    def has_memories(self) -> bool:
        """是否有记忆"""
        return bool(self.working or self.episodic or self.semantic)
    
    def format(self) -> str:
        """格式化为可注入 prompt 的字符串"""
        parts = []
        
        if self.working:
            parts.append("【当前对话】")
            for msg in self.working[-3:]:
                content = msg.get("content", "")[:100]
                role = msg.get("role", "unknown")
                parts.append(f"- [{role}]: {content}")
        
        if self.episodic:
            parts.append("\n【相关经历】")
            for mem in self.episodic[:3]:
                summary = mem.get("summary", mem.get("content", ""))[:100]
                parts.append(f"- {summary}")
        
        if self.semantic:
            parts.append("\n【相关知识】")
            for mem in self.semantic[:3]:
                summary = mem.get("summary", mem.get("content", ""))[:100]
                parts.append(f"- {summary}")
        
        return "\n".join(parts) if parts else ""
```

**验收标准**:
- [ ] MemoryContext 可以正确存储三层记忆
- [ ] format() 方法生成可读的上下文字符串
- [ ] 单元测试覆盖率 100%

#### 1.2 定义 MemoryPort 协议

**文件**: `backend/ports/memory.py` (新建)

```python
"""Memory Port Protocol"""
from typing import Protocol
from backend.domain.memory import MemoryContext


class MemoryPort(Protocol):
    """记忆端口协议 - 六边形架构的记忆接口"""
    
    async def retrieve(
        self,
        query: str,
        session_id: str,
        limit: int = 5
    ) -> MemoryContext:
        """检索相关记忆
        
        Args:
            query: 查询文本
            session_id: 会话 ID
            limit: 每种记忆类型的返回数量
            
        Returns:
            MemoryContext 包含三层记忆
        """
        ...
    
    async def store(
        self,
        content: str,
        session_id: str,
        importance: int = 5,
        tags: list[str] | None = None
    ) -> str:
        """存储记忆
        
        Args:
            content: 记忆内容
            session_id: 会话 ID
            importance: 重要性 1-10
            tags: 标签列表
            
        Returns:
            memory_id: 生成的记忆 ID
        """
        ...
    
    async def compress(
        self,
        session_id: str
    ) -> None:
        """压缩工作记忆
        
        Args:
            session_id: 会话 ID
        """
        ...
```

**验收标准**:
- [ ] MemoryPort 定义清晰,符合 Protocol 规范
- [ ] 方法签名与 Legacy Agent 的记忆功能对齐
- [ ] 有完整的 docstring

---

### Phase 2: MemoryAdapter 实现 (Week 1, Day 2-3)

#### 2.1 实现 MemoryAdapter

**文件**: `backend/adapters/out/memory/adapter.py` (新建)

```python
"""Memory Adapter - 记忆端口适配器"""
import logging
from backend.ports.memory import MemoryPort
from backend.domain.memory import MemoryContext
from backend.memory import MemoryManager, ConsolidationPipeline

logger = logging.getLogger(__name__)


class MemoryAdapter:
    """记忆端口适配器 - 将 MemoryPort 适配到现有的 MemoryManager"""
    
    def __init__(self, memory_manager: MemoryManager):
        self.memory_manager = memory_manager
        self.consolidation = ConsolidationPipeline()
    
    async def retrieve(
        self,
        query: str,
        session_id: str,
        limit: int = 5
    ) -> MemoryContext:
        """检索相关记忆"""
        logger.debug(f"Retrieving memories for query: {query[:50]}...")
        
        results = self.memory_manager.recall(query, limit=limit)
        
        return MemoryContext(
            working=results.get("working", []),
            episodic=results.get("episodic", []),
            semantic=results.get("semantic", [])
        )
    
    async def store(
        self,
        content: str,
        session_id: str,
        importance: int = 5,
        tags: list[str] | None = None
    ) -> str:
        """存储记忆"""
        logger.debug(f"Storing memory: {content[:50]}...")
        
        memory_id = self.memory_manager.memorize(
            content=content,
            importance=importance,
            metadata={"session_id": session_id, "tags": tags or []}
        )
        
        return memory_id or ""
    
    async def compress(self, session_id: str) -> None:
        """压缩工作记忆"""
        if self.memory_manager.working.total_tokens > 3000:
            logger.info(f"Compressing working memory for session: {session_id}")
            self.consolidation.consolidate(
                self.memory_manager,
                session_id=session_id
            )
```

**验收标准**:
- [ ] MemoryAdapter 正确实现 MemoryPort 协议
- [ ] retrieve() 调用 MemoryManager.recall()
- [ ] store() 调用 MemoryManager.memorize()
- [ ] compress() 在 Token 超阈值时调用 ConsolidationPipeline
- [ ] 单元测试覆盖率 ≥ 90%

#### 2.2 编写单元测试

**文件**: `backend/tests/unit/test_memory_adapter.py` (新建)

测试用例:
- [ ] test_retrieve_returns_memory_context
- [ ] test_store_calls_memory_manager
- [ ] test_compress_when_tokens_exceed_threshold
- [ ] test_compress_skips_when_tokens_low

---

### Phase 3: ChatService 集成记忆 (Week 1, Day 3-5)

#### 3.1 修改 ChatService 构造函数

**文件**: `backend/application/services/chat_service.py`

```python
# 在 __init__ 中添加 memory 参数
def __init__(
    self,
    llm: LLMPort,
    tools: ToolPort,
    skills: SkillPort,
    storage: StoragePort,
    metrics: MetricPort,
    events: EventPort,
    memory: MemoryPort,  # ✅ 新增
):
    self.llm = llm
    self.tools = tools
    self.skills = skills
    self.storage = storage
    self.metrics = metrics
    self.events = events
    self.memory = memory  # ✅ 保存
```

#### 3.2 修改 _run_turn_inner 方法

在 `_run_turn_inner` 中添加记忆检索和注入:

```python
async def _run_turn_inner(self, session_id, user_message, span):
    # 1) 持久化 user message
    await self.storage.append_message(session_id, user_message)
    self.events.emit("chat_message_sent", {"session_id": session_id, "role": "user"})
    
    # ✅ 2) 检索相关记忆
    memory_context = await self.memory.retrieve(
        query=user_message.content,
        session_id=session_id,
        limit=5
    )
    span.set_attribute("memory.has_memories", memory_context.has_memories)
    
    # 3) 拉取历史上下文
    history = await self.storage.get_messages(session_id, limit=20)
    span.set_attribute("history.size", len(history))
    
    # ✅ 4) 构建 system prompt (注入记忆)
    system_content = "你是 Sage,一个智能 AI 助手。"
    
    # 添加图表工具提示
    try:
        from backend.core.diagram_prompt import DIAGRAM_TOOL_PROMPT
        if self.tools and any("drawio" in t.name for t in self.tools.list()):
            system_content += DIAGRAM_TOOL_PROMPT
    except Exception:
        pass
    
    # ✅ 注入记忆上下文
    if memory_context.has_memories:
        system_content += "\n\n以下是相关的记忆上下文:\n"
        system_content += memory_context.format()
    
    system_msg = Message(role=Role.SYSTEM, content=system_content)
    history = [system_msg] + list(history)
    
    # 5) 调 LLM
    response = await self.llm.chat(history, tools=llm_tools)
    
    # 6) 执行 tool_calls
    if response.tool_calls:
        await self._execute_tool_calls(session_id, response.tool_calls)
    
    # 7) 持久化 assistant response
    await self.storage.append_message(session_id, response)
    self.events.emit("chat_response_completed", {"session_id": session_id})
    
    # ✅ 8) 提取并存储记忆
    await self._extract_and_store_memory(
        session_id=session_id,
        user_message=user_message,
        assistant_message=response
    )
    
    # ✅ 9) 压缩工作记忆
    await self.memory.compress(session_id)
    
    return [user_message, response]
```

#### 3.3 添加 _extract_and_store_memory 方法

```python
async def _extract_and_store_memory(
    self,
    session_id: str,
    user_message: Message,
    assistant_message: Message
):
    """从对话中提取关键信息并存入记忆"""
    user_content = user_message.content
    assistant_content = assistant_message.content
    
    # 对于较长的对话,保存到记忆
    if len(user_content) > 100 or len(assistant_content) > 100:
        combined_content = f"[用户]: {user_content}\n[助手]: {assistant_content}"
        importance = 5
        
        # 检测是否包含偏好或设置信息
        preference_keywords = ["喜欢", "偏好", "不要", "记得", "设置", "以后"]
        for keyword in preference_keywords:
            if keyword in user_content:
                importance = 7
                break
        
        await self.memory.store(
            content=combined_content,
            session_id=session_id,
            importance=importance,
            tags=["conversation"]
        )
```

**验收标准**:
- [ ] ChatService 构造函数接受 memory 参数
- [ ] 每次对话前检索记忆
- [ ] 记忆正确注入到 system prompt
- [ ] 对话后自动提取和存储记忆
- [ ] Token 超阈值时自动压缩
- [ ] 单元测试覆盖率 ≥ 90%

#### 3.4 编写单元测试

**文件**: `backend/tests/unit/test_chat_service_memory.py` (新建)

测试用例:
- [ ] test_chat_service_retrieves_memory_before_chat
- [ ] test_chat_service_injects_memory_to_system_prompt
- [ ] test_chat_service_stores_memory_after_chat
- [ ] test_chat_service_compresses_when_tokens_high
- [ ] test_memory_context_formatting

---

### Phase 4: 装配 MemoryAdapter (Week 2, Day 1)

#### 4.1 修改 main.py

**文件**: `backend/main.py`

```python
def _build_chat_service() -> ChatService:
    """装配 ChatService,添加 MemoryAdapter"""
    # ... 现有装配
    
    # ✅ 添加记忆管理器
    from backend.memory import MemoryManager, WorkingMemory, EpisodicMemory, SemanticMemory
    from backend.data.database import Database
    
    db = Database(db_path="data/sage.db")
    memory_manager = MemoryManager(
        working=WorkingMemory(max_size=20, max_tokens=4000),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db)
    )
    
    from backend.adapters.out.memory.adapter import MemoryAdapter
    memory_adapter = MemoryAdapter(memory_manager)
    
    return ChatService(
        llm=HttpxLLMAdapter(),
        tools=tools,
        skills=None,  # P3 实现
        storage=SqliteStorageAdapter(),
        metrics=PrometheusMetricAdapter(),
        events=FileEventAdapter(),
        memory=memory_adapter,  # ✅ 注入
    )
```

**验收标准**:
- [ ] MemoryAdapter 正确装配
- [ ] ChatService 可以正常启动
- [ ] 冒烟测试通过

---

### Phase 5: 集成测试 (Week 2, Day 2-3)

#### 5.1 编写集成测试

**文件**: `backend/tests/integration/test_chat_service_memory_integration.py` (新建)

测试场景:
- [ ] test_full_conversation_with_memory
  - 创建会话
  - 发送消息
  - 验证记忆被检索和注入
  - 验证记忆被存储
- [ ] test_memory_persistence_across_sessions
  - 会话 A 存储记忆
  - 会话 B 检索记忆
  - 验证记忆跨会话持久化
- [ ] test_memory_compression
  - 发送大量消息
  - 验证工作记忆被压缩

#### 5.2 运行集成测试

```bash
cd backend
pytest tests/integration/test_chat_service_memory_integration.py -v
```

**验收标准**:
- [ ] 所有集成测试通过
- [ ] 测试覆盖率 ≥ 80%

---

### Phase 6: 灰度发布 (Week 2, Day 4-5)

#### 6.1 准备灰度环境

- [ ] 更新配置文件,支持 API_MODE 动态切换
- [ ] 添加监控指标 (记忆检索次数、存储次数、压缩次数)
- [ ] 准备回滚脚本

#### 6.2 灰度 10% 流量

```bash
# 10% 流量走 hex
export API_MODE=hex
# 90% 流量走 legacy (通过负载均衡)
```

- [ ] 监控错误率
- [ ] 监控性能指标
- [ ] 收集用户反馈

#### 6.3 灰度 50% 流量

如果 10% 灰度成功,提升到 50%:

```bash
export API_MODE=hex  # 50%
```

- [ ] 无 P0/P1 级别 bug
- [ ] 性能指标正常
- [ ] 用户反馈积极

#### 6.4 全量切换

```bash
# 修改 backend/main.py 第 210 行
_API_MODE = os.environ.get("API_MODE", "hex").lower()  # 改回 hex
```

**验收标准**:
- [ ] 100% 流量走 hex
- [ ] 无重大 bug
- [ ] 性能指标正常

---

### Phase 7: 废弃 Legacy Agent (Week 3, Day 1-2)

#### 7.1 标记为 deprecated

**文件**: `backend/core/legacy/agent.py`

```python
import warnings

class SageAgent:
    def __init__(self, ...):
        warnings.warn(
            "SageAgent is deprecated. Use ChatService instead.",
            DeprecationWarning,
            stacklevel=2
        )
        # ...
```

#### 7.2 更新文档

**文件**: `docs/technical/18-hexagonal.md`

添加迁移完成说明:

```markdown
## 迁移完成 (2026-06-XX)

- ✅ Legacy Agent 已废弃
- ✅ 所有流量走 ChatService
- ✅ core/legacy/ 将在 v0.3.0 删除
- ✅ 记忆功能已集成到 ChatService
```

#### 7.3 清理代码 (可选)

如果时间允许,可以删除 `backend/core/legacy/` 目录。否则保留作为参考。

**验收标准**:
- [ ] Legacy Agent 标记为 deprecated
- [ ] 文档更新完成
- [ ] 团队通知到位

---

## 风险管理

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 记忆检索性能问题 | 中 | 中 | 添加缓存,限制检索数量 |
| 记忆存储失败 | 低 | 高 | 完善的错误处理,不阻塞主流程 |
| 灰度期间发现问题 | 中 | 高 | 快速回滚到 legacy |
| 测试覆盖不足 | 低 | 中 | 强制 80% 覆盖率门禁 |
| 用户反馈负面 | 低 | 高 | 收集反馈,快速迭代 |

---

## 关键成功因素

1. ✅ **MemoryPort 设计合理**: 协议清晰,易于测试
2. ✅ **灰度发布策略**: 10% → 50% → 100%
3. ✅ **监控完善**: 性能指标、错误率、用户反馈
4. ✅ **快速回滚**: 发现问题立即切回 legacy

---

## 里程碑

| 日期 | 里程碑 | 交付物 |
|------|--------|--------|
| Week 1 Day 5 | MemoryPort + Adapter 完成 | ✅ 协议定义 ✅ Adapter 实现 ✅ 单元测试 |
| Week 2 Day 3 | ChatService 集成完成 | ✅ 记忆检索 ✅ 记忆注入 ✅ 记忆存储 ✅ 集成测试 |
| Week 2 Day 5 | 灰度发布成功 | ✅ 10% 流量 ✅ 监控正常 ✅ 无重大 bug |
| Week 3 Day 2 | 全量切换完成 | ✅ API_MODE=hex ✅ Legacy deprecated ✅ 文档更新 |

---

## 验收标准汇总

### 功能验收
- [ ] ChatService 可以检索记忆
- [ ] 记忆正确注入到 system prompt
- [ ] 对话后自动存储记忆
- [ ] Token 超阈值时自动压缩
- [ ] 记忆跨会话持久化

### 测试验收
- [ ] 单元测试覆盖率 ≥ 80%
- [ ] 集成测试通过
- [ ] 冒烟测试通过

### 性能验收
- [ ] 记忆检索延迟 < 100ms
- [ ] 无性能退化
- [ ] 内存占用正常

### 文档验收
- [ ] 技术文档更新
- [ ] API 文档更新
- [ ] 迁移指南完成

---

## 附录

### 相关文件清单

**新建文件**:
- `backend/domain/memory.py`
- `backend/ports/memory.py`
- `backend/adapters/out/memory/adapter.py`
- `backend/tests/unit/test_memory_adapter.py`
- `backend/tests/unit/test_chat_service_memory.py`
- `backend/tests/integration/test_chat_service_memory_integration.py`

**修改文件**:
- `backend/application/services/chat_service.py`
- `backend/main.py`
- `docs/technical/18-hexagonal.md`

### 参考实现

- Legacy Agent 记忆实现: `backend/core/legacy/agent.py` 第 260-390 行
- MemoryManager: `backend/memory/manager.py`
- ConsolidationPipeline: `backend/memory/consolidation.py`

---

**计划创建时间**: 2026-06-19  
**最后更新**: 2026-06-19
