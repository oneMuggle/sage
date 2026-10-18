# 闲时自主目标执行系统设计方案

> 日期：2026-10-17
> 状态：设计中
> 分支：feat/autonomous-goals

## 1. 背景与目标

### 1.1 问题

许多 API 提供商采用峰谷定价策略，夜间闲时价格更低。用户希望在无人值守时（如夜间）自动执行复杂任务，但现有系统缺乏：

- 时间窗口感知（不知道何时是闲时）
- 自主多轮执行能力（无法自动迭代）
- 目标完成度审查（无法判断目标是否达成）
- 智能降级机制（失败时无法自动调整策略）

### 1.2 解决方案

构建一个**通用目标驱动的多轮自主执行系统**：

1. 用户定义目标（如"重构认证模块，测试覆盖率提升到 80%"）
2. 系统在闲时自动启动执行
3. LLM 将目标分解为可验证的检查点
4. 系统自动执行任务、验证检查点
5. LLM 审查完成度，决定是否继续
6. 失败时智能降级（换模型、简化任务）
7. 目标达成或预算耗尽时停止，生成执行报告

### 1.3 设计原则

- **最大化复用**：90% 代码复用现有编排系统（Planner/ChatDispatcher/LaneExecutor）
- **架构清晰**：只新增"目标管理层"，不重建执行引擎
- **成本可控**：三重预算控制（轮数、时间、token）
- **用户友好**：实时看板 + 关键通知 + 执行报告

## 2. 核心设计决策

### 2.1 目标类型：通用目标循环（D）

不限定目标类型，支持任意用户目标，系统自动分解、执行、审查、迭代。

**理由：** 灵活性最高，适用于各种场景（代码重构、文档整理、数据分析等）。

### 2.2 审查机制：混合模式（C）

- LLM 生成可验证的检查点
- 系统自动验证检查点（执行命令、检查文件）
- LLM 在关键节点做最终判断

**理由：** 兼顾灵活性和客观性，成本可控。

### 2.3 时间感知：混合模式（D）

- 基础：用户配置闲时时段（如 22:00-06:00）
- 进阶：如果 API 提供商支持动态定价，系统自动适配

**理由：** 简单场景开箱即用，复杂场景可深度定制。

### 2.4 终止条件：组合策略（D）

三重保护，任一满足即停止：
- 目标达成
- 达到最大轮数（用户配置）
- 超过时间预算（用户配置）

**理由：** 全面保护，防止无限循环和成本失控。

### 2.5 错误处理：智能降级（C）

失败后自动尝试替代方案：
1. 第一次失败 → 换模型（Opus → Sonnet → Haiku）
2. 第二次失败 → 简化任务（分解为更小步骤）
3. 第三次失败 → 停止并生成详细报告

**理由：** 平衡自动化和可靠性。

### 2.6 UI/通知：混合模式（E）

- 实时看板（复用 Task Center）
- 关键事件通知（目标完成/严重失败/达到预算）
- 执行摘要报告（每轮生成）

**理由：** 夜间无人值守场景需要完整的监控和通知机制。

## 3. 架构设计

### 3.1 组件层次图

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Zustand)                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ GoalListPage │  │ GoalDetail   │  │  TaskCenter      │  │
│  │ (CRUD)       │  │ (监控/报告)   │  │  (复用现有)       │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            ↕ API
┌─────────────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │            GoalService (新建 - 目标管理层)             │  │
│  │  • 目标生命周期管理                                    │  │
│  │  • 时间窗口判断（闲时/峰时）                            │  │
│  │  • 多轮迭代控制                                        │  │
│  │  • 完成度审查（LLM + 检查点）                          │  │
│  │  • 智能降级决策                                        │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↕                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         CheckpointManager (新建 - 检查点管理)          │  │
│  │  • 生成可验证检查点（调用 LLM）                        │  │
│  │  • 自动验证检查点（执行命令/检查文件）                  │  │
│  │  • 进度追踪                                            │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↕                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              复用现有编排系统                           │  │
│  │  ┌────────────┐  ┌────────────┐  ┌──────────────┐   │  │
│  │  │ Planner    │  │ ChatDisp.  │  │ LaneExecutor │   │  │
│  │  │ (目标分解)  │  │ (任务调度)  │  │ (生命周期)   │   │  │
│  │  └────────────┘  └────────────┘  └──────────────┘   │  │
│  │  ┌────────────┐  ┌────────────┐  ┌──────────────┐   │  │
│  │  │ Subagent   │  │ Scheduler  │  │ TaskCenter   │   │  │
│  │  │ Runner     │  │ Service    │  │ Store        │   │  │
│  │  │ (代理执行)  │  │ (时间触发)  │  │ (状态监控)   │   │  │
│  │  └────────────┘  └────────────┘  └──────────────┘   │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心职责分离

| 组件 | 职责 | 新建/复用 |
|------|------|----------|
| **GoalService** | 目标生命周期、迭代控制、完成度审查、降级决策 | 新建 |
| **CheckpointManager** | 检查点生成（LLM）、验证（自动化）、进度追踪 | 新建 |
| **TimeWindowManager** | 闲时判断、定价规则应用 | 新建 |
| **Planner** | 将目标分解为任务 DAG | 复用 |
| **ChatDispatcher** | 调度子代理执行任务 | 复用 |
| **SubagentRunner** | 实际执行代理任务 | 复用 |
| **LaneExecutor** | 管理 Lane 生命周期、重试、取消 | 复用 |
| **SchedulerService** | 定时触发 Goal 执行 | 扩展 |
| **TaskCenter** | 实时进度监控 | 复用 |

### 3.3 数据流

```
用户创建目标（带时间窗口配置）
    ↓
SchedulerService 在闲时触发
    ↓
GoalService.start_execution(goal_id)
    ↓
┌─────────────────────────────────────────┐
│ 执行循环（多轮）                          │
│                                         │
│  while not terminated:                  │
│    1. CheckpointManager 生成/获取检查点  │
│    2. Planner 分解当前轮次任务           │
│    3. ChatDispatcher 执行任务            │
│    4. CheckpointManager 验证检查点       │
│    5. GoalService 审查完成度             │
│    6. 决策：继续/停止/降级               │
└─────────────────────────────────────────┘
    ↓
生成执行报告 + 通知用户
```

## 4. 核心组件设计

### 4.1 数据模型

```python
from enum import Enum
from datetime import datetime
from pydantic import BaseModel

class GoalStatus(str, Enum):
    """目标状态"""
    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 执行中
    PAUSED = "paused"            # 暂停
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消

class PricingTier(str, Enum):
    """定价等级"""
    PEAK = "peak"                # 高峰 1.0x
    STANDARD = "standard"        # 平峰 0.7x
    OFF_PEAK = "off_peak"        # 闲时 0.5x
    DYNAMIC = "dynamic"          # 动态定价

class CheckpointType(str, Enum):
    """检查点类型"""
    FILE = "file"                # 文件检查
    COMMAND = "command"          # 命令执行
    CODE = "code"                # 代码质量
    CUSTOM = "custom"            # 自定义

class DegradationLevel(str, Enum):
    """降级等级"""
    NONE = "none"
    MODEL_DOWNGRADE = "model_downgrade"
    TASK_SIMPLIFY = "task_simplify"
    STOPPED = "stopped"

class TimeWindow(BaseModel):
    """时间窗口配置"""
    off_peak_start: str          # "22:00"
    off_peak_end: str            # "06:00"
    weekends_off_peak: bool = True
    holidays: list[str] = []
    min_pricing_tier: PricingTier = PricingTier.OFF_PEAK

class ExecutionBudget(BaseModel):
    """执行预算"""
    max_rounds: int = 10
    max_hours: float = 8.0
    max_tokens: int = 1_000_000
    stop_on_failure: bool = False

class Checkpoint(BaseModel):
    """检查点"""
    id: str
    type: CheckpointType
    description: str
    verification_command: str | None = None
    file_path: str | None = None
    expected_pattern: str | None = None
    verified: bool = False
    verified_at: datetime | None = None

class ExecutionRound(BaseModel):
    """执行轮次"""
    round_number: int
    started_at: datetime
    completed_at: datetime | None = None
    tasks_executed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    tokens_used: int = 0
    checkpoints_verified: int = 0
    degradation_level: DegradationLevel = DegradationLevel.NONE
    error_message: str | None = None
    llm_review: str | None = None

class Goal(BaseModel):
    """目标"""
    id: str
    name: str
    description: str
    status: GoalStatus = GoalStatus.PENDING
    session_id: str | None = None
    time_window: TimeWindow
    budget: ExecutionBudget
    checkpoints: list[Checkpoint] = []
    rounds: list[ExecutionRound] = []
    current_round: int = 0
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_tokens_used: int = 0
    completion_percentage: float = 0.0
    degradation_level: DegradationLevel = DegradationLevel.NONE
    last_error: str | None = None
```

### 4.2 GoalService 核心接口

```python
class GoalService:
    """目标生命周期管理器"""
    
    async def create_goal(
        self,
        name: str,
        description: str,
        time_window: TimeWindow,
        budget: ExecutionBudget,
        session_id: str | None = None,
    ) -> Goal:
        """创建新目标"""
        pass
    
    async def start_execution(self, goal_id: str) -> None:
        """启动目标执行"""
        pass
    
    async def execute_round(self, goal_id: str) -> ExecutionRound:
        """执行一轮迭代"""
        pass
    
    async def review_completion(self, goal: Goal) -> CompletionReview:
        """LLM 审查完成度"""
        pass
    
    async def should_continue(self, goal: Goal, review: CompletionReview) -> bool:
        """决策是否继续"""
        pass
    
    async def apply_degradation(self, goal: Goal, error: Exception) -> DegradationAction:
        """智能降级处理"""
        pass
```

### 4.3 CheckpointManager 核心接口

```python
class CheckpointManager:
    """检查点生成与验证器"""
    
    async def generate_checkpoints(
        self,
        goal: Goal,
        current_context: dict,
    ) -> list[Checkpoint]:
        """使用 LLM 生成检查点"""
        pass
    
    async def verify_checkpoint(self, checkpoint: Checkpoint) -> VerificationResult:
        """自动验证单个检查点"""
        pass
    
    async def verify_all(self, checkpoints: list[Checkpoint]) -> CheckpointReport:
        """验证所有检查点"""
        pass
```

### 4.4 TimeWindowManager 核心接口

```python
class TimeWindowManager:
    """时间窗口与定价管理器"""
    
    def is_off_peak(self, now: datetime | None = None) -> bool:
        """判断当前是否在闲时窗口"""
        pass
    
    def get_pricing_tier(self, now: datetime | None = None) -> PricingTier:
        """获取当前定价等级"""
        pass
    
    def should_execute_now(self, goal: Goal) -> bool:
        """判断是否应该执行"""
        pass
    
    async def get_next_execution_time(self, goal: Goal) -> datetime:
        """计算下次执行时间"""
        pass
```

## 5. 执行流程

### 5.1 主执行循环

```python
async def execute_goal(goal_id: str) -> Goal:
    goal = await get_goal(goal_id)
    goal.status = GoalStatus.RUNNING
    goal.started_at = datetime.utcnow()
    
    try:
        while await should_continue(goal):
            # 1. 时间窗口检查
            if not time_window_manager.should_execute_now(goal):
                next_time = await time_window_manager.get_next_execution_time(goal)
                await schedule_next_execution(goal_id, next_time)
                goal.status = GoalStatus.PAUSED
                return goal
            
            # 2. 执行一轮
            round_result = await execute_round(goal)
            goal.rounds.append(round_result)
            goal.current_round += 1
            goal.total_tokens_used += round_result.tokens_used
            
            # 3. 检查点验证
            checkpoint_report = await checkpoint_manager.verify_all(goal.checkpoints)
            goal.completion_percentage = checkpoint_report.progress_percentage
            
            # 4. LLM 审查完成度
            review = await review_completion(goal, checkpoint_report)
            round_result.llm_review = review.reasoning
            round_result.completed_at = datetime.utcnow()
            
            # 5. 决策
            if review.is_complete:
                goal.status = GoalStatus.COMPLETED
                break
            
            if not await should_continue(goal):
                goal.status = GoalStatus.COMPLETED
                break
            
            # 6. 保存进度
            await save_goal(goal)
            
            # 7. 通知用户
            await send_progress_notification(goal, round_result, checkpoint_report)
        
        # 生成最终报告
        await generate_final_report(goal)
        goal.completed_at = datetime.utcnow()
        
    except Exception as e:
        goal.status = GoalStatus.FAILED
        goal.last_error = str(e)
        await apply_degradation(goal, e)
    
    return goal
```

### 5.2 智能降级流程

```python
async def apply_degradation(goal: Goal, error: Exception) -> DegradationAction:
    consecutive_failures = count_consecutive_failures(goal.rounds)
    
    if consecutive_failures == 1:
        # 第一次失败：降级模型
        new_model = get_downgraded_model(goal.current_model)
        if new_model:
            return DegradationAction(
                action="switch_model",
                new_model=new_model,
                reason=f"任务失败，尝试使用 {new_model} 模型",
            )
    
    elif consecutive_failures == 2:
        # 第二次失败：简化任务
        simplified = await simplify_goal_description(goal)
        return DegradationAction(
            action="simplify_task",
            simplified_description=simplified,
            reason="任务失败两次，尝试简化任务描述",
        )
    
    else:
        # 第三次失败：停止
        await generate_failure_report(goal, error)
        return DegradationAction(
            action="stop",
            reason=f"连续失败 {consecutive_failures} 次，停止执行",
        )
```

## 6. 时间窗口与定价

### 6.1 配置示例

**只在深夜闲时执行：**
```json
{
  "time_window": {
    "off_peak_start": "23:00",
    "off_peak_end": "05:00",
    "weekends_off_peak": false,
    "min_pricing_tier": "off_peak"
  }
}
```

**周末全天 + 工作日夜间：**
```json
{
  "time_window": {
    "off_peak_start": "22:00",
    "off_peak_end": "06:00",
    "weekends_off_peak": true,
    "min_pricing_tier": "off_peak"
  }
}
```

**接受平峰时段：**
```json
{
  "time_window": {
    "off_peak_start": "20:00",
    "off_peak_end": "08:00",
    "weekends_off_peak": true,
    "min_pricing_tier": "standard",
    "holidays": ["2026-10-01", "2026-10-02"]
  }
}
```

### 6.2 定价策略

| 时间段 | 工作日 | 周末/节假日 | 定价等级 |
|--------|--------|-------------|----------|
| 00:00-06:00 | OFF_PEAK | OFF_PEAK | 0.5x |
| 06:00-09:00 | STANDARD | OFF_PEAK | 0.7x |
| 09:00-18:00 | PEAK | OFF_PEAK | 1.0x |
| 18:00-22:00 | STANDARD | OFF_PEAK | 0.7x |
| 22:00-24:00 | OFF_PEAK | OFF_PEAK | 0.5x |

## 7. API 设计

### 7.1 核心端点

```
GET    /api/v1/autonomous-goals          # 列表
POST   /api/v1/autonomous-goals          # 创建
GET    /api/v1/autonomous-goals/{id}     # 详情
PATCH  /api/v1/autonomous-goals/{id}     # 更新
DELETE /api/v1/autonomous-goals/{id}     # 删除
POST   /api/v1/autonomous-goals/{id}/start   # 启动
POST   /api/v1/autonomous-goals/{id}/pause   # 暂停
POST   /api/v1/autonomous-goals/{id}/resume  # 恢复
POST   /api/v1/autonomous-goals/{id}/cancel  # 取消
GET    /api/v1/autonomous-goals/{id}/rounds  # 执行历史
GET    /api/v1/autonomous-goals/{id}/report  # 执行报告
```

### 7.2 创建目标示例

**请求：**
```bash
curl -X POST http://localhost:8765/api/v1/autonomous-goals \
  -H "Content-Type: application/json" \
  -d '{
    "name": "重构认证模块",
    "description": "将 auth.py 拆分为多个模块，测试覆盖率提升到 80%",
    "time_window": {
      "off_peak_start": "22:00",
      "off_peak_end": "06:00",
      "weekends_off_peak": true,
      "min_pricing_tier": "off_peak"
    },
    "budget": {
      "max_rounds": 10,
      "max_hours": 8,
      "max_tokens": 1000000
    }
  }'
```

**响应：**
```json
{
  "id": "goal_abc123",
  "name": "重构认证模块",
  "status": "pending",
  "completion_percentage": 0.0,
  "created_at": "2026-10-17T14:30:00Z"
}
```

## 8. 前端 UI

### 8.1 页面结构

```
src/
├── features/
│   └── autonomous-goals/
│       ├── GoalListPage.tsx        # 目标列表页
│       ├── CreateGoalModal.tsx     # 创建目标弹窗
│       ├── GoalDetailPage.tsx      # 目标详情页
│       ├── GoalTimeline.tsx        # 执行时间线
│       └── CheckpointList.tsx      # 检查点列表
├── entities/
│   └── autonomous-goals/
│       ├── goalStore.ts            # Zustand store
│       ├── goalApi.ts              # API 调用
│       └── types.ts                # 类型定义
└── widgets/
    └── autonomous-goals/
        ├── GoalCard.tsx            # 目标卡片
        └── GoalProgress.tsx        # 进度条
```

### 8.2 TaskCenter 集成

在现有 TaskCenterWidget 中添加自主目标入口，实时显示运行中的目标进度。

### 8.3 通知机制

- **应用内 Toast**：关键事件实时通知
- **桌面通知**：用户授权后推送
- **执行报告**：每轮生成摘要，可查看历史

## 9. 实现计划

### 阶段 1：核心基础设施（2-3 天）

- [ ] 数据库模型和迁移脚本
- [ ] GoalRepository（CRUD）
- [ ] TimeWindowManager
- [ ] CheckpointManager 基础版
- [ ] 单元测试

### 阶段 2：执行引擎（3-4 天）

- [ ] GoalService 核心方法
- [ ] 集成 Planner/ChatDispatcher/LaneExecutor
- [ ] 执行轮次记录
- [ ] 集成测试

### 阶段 3：完成度审查与降级（2-3 天）

- [ ] CheckpointManager.generate_checkpoints()（LLM）
- [ ] GoalService.review_completion()（LLM）
- [ ] GoalService.apply_degradation()
- [ ] Prompt 工程优化

### 阶段 4：API 与调度集成（2 天）

- [ ] autonomous_goals_router
- [ ] SchedulerService 集成
- [ ] API 测试

### 阶段 5：前端 UI（3-4 天）

- [ ] goalStore + goalApi
- [ ] GoalListPage + GoalCard
- [ ] CreateGoalModal
- [ ] GoalDetailPage + GoalTimeline
- [ ] TaskCenter 集成
- [ ] 通知机制

### 阶段 6：报告与优化（2 天）

- [ ] GoalReportService
- [ ] 性能优化
- [ ] 文档编写

**总周期：14-18 天**

## 10. 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| LLM 幻觉导致错误检查点 | 中 | 高 | 结构化输出 + 人工审核选项 |
| 无限循环消耗大量 token | 中 | 高 | 三重预算控制 |
| 时间窗口判断错误 | 低 | 中 | 充分测试 + 手动覆盖 |
| 降级策略不够智能 | 中 | 中 | 记录历史，优化 prompt |
| 前端性能问题 | 低 | 低 | 分页加载，虚拟滚动 |

## 11. 测试策略

### 单元测试（覆盖率 > 80%）

- `test_time_window_manager.py` - 时间窗口判断
- `test_checkpoint_manager.py` - 检查点验证
- `test_goal_service.py` - 核心逻辑

### 集成测试

- `test_goal_execution_flow.py` - 完整执行流程
- `test_checkpoint_generation.py` - 检查点生成
- `test_api_endpoints.py` - API 端点

### 端到端测试

- `autonomous_goals.spec.ts` - 完整用户流程

## 12. 成功标准

**功能标准：**
- [ ] 用户可以创建、管理自主目标
- [ ] 系统在闲时自动执行目标
- [ ] 多轮迭代正常工作
- [ ] 完成度审查准确（> 80%）
- [ ] 智能降级有效减少失败率
- [ ] 实时进度监控
- [ ] 执行报告完整清晰

**性能标准：**
- [ ] API 响应时间 < 500ms
- [ ] 单轮执行时间 < 10 分钟
- [ ] 系统稳定运行 24 小时无崩溃

**质量标准：**
- [ ] 单元测试覆盖率 > 80%
- [ ] 无 CRITICAL/HIGH 级别 bug
- [ ] 代码符合项目规范
- [ ] 文档齐全

## 13. 后续优化

**短期（1-2 个月）：**
- 目标优先级（高/中/低）
- 目标依赖（A 完成后执行 B）
- 执行日志搜索和过滤
- 自定义检查点类型

**中期（3-6 个月）：**
- 集成更多 API 提供商的动态定价
- 跨目标资源共享
- 目标模板
- 协作目标

**长期（6-12 个月）：**
- 机器学习优化执行策略
- 自动调整预算参数
- 复杂工作流（条件分支、并行执行）
- 集成外部系统（GitHub Issues、Jira）

## 14. 参考资料

- 现有调度系统：`backend/services/scheduler.py`
- 编排系统：`backend/orchestration/`
- 执行器：`backend/orchestration/executor.py`
- 子代理运行器：`backend/orchestration/subagent_runner.py`
- 聊天调度器：`backend/orchestration/chat_dispatcher.py`
- 任务中心：`src/widgets/task-center/`
