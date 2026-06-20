# 多 Agent 协调层计划

## 背景与目标

### 背景
当前 Sage 使用单体 Agent 架构（`backend/agents/`），所有任务由单个 Agent 串行处理。这种架构存在以下问题：
- 无法并行处理多个独立任务
- 缺乏任务分解与依赖管理能力
- 难以支持复杂的多步骤工作流
- 缺乏灵活的通知路由机制

### 目标
借鉴 claw-code 的 **OmX + clawhip + claws** 三方系统，实现多 Agent 协调架构：
1. **规划层（OmX 风格）**：任务分解、依赖分析、执行计划生成
2. **路由层（clawhip 风格）**：事件分发、通知路由（Discord/Webhook/邮件）
3. **执行层（claws）**：可并行的 Agent 实例，独立执行具体任务

## 涉及的文件与模块

### 当前模块
- `backend/agents/` - 当前单体 Agent
  - `backend/agents/agent.py` - Agent 核心逻辑
  - `backend/agents/tools.py` - 工具调用
  - `backend/agents/context.py` - 上下文管理

### 新增模块
- `backend/orchestration/` - 协调层
  - `backend/orchestration/planner.py` - 规划层（OmX 风格）
  - `backend/orchestration/router.py` - 路由层（clawhip 风格）
  - `backend/orchestration/executor.py` - 执行层（claws）
  - `backend/orchestration/models.py` - 数据模型
  - `backend/orchestration/scheduler.py` - 任务调度器

### 修改模块
- `backend/agents/` - 改造为可并行的执行单元
- `backend/main.py` - 集成协调层
- `backend/config.py` - 添加多 Agent 配置

## 技术方案

### 架构设计

```
┌─────────────────────────────────────────┐
│           用户请求入口                   │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│      规划层 (Planner / OmX 风格)         │
│  ├─ 任务分解                             │
│  ├─ 依赖分析                             │
│  ├─ 执行计划生成                         │
│  └─ 资源评估                             │
└────────────┬────────────────────────────┘
             │ 执行计划 (TaskGraph)
             ▼
┌─────────────────────────────────────────┐
│      路由层 (Router / clawhip 风格)      │
│  ├─ 事件分发                             │
│  ├─ 通知路由 (Discord/Webhook/邮件)      │
│  ├─ 优先级管理                           │
│  └─ 负载均衡                             │
└────────────┬────────────────────────────┘
             │ 分配任务
             ▼
┌─────────────────────────────────────────┐
│      执行层 (Executors / claws)          │
│  ├─ Agent 实例 1 (并行)                  │
│  ├─ Agent 实例 2 (并行)                  │
│  ├─ Agent 实例 3 (并行)                  │
│  └─ ... (动态扩展)                       │
└─────────────────────────────────────────┘
```

### 核心数据模型

#### TaskGraph（任务图）
```python
class TaskGraph:
    """任务执行图，表示任务间的依赖关系"""
    tasks: List[Task]
    dependencies: Dict[str, List[str]]  # task_id -> [dependent_task_ids]
    
    def get_ready_tasks(self) -> List[Task]:
        """获取所有依赖已满足的任务"""
        ...
    
    def mark_completed(self, task_id: str):
        """标记任务完成，触发下游任务"""
        ...
```

#### Task（任务）
```python
class Task:
    id: str
    name: str
    description: str
    status: TaskStatus  # PENDING, RUNNING, COMPLETED, FAILED
    priority: int
    executor_type: str  # "agent", "tool", "script"
    parameters: Dict[str, Any]
    result: Optional[Any]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
```

#### Notification（通知）
```python
class Notification:
    id: str
    event_type: str  # "task_completed", "task_failed", "plan_ready"
    target: str  # "discord", "webhook", "email"
    payload: Dict[str, Any]
    sent_at: Optional[datetime]
```

### 接口设计

#### Planner API
```python
class Planner:
    async def create_plan(self, goal: str) -> TaskGraph:
        """根据目标生成执行计划"""
        ...
    
    async def refine_plan(self, plan: TaskGraph, feedback: str) -> TaskGraph:
        """根据反馈优化计划"""
        ...
    
    async def validate_plan(self, plan: TaskGraph) -> PlanValidation:
        """验证计划可行性"""
        ...
```

#### Router API
```python
class Router:
    async def dispatch(self, task: Task) -> str:
        """分发任务到合适的执行器"""
        ...
    
    async def notify(self, notification: Notification):
        """发送通知"""
        ...
    
    async def get_status(self, task_id: str) -> TaskStatus:
        """查询任务状态"""
        ...
```

#### Executor API
```python
class Executor:
    async def execute(self, task: Task) -> TaskResult:
        """执行任务"""
        ...
    
    async def cancel(self, task_id: str):
        """取消任务"""
        ...
    
    async def get_capabilities(self) -> List[str]:
        """返回执行器能力列表"""
        ...
```

### 并发控制

```python
class TaskScheduler:
    def __init__(self, max_concurrent: int = 5):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.task_queue = asyncio.PriorityQueue()
    
    async def schedule(self, task_graph: TaskGraph):
        """调度任务图执行"""
        while not task_graph.is_completed():
            ready_tasks = task_graph.get_ready_tasks()
            for task in ready_tasks:
                await self.task_queue.put((task.priority, task))
            
            # 并行执行就绪任务
            await self._process_queue()
    
    async def _process_queue(self):
        async with self.semaphore:
            _, task = await self.task_queue.get()
            asyncio.create_task(self._execute_task(task))
```

## 实施步骤

### 阶段 1：核心数据模型（1 周）
- [ ] 1.1 定义 Task、TaskGraph、Notification 数据模型
- [ ] 1.2 实现 TaskGraph 依赖分析逻辑
- [ ] 1.3 编写模型单元测试
- [ ] 1.4 设计数据库 schema（持久化任务状态）

### 阶段 2：规划层实现（2 周）
- [ ] 2.1 实现 Planner 核心逻辑（任务分解）
- [ ] 2.2 集成 LLM 进行智能任务分解
- [ ] 2.3 实现计划验证与优化
- [ ] 2.4 编写 Planner 单元测试
- [ ] 2.5 编写 Planner 集成测试

### 阶段 3：路由层实现（1.5 周）
- [ ] 3.1 实现 Router 核心逻辑（任务分发）
- [ ] 3.2 实现通知路由（Discord/Webhook/邮件）
- [ ] 3.3 实现优先级管理与负载均衡
- [ ] 3.4 编写 Router 单元测试
- [ ] 3.5 编写通知集成测试

### 阶段 4：执行层实现（1.5 周）
- [ ] 4.1 改造现有 Agent 为 Executor
- [ ] 4.2 实现 Executor 并发控制
- [ ] 4.3 实现任务取消与重试机制
- [ ] 4.4 编写 Executor 单元测试
- [ ] 4.5 压力测试（多 Agent 并行）

### 阶段 5：集成与测试（1 周）
- [ ] 5.1 集成 Planner + Router + Executor
- [ ] 5.2 实现任务状态持久化
- [ ] 5.3 端到端测试（复杂工作流）
- [ ] 5.4 性能测试与优化
- [ ] 5.5 编写用户文档

## 风险评估与依赖

### 风险
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 任务死锁 | 高 | 实现超时检测与自动恢复 |
| Agent 冲突 | 中 | 资源隔离，避免并发修改同一资源 |
| 任务失败级联 | 高 | 实现失败隔离与重试机制 |
| 性能瓶颈 | 中 | 异步架构，水平扩展执行器 |

### 依赖
- asyncio（Python 异步支持）
- LLM API（用于智能任务分解）
- 消息队列（可选：Celery/Redis）

### 性能指标
| 指标 | 目标值 |
|------|--------|
| 任务分解延迟 | < 2s |
| 并发执行数 | > 10 |
| 任务状态更新延迟 | < 100ms |
| 系统吞吐量 | > 50 tasks/min |

## 验证标准

1. **功能验证**：复杂任务能正确分解并并行执行
2. **可靠性验证**：单个任务失败不影响其他任务
3. **性能验证**：达到并发性能指标
4. **通知验证**：事件通知能正确路由到目标渠道

## 示例工作流

```
用户请求："分析项目代码质量并生成报告"

Planner 分解为：
  Task 1: 扫描代码结构 (无依赖)
  Task 2: 运行静态分析 (依赖 Task 1)
  Task 3: 运行测试覆盖率 (依赖 Task 1)
  Task 4: 生成报告 (依赖 Task 2, 3)

Router 分发：
  Task 1 → Agent A (立即执行)
  Task 2 → Agent B (Task 1 完成后)
  Task 3 → Agent C (Task 1 完成后，与 Task 2 并行)
  Task 4 → Agent D (Task 2, 3 完成后)

通知：
  Task 1 完成 → 发送到 Discord
  全部完成 → 发送邮件报告
```
