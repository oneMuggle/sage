# Sage 任务层级化设计

## 状态

已确认设计，待用户审阅规格后进入实施计划。

## 背景

Sage 当前使用平铺任务列表加 `depends_on` DAG。DAG 能表达执行顺序和并行关系，但不能表达“主任务包含哪些子任务”的语义。`ChatTaskState.parent_task_id` 目前只服务 `followup_of`，存在于 dispatcher 内存中，不会写入计划或任务历史。

这会导致复杂任务出现三个问题：

1. 历史任务回放无法重建父子关系。
2. 前端只能按是否存在依赖做简单缩进，不能展示真正的任务树。
3. LLM 动态追加任务时不能声明其所属的主任务。

## 目标

本阶段实现增量任务层级模型：

- 计划项和运行任务都支持可选 `parent_task_id`。
- 计划项和运行任务都保存 `depth`，避免前端重复计算或遇到异常环时递归失控。
- 保留现有平铺数组和 `depends_on` DAG。
- `parent_task_id` 只表达归属和展示层级，不参与调度。
- `depends_on` 继续负责拓扑排序、并行波次和级联失败。
- 支持动态新增任务指定父任务。
- 旧计划和旧数据库记录无需迁移数据即可继续运行。
- 前端显示可折叠的树形任务视图。

## 非目标

本阶段不实现：

- 条件分支或 fallback edge。
- 递归 Planner 或无限深度自动分解。
- 分布式任务调度。
- 将 `depends_on` 改造成树结构。
- 改变 Lane 的重试模型。
- 删除现有 PlanCard 编辑流程。

## 设计原则

### 层级与依赖分离

一个任务可以属于父任务，但不一定依赖父任务；一个任务也可以依赖树中其他分支的任务。因此：

```text
parent_task_id  = 展示和归属关系
depends_on      = 执行依赖关系
```

默认情况下，子任务不自动依赖父任务。Planner 如果要求父任务完成后才能执行子任务，必须显式写入 `depends_on`。

### 兼容旧数据

所有新字段均可空或有默认值：

- 缺失 `parent_task_id` 等价于根任务。
- 缺失 `depth` 等价于 `0`。
- 老 `task_plan` 事件无需重放迁移。
- 老 `orch_tasks` 行通过 `ALTER TABLE ... ADD COLUMN` 补齐默认值。

### 单一校验入口

父子关系的校验集中在计划规范化/动态计划修改路径，不在 React 层重复实现业务规则。前端只负责容错渲染。

## 数据模型

### TaskPlanItem

计划项增加以下可选字段：

```typescript
interface TaskPlanItem {
  task_id: string;
  agent_id: string;
  goal: string;
  depends_on?: string[];
  parent_task_id?: string | null;
  depth?: number;
}
```

约束：

- `parent_task_id` 必须引用同一计划中存在的任务。
- 任务不能以自己为父任务。
- 父链不能形成环。
- `depth` 必须等于父任务深度加一，根任务为零。
- 最大深度使用常量 `MAX_TASK_DEPTH = 8`，超过时拒绝计划或动态添加。
- 省略 `depth` 时由后端根据父链计算。
- 客户端传入的错误 `depth` 不作为权威值。

### orch_tasks

新增可空字段：

```sql
parent_task_id TEXT NULL,
depth INTEGER NOT NULL DEFAULT 0
```

本阶段不增加父子外键。原因是：

- `orch_tasks.task_id` 当前跨 run 唯一约束，旧数据和计划覆盖路径存在不同生命周期。
- 父子关系已经由 `plan_json` 和事件快照校验。
- 不加外键可以保持旧数据库兼容和动态追加容错。

现有 `orch_tasks` 的 `run_id`、`status`、`blocked_by` 和用量字段保持不变。

### ChatTaskState

增加：

```python
parent_task_id: Optional[str] = None
```

现有 `parent_task_id` 字段保留其 followup 语义，但将其统一为计划层级字段和 followup 关联字段的兼容承载。为避免语义混淆，`followup_of` 在内部优先保留为单独的输入字段；当 followup 没有计划父任务时，不自动把它伪装成计划层级。

具体规则：

- `parent_task_id` 来自计划项的 `parent_task_id`。
- `followup_of` 继续通过历史上下文和执行依赖处理。
- 如果 followup 任务没有计划父任务，事件中不填 `parent_task_id`，但保留现有 followup 行为。

## 后端数据流

### 首次计划

1. Planner 生成平铺 `TaskPlanItem[]`。
2. 计划规范化器校验父引用、父环和最大深度。
3. `task_plan` 事件携带 `parent_task_id` 与规范化后的 `depth`。
4. `orch_runs.plan_json` 保存同一份规范化计划。
5. 首次 dispatch 时，dispatcher 从 `plan_json` 读取层级字段。

### 派发

对于每个任务：

1. dispatcher 从计划读取 `goal`、`agent_id`、`depends_on`、`parent_task_id`、`depth`。
2. `ChatTaskState` 保存层级字段。
3. `task_status` 事件携带层级字段。
4. `_persist_task_state` 将层级字段写入 `orch_tasks`。
5. `depends_on` 仍交给 `build_waves()`，层级字段不改变波次计算。

### 动态新增

`add_task_to_plan` 新增可选参数：

```json
{
  "task_id": "t9",
  "goal": "补充验证",
  "agent_id": "tester",
  "depends_on": ["t3"],
  "parent_task_id": "t2"
}
```

校验顺序：

1. `task_id` 格式、唯一性和必填字段。
2. `parent_task_id` 必须存在，不能等于新任务自身。
3. 新任务加入计划后检查父链无环。
4. 计算并写入规范化 `depth`。
5. 校验 `depends_on` 引用和整个 DAG 环。
6. 所有校验通过后才写入内存计划和 `plan_json`。

失败时不留下部分状态。

### 取消任务

取消父任务不自动取消子任务。子任务仍按自己的 `depends_on` 和状态执行。这样避免展示层级关系意外改变现有调度语义。若未来需要级联取消，应作为独立策略实现。

## API 与事件

### task_plan

每个 plan item 允许携带：

```json
{
  "task_id": "t2",
  "agent_id": "writer",
  "goal": "整理结果",
  "parent_task_id": "t1",
  "depth": 1,
  "depends_on": ["t1"]
}
```

### task_status

增加可选字段：

```json
{
  "parent_task_id": "t1",
  "depth": 1
}
```

旧消费者忽略新增字段即可。

### 持久化

`orch_tasks` 查询结果和历史回放返回上述两个字段。`OrchTask` dataclass 与 `upsert_state()` 参数同步增加字段，并对旧数据库列缺失提供防御性默认值。

## 前端设计

### TaskTreeSection

渲染前先把平铺计划转换为树形索引：

- 通过 `parent_task_id` 建立 `childrenByParent`。
- 根任务按原计划顺序显示。
- 子任务按原计划顺序显示。
- 找不到父任务的项降级为根任务并显示兼容状态，不丢弃任务。
- 深度优先使用后端 `depth`，渲染时仍限制最大缩进层级。

每个节点支持：

- 展开/折叠按钮。
- 父任务的聚合状态摘要。
- 现有状态图标、耗时、token、重试、已调整、跳过和重跑操作。
- 依赖提示仍保留，不用依赖关系替代树形缩进。

### 交互兼容

- 没有 `parent_task_id` 的旧计划保持当前平铺视觉效果。
- 键盘 Enter/Space 行为保持不变。
- 展开状态只存在于当前组件，不持久化到后端。
- 任务详情抽屉仍以 `task_id` 定位。

## 错误处理

- Planner 父引用非法：丢弃非法父引用并将任务提升为根，或在严格计划入口返回可解释错误。统一采用现有 Planner 的 fail-open 风格，避免简单任务因一个坏引用完全不可执行。
- 动态新增父引用非法：返回工具失败，不修改计划。
- 父环：返回具体环路径，不派发本次新增任务。
- 旧 `task_status` 缺字段：前端按根任务和深度零处理。
- 数据库列不存在：初始化迁移后默认可用；repo 读取仍对旧行采用 `None/0` 防御。

## 测试计划

### 后端单元测试

- 计划规范化：根任务、多级父链、非法父引用、自环、父环、最大深度。
- `add_task_to_plan`：无父任务、合法父任务、非法父任务、父环、DAG 环、原子失败。
- dispatcher：计划层级透传到 `ChatTaskState`、`task_status` 和 `orch_tasks`。
- `OrchTaskRepository`：新列写入、读取、旧列缺失默认值。
- 旧 plan JSON：没有新字段时行为不变。

### 前端单元测试

- 根任务和多级子任务的缩进与折叠。
- 父任务不存在时降级根节点。
- 没有层级字段的旧计划保持平铺渲染。
- 状态和操作按钮在树形渲染后保持可用。

### 验收标准

- 层级字段能从 Planner 计划进入 `task_plan`、`task_status`、`orch_tasks` 和历史回放。
- 旧计划、旧数据库和旧前端事件均能继续工作。
- 动态添加任务能声明父任务，非法关系不会污染计划。
- `depends_on` 的波次并行行为不发生变化。
- TaskTreeSection 能展示至少三层层级并支持折叠。
- 任务取消、重试、followup 和审批行为不回归。
- 相关后端与前端测试通过，Ruff/TypeScript 检查通过。

## 迁移与发布

- 数据库迁移使用幂等 `ALTER TABLE ... ADD COLUMN` 检查。
- 不删除或重命名现有字段。
- 计划 JSON 不做全量回填，旧 run 按根任务处理。
- 新字段先后端兼容，再前端启用树形展示。
- 发布前运行编排核心回归和前端任务树测试。
