# 闲时延迟执行系统（Idle & Deferred Task Execution）

> 日期: 2026-10-28
> 分支: feat/idle-deferred-tasks
> 状态: 实施中

## 背景与目标

Sage 已有完善的自主目标系统（GoalService + AutonomousGoalScheduler + TimeWindowManager），
但触发方式单一——仅支持**时间窗口**（off-peak hours）。

用户需求：**计划与执行解耦 + 条件感知调度**

- 用户与 LLM 对话生成实施计划后，不立即执行
- 在特定条件满足时（空闲、资源充足、低成本时段）自动执行
- 减少 API 费用、避免并发上限影响其他任务
- **显式 opt-in**：默认始终立即执行，闲时是用户主动选择

## 涉及的文件与模块

### 后端新增

| 文件 | 职责 |
|------|------|
| `backend/domain/execution_conditions.py` | 执行条件数据模型 |
| `backend/services/idle_detector.py` | 用户空闲检测服务 |
| `backend/services/condition_evaluator.py` | 条件评估引擎 |

### 后端修改

| 文件 | 修改内容 |
|------|---------|
| `backend/domain/autonomous_goals.py` | Goal 增加 `execution_conditions` + `trigger_mode` 字段 |
| `backend/services/autonomous_goal_scheduler.py` | 扩展扫描逻辑：评估条件而非仅检查时间窗口 |
| `backend/services/goal_service.py` | create_goal 接受 execution_conditions 参数 |
| `backend/api/autonomous_goals_router.py` | API 增加条件字段支持 |
| `backend/main.py` | lifespan 中初始化 IdleDetector |

### Electron 端修改

| 文件 | 修改内容 |
|------|---------|
| `electron/main.ts` | 增加 idle:user-activity IPC handler → 转发到后端 |
| `electron/preload.ts` | 暴露 reportActivity API |

### 前端修改

| 文件 | 修改内容 |
|------|---------|
| `src/entities/autonomous-goals/types.ts` | 增加 ExecutionCondition / TriggerMode 类型 |
| `src/features/autonomous-goals/CreateGoalModal.tsx` | 增加触发模式 + 条件选择 UI |

## 技术方案

### 1. 执行条件模型

```python
class ConditionType(str, Enum):
    TIME_WINDOW = "time_window"     # 在指定时间段内（已有）
    IDLE = "idle"                   # 用户空闲 N 分钟
    RESOURCE = "resource"           # 系统资源充足（CPU<30%）
    NO_ACTIVE_TASKS = "no_active"   # 无其他运行中 Agent 任务
    MANUAL = "manual"               # 用户手动触发

class TriggerMode(str, Enum):
    IMMEDIATE = "immediate"         # 立即执行（默认）
    CONDITIONAL = "conditional"     # 条件满足后执行

@dataclass
class ExecutionCondition:
    type: ConditionType
    params: Dict[str, Any]
    # 示例: {"type": "idle", "params": {"min_idle_minutes": 15}}
    # 示例: {"type": "time_window", "params": {"start": "02:00", "end": "06:00"}}
```

### 2. 空闲检测

Electron 前端监听用户活动 → IPC 上报 → Backend IdleDetector 维护最后活跃时间。

三级空闲：
- `none`: 用户活跃（< 5 分钟）
- `short`: 短暂空闲（5-30 分钟）→ 执行轻任务
- `deep`: 深度空闲（> 30 分钟）→ 执行重任务

### 3. 条件评估引擎

AutonomousGoalScheduler 每 60s 扫描 pending goals，对每个 goal：
1. 检查 trigger_mode（IMMEDIATE → 直接启动）
2. CONDITIONAL → 遍历 execution_conditions，全部满足才启动
3. 复用现有 TimeWindowManager 处理 time_window 类型条件

### 4. 用户主权

- 默认 trigger_mode = IMMEDIATE，行为与现有系统完全一致
- 用户显式选择 CONDITIONAL 时才进入条件队列
- 全局偏好可控制是否提示闲时选项（默认关闭）

## 实施步骤

### Phase A: 后端核心（条件模型 + 空闲检测 + 评估引擎）

- [x] A1: 创建 `backend/domain/execution_conditions.py`
  - ConditionType / TriggerMode / ExecutionCondition 数据模型
- [x] A2: 扩展 `backend/domain/autonomous_goals.py`
  - Goal 增加 `trigger_mode` + `execution_conditions` 字段
  - to_dict / from_dict 适配
- [x] A3: 创建 `backend/services/idle_detector.py`
  - IdleDetector 类，维护 last_activity 时间戳
  - report_activity() / get_idle_level() / get_idle_minutes()
  - 三级空闲判断
- [x] A4: 创建 `backend/services/condition_evaluator.py`
  - ConditionEvaluator 类
  - evaluate(condition) → bool
  - evaluate_all(conditions) → bool（AND 语义）
- [x] A5: 扩展 `backend/services/autonomous_goal_scheduler.py`
  - 注入 IdleDetector + ConditionEvaluator
  - 扫描逻辑：IMMEDIATE 直接启动，CONDITIONAL 评估条件
- [x] A6: 扩展 `backend/services/goal_service.py`
  - create_goal 接受 trigger_mode + execution_conditions
- [x] A7: 扩展 `backend/api/autonomous_goals_router.py`
  - CreateGoalIn / GoalOut 增加条件字段
  - POST /goals 支持 trigger_mode
- [x] A8: 扩展 `backend/main.py`
  - lifespan 中初始化 IdleDetector
  - POST /api/v1/idle/activity + GET /api/v1/idle/status 端点

### Phase B: Electron 空闲上报

- [x] B1: 通过现有 `backendRequest` relay 实现，无需新 IPC channel
- [x] B2: `src/entities/autonomous-goals/idleReporter.ts` — 节流活动上报
- [x] B3: `src/App.tsx` — 启动时调用 initIdleReporter()

### Phase C: 前端条件选择 UI

- [x] C1: `src/entities/autonomous-goals/types.ts` 增加 TriggerMode / ConditionType / ExecutionCondition 类型
- [x] C2: Goal / CreateGoalInput 接口增加新字段
- [x] C3: `goalStore.test.ts` 修复新字段类型

### Phase D: 测试

- [x] D1: `backend/tests/unit/test_idle_deferred_execution.py` — 30 测试全通过

## 风险评估

| 风险 | 缓解 |
|------|------|
| IdleDetector 误判（用户在看视频但无鼠标活动） | 三级空闲 + 可配置阈值，用户可手动触发 |
| SQLite 并发写入 | 复用 `_SQLITE_LOCK`，与现有 GoalRepository 一致 |
| Electron IPC 丢消息（窗口最小化） | 心跳机制，每 30s 上报一次活跃状态 |
| Win7 Python 3.8 兼容 | 不使用 TaskGroup/match-case，用 if-elif + gather |

## 依赖

- 现有: GoalService, AutonomousGoalScheduler, TimeWindowManager, GoalRepository
- 现有: Electron IPC 基础设施
- 无新增外部依赖
