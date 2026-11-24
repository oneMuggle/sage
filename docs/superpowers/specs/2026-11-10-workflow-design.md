# Sage Workflow 功能设计文档

> 日期：2026-11-10  
> 状态：设计中  
> 作者：Claude + 用户协作

---

## 1. 背景与目标

### 1.1 需求

Sage 需要一个**工作流（Workflow）**功能，支持"解析任务书 → 制定实施计划 → 分阶段执行 → 结果后处理 → 产出报告"等**固定流程编排**。

**核心约束**：
- **不是** CFD 特定（CFD 只是举例），是通用模式
- 复用现有**专家（Agent）**和**项目（Project）**模块
- 参考主流 AI 应用：Dify / Coze / n8n / LangGraph / CrewAI / Cursor rules / Claude Code CLAUDE.md
- 用户偏好：**对话驱动**（user+AI 聊天确定阶段和动作）、**Skill-like**（markdown 可读可写）、**软约束 + 硬门禁**

### 1.2 目标

1. **概念模型**：工作流 = Playbook 超集（v1.0 → v1.1）
2. **双轨存储**：全局工作流库 + 项目内快照（复用 playbook_library + project_playbooks 模式）
3. **编排引擎驱动**：每个工作流阶段 = orchestration lane = Sage agent 执行
4. **软/硬约束层级**：`stage_order` / `executor` 软（AI 指导）；`required_stages` / `gate` 硬（引擎强制执行）
5. **结构化产物传递**：阶段间数据通过 JSON + 文件传递（`<workspace>/.sage/workflow/<run_id>/<stage_id>/`）
6. **TaskCenter 集成**：workflow_run 成为 unifiedTaskModel 第 7 个 source

---

## 2. 概念模型与数据流

### 2.1 工作流 = Playbook 超集

**Playbook v1.0**（已有）：
```yaml
schema_version: "1.0"
name: "科研规程"
stages:
  - id: research
    goal: "调研并收集资料"
    exit_criteria: "产出调研报告"
```

**Workflow v1.1**（扩展）：
```yaml
schema_version: "1.1"
id: "research-grant-cfd"
name: "CFD 科研课题"
stage_order: [parse, plan, design, compute, postprocess, report]
required_stages: [parse, plan, report]
recommended_specialists:
  parse: "task-book-parser"
  plan: "project-planner"
  report: "report-writer"
```

**新增字段**（v1.1 vs v1.0）：
| 字段 | 类型 | 用途 | 软/硬 |
|---|---|---|---|
| `id` | string | 工作流唯一标识 | 硬 |
| `stage_order` | list | 阶段执行顺序 | 软（AI 指导） |
| `required_stages` | list | 必须完成的阶段 | 硬（引擎强制） |
| `recommended_specialists` | dict | 推荐 agent id 映射 | 软（AI 参考） |
| `inputs` | list | 阶段输入（JSON 字段） | 硬（gate 校验） |
| `outputs` | list | 阶段输出（JSON 字段） | 硬（gate 校验） |
| `gate` | string | 阶段通过条件表达式 | 硬（引擎校验） |

### 2.2 数据流

```
用户创建 workflow_run
  ↓
workflow_loader 解析 markdown（v1.1）
  ↓
orchestration 引擎创建 run_id
  ↓
阶段 1：parse（executor: task-book-parser）
  ├─ lane 执行（AI 调用工具）
  ├─ 产物落盘：<workspace>/.sage/workflow/<run_id>/parse/outputs.json
  └─ gate 校验：goals non-empty AND acceptance_criteria non-empty
      ↓ 通过
阶段 2：plan（executor: project-planner）
  ├─ 读取 parse 产物（parsed_spec）
  ├─ lane 执行
  ├─ 产物落盘：plan/outputs.json
  └─ gate 校验：milestones non-empty
      ↓ 通过
...
阶段 N：report（executor: report-writer）
  └─ 读取前序产物 → 产出最终报告
```

### 2.3 产物存储路径

```
<workspace>/.sage/workflow/<workflow_run_id>/
├── manifest.json          # workflow_run 元数据
├── parse/
│   ├── outputs.json       # 结构化输出
│   ├── files/             # 文件产物
│   │   └── task_book.pdf
│   └── trace.jsonl        # 执行 trace（事件流）
├── plan/
│   ├── outputs.json
│   └── trace.jsonl
└── ...
```

---

## 3. Markdown Schema（v1.1）

### 3.1 完整示例

以下示例以科研课题流程为例说明 schema 形态；**schema 本身不含任何领域特定字段**，`executor` 是通用 agent id，`inputs`/`outputs` 是通用 JSON 字段名。

````markdown
---
schema_version: "1.1"
id: "research-grant-cfd"
name: "CFD 科研课题"
description: "从任务书到课题报告的完整流程"
stage_order:
  - parse
  - plan
  - design
  - compute
  - postprocess
  - report
required_stages:
  - parse
  - plan
  - report
recommended_specialists:
  parse: "task-book-parser"
  plan: "project-planner"
  design: "primary"
  compute: "primary"
  postprocess: "primary"
  report: "report-writer"
---

## 1. parse（解析任务书）

解析用户上传的任务书，提取目标、验收标准、约束条件。

```yaml
executor: task-book-parser | primary
gate: "goals non-empty AND acceptance_criteria non-empty"
inputs:
  - user_upload:file
outputs:
  - parsed_spec:json
```

**阶段说明**：
- 输入：用户上传的任务书文件（PDF/Word/TXT）
- 输出：结构化 JSON（goals / acceptance_criteria / constraints）
- 执行器：task-book-parser 专家（若无则降级 primary）

---

## 2. plan（制定实施计划）

基于 parsed_spec，制定里程碑、任务分解、时间线。

```yaml
executor: project-planner | primary
gate: "milestones non-empty AND timeline valid"
inputs:
  - parsed_spec:json (from parse)
outputs:
  - milestones:json
  - timeline:json
```

---

## 3. design（设计计算状态）

根据计划设计计算所需的各个状态（边界条件、网格、求解器配置）。

```yaml
executor: primary
gate: "states non-empty AND mesh_quality >= 0.8"
inputs:
  - milestones:json (from plan)
outputs:
  - design_states:json
```

---

## 4. compute（执行计算）

调用外部工具（bash/python）执行计算。

```yaml
executor: primary
timeout: 24h
gate: "exit_code == 0 AND output_files non-empty"
inputs:
  - design_states:json (from design)
outputs:
  - raw_results:files
```

---

## 5. postprocess（结果后处理）

对原始结果进行后处理（可视化、统计分析）。

```yaml
executor: primary
gate: "processed_results non-empty"
inputs:
  - raw_results:files (from compute)
outputs:
  - processed_results:json
  - charts:files
```

---

## 6. report（撰写课题报告）

汇总所有产物，撰写最终报告。

```yaml
executor: report-writer | primary
gate: "report.length > 5000 AND references non-empty"
inputs:
  - parsed_spec:json (from parse)
  - milestones:json (from plan)
  - processed_results:json (from postprocess)
  - charts:files (from postprocess)
outputs:
  - report:docx
  - references:json
```
````

### 3.2 字段规范

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `schema_version` | string | ✓ | — | 固定 "1.1" |
| `id` | string | ✓ | — | 工作流唯一标识（kebab-case） |
| `name` | string | ✓ | — | 显示名称 |
| `description` | string | ✗ | "" | 一句话描述 |
| `stage_order` | list | ✓ | — | 阶段执行顺序 |
| `required_stages` | list | ✗ | [] | 必须完成的阶段（缺省 = 全部） |
| `recommended_specialists` | dict | ✗ | {} | agent id 映射（缺省 = primary） |
| `executor` | string | ✓（阶段级） | — | agent id 或 "primary" |
| `gate` | string | ✗ | "true" | 阶段通过条件表达式 |
| `inputs` | list | ✗ | [] | 输入字段（`name:type`） |
| `outputs` | list | ✗ | [] | 输出字段 |
| `timeout` | string | ✗ | "1h" | 阶段超时（如 "24h"） |

**兼容性**：v1.0 playbook 文件在 v1.1 loader 下**必须仍能加载** —— loader 检测 `schema_version` 决定走 playbook 路径还是 workflow 路径。

**两处 executor 声明的分工**（易混淆点，明确如下）：

| 字段 | 层级 | 作用 | 生效时机 |
|---|---|---|---|
| `recommended_specialists`（顶层） | 工作流级 | 给 AI 的**建议**："这个阶段大概适合哪个专家" | 仅在对话式阶段发现 / AI 自主规划时参考 |
| `executor`（阶段级） | 阶段级 | **实际派发**的 agent id | 引擎执行该阶段时唯一依据 |

**优先级**：阶段级 `executor` 缺失时，引擎取 `recommended_specialists[stage_id]`，再缺失则取 `"primary"`。顶层 map 不覆盖阶段级显式声明。

---

## 4. 阶段执行引擎

### 4.1 阶段 → Orchestration Lane

**映射关系**：
| Workflow 概念 | Orchestration 概念 |
|---|---|
| `workflow_run` | `orch_run`（复用） |
| `stage` | `orch_task`（1:1） |
| `executor` | `lane.agent_id`（动态派发） |
| `gate` | 新增 `gate_evaluator`（JSON 表达式） |
| `inputs` / `outputs` | lane 的 `context`（JSON dict） |

**执行流程**：
1. `workflow_run` 创建 → 初始化 `orch_run`（`status=running`）
2. 阶段 1 启动 → 创建 `orch_task`（`status=running`）
3. `subagent_runner` 根据 `executor` 字段派发 agent：
   - `executor: "task-book-parser"` → 调用 `get_enabled_agent("task-book-parser")` → 找到 agent row → 构造 system prompt
   - `executor: "primary"` → 使用当前会话主 agent
4. Lane 执行（AI 调用工具、产生产物）
5. 产物落盘（`outputs.json` + `files/`）
6. Gate 校验（`gate_evaluator` 读 `outputs.json`，校验表达式）
7. 通过 → 阶段完成 → 下一阶段启动
8. 失败 → 重试 / 用户介入

### 4.2 Agent 动态派发（替换硬编码 agent_hint）

**现状**（`backend/orchestration/planner.py:113-122`）：
```python
# 硬编码 5 个角色
ALLOWED_AGENT_HINTS = {"researcher", "coder", "writer", "reviewer", "memory_manager"}
```

**改造**：
```python
# 动态派发
def resolve_agent(executor: str, project_id: str) -> AgentProfile:
    if executor == "primary":
        return get_primary_agent()
    agent = get_enabled_agent(executor, project_id=project_id)
    if not agent:
        logger.warning(f"Agent '{executor}' not found, fallback to primary")
        return get_primary_agent()
    return agent
```

**接线**：
- `backend/agents/profiles.py:53-103` — `AgentProfile` dataclass（已有）
- `backend/agents/registry.py` — `get_enabled_agent(agent_id, project_id)`（已有）
- `backend/orchestration/subagent_runner.py:180-239` — `Lane` 指定 `agent_id` → `get_enabled_agent` → `compose_system_prompt`（已有）

### 4.3 Gate 表达式求值器

**新增模块**：`backend/services/workflow_gate_eval.py`

**表达式语法**：
```
<field> <op> <value>
<expr> AND <expr>
<expr> OR <expr>
NOT <expr>
(<expr>)
```

**操作符**：
| op | 含义 | 示例 |
|---|---|---|
| `non-empty` | 字段非空 | `goals non-empty` |
| `==` | 等于 | `exit_code == 0` |
| `!=` | 不等于 | `status != failed` |
| `>=` / `<=` | 大于等于 / 小于等于 | `mesh_quality >= 0.8` |
| `>` / `<` | 大于 / 小于 | `report.length > 5000` |
| `contains` | 包含 | `tags contains "urgent"` |
| `matches` | 正则匹配 | `filename matches ".*\\.pdf$"` |
| `valid` | 格式合法（日期/JSON/URL） | `timeline valid` |

**字段路径**：支持点号访问嵌套字段，如 `report.length`、`results[0].name`（仅支持数字下标）。路径不存在时该子表达式判定为 `false`，不抛异常。

**类型比较**：`>=` / `<=` / `>` / `<` 只在两侧都可转为数值时生效；否则该子表达式判定为 `false`（不做字符串字典序比较，避免语义歧义）。

**示例**：
```python
from backend.services.workflow_gate_eval import evaluate_gate

outputs = {
    "goals": ["目标 1", "目标 2"],
    "acceptance_criteria": ["标准 1"],
}
gate_expr = "goals non-empty AND acceptance_criteria non-empty"
result = evaluate_gate(gate_expr, outputs)
# result = True
```

**实现**：
- 简单表达式：手写递归下降解析器（不引入新依赖，避免 win7 分支 py38 兼容问题）
- 输出：`{"passed": bool, "reason": str}`（失败原因用于反馈给 AI）

### 4.4 产物落盘与传递

**落盘路径**：
```python
workspace = "<project_workspace>/.sage/workflow/<workflow_run_id>"
stage_dir = f"{workspace}/{stage_id}"
os.makedirs(stage_dir, exist_ok=True)

# outputs.json
with open(f"{stage_dir}/outputs.json", "w") as f:
    json.dump(outputs, f)

# files/
for file in output_files:
    shutil.copy(file, f"{stage_dir}/files/")

# trace.jsonl（事件流）
for event in trace_events:
    with open(f"{stage_dir}/trace.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")
```

**传递机制**：
- 阶段 N 的 `inputs` 字段引用前序阶段产物：
  ```yaml
  inputs:
    - parsed_spec:json (from parse)
    - milestones:json (from plan)
  ```
- Lane 启动时，`subagent_runner` 读取前序 `outputs.json`，注入到 lane context：
  ```python
  context = {
      "parsed_spec": load_outputs("parse"),
      "milestones": load_outputs("plan"),
  }
  lane = Lane(agent_id=executor, goal=stage_goal, context=context)
  ```

### 4.5 暂停 / 恢复 / 重跑

**暂停**：
- API：`POST /workflow/runs/{id}/stages/{sid}/pause`
- 行为：挂起 lane（保留 trace），`orch_task.status = paused`
- 复用 `GoalService.pause()` 模式（已有）

**恢复**：
- API：`POST /workflow/runs/{id}/stages/{sid}/resume`
- 行为：重启 lane，`orch_task.status = running`
- 难点：恢复 lane state（从 `trace.jsonl` 重建 context）

**重跑**：
- API：`POST /workflow/runs/{id}/stages/{sid}/rerun`
- 行为：清除当前阶段产物，重启 lane
- `orch_task.status = running`，删除 `stage_dir/*`

---

## 5. 任务书解析 + 对话式阶段发现

### 5.1 入口

**两种方式**：
1. **项目工作台 Tab**（显式）：
   - 用户点击"工作流"Tab → 点击"从任务书开始"
   - 弹出对话框：选择工作流模板（如"科研课题"）→ 上传任务书文件
   - 系统创建 `workflow_run`，启动阶段 1（parse）

2. **聊天快捷**（隐式）：
   - 用户在新会话输入："用科研课题工作流，这是我的任务书 [附件]"
   - AI 识别意图 → 调用 `discover_workflow("research-grant-cfd")` → 创建 `workflow_run`

### 5.2 阶段配置对话（AI 引导）

**流程**：
1. 用户上传任务书 → 系统创建 `workflow_run`
2. AI 读取工作流 markdown（作为 system prompt 一部分）
3. AI 发起对话：
   ```
   AI: 我已读取你的任务书。接下来我会分 6 个阶段完成这个课题：
       1. parse — 解析任务书
       2. plan — 制定实施计划
       3. design — 设计计算状态
       4. compute — 执行计算
       5. postprocess — 结果后处理
       6. report — 撰写报告

       每个阶段我会用不同的专家来执行。你希望调整阶段顺序或增减阶段吗？
   ```
4. 用户回应：
   ```
   User: 把 design 和 compute 合并成一个阶段
   ```
5. AI 修改工作流 markdown（动态调整）：
   ```yaml
   stage_order: [parse, plan, design-compute, postprocess, report]
   ```
6. AI 确认：
   ```
   AI: 好的，已合并 design 和 compute 为"design-compute"阶段。
       现在开始阶段 1：parse。请确认任务书文件是否正确。
   ```

### 5.3 阶段内对话模式

每个阶段执行时，用户可选择对话模式：

| 模式 | 行为 | 适用场景 |
|---|---|---|
| **自动**（默认） | AI 自主执行，不中断 | 用户信任 AI，长任务 |
| **确认** | 每步需用户确认 | 高风险操作 |
| **介入** | 用户可随时插话 | 用户想参与决策 |
| **接管** | 用户完全控制 | 用户想自己执行 |

**切换方式**：
- 阶段详情面板 → 下拉菜单选择模式
- 或对话中输入 `/mode auto` / `/mode confirm` / `/mode intervene` / `/mode takeover`

### 5.4 Parse 阶段 specifics

**目标**：解析任务书，提取结构化信息

**执行器**：`task-book-parser` 专家（若无则降级 `primary`）

**输入**：
- 用户上传的文件（PDF/Word/TXT）

**输出**（`outputs.json`）：
```json
{
  "goals": ["目标 1", "目标 2"],
  "acceptance_criteria": ["标准 1", "标准 2"],
  "constraints": ["约束 1"],
  "timeline": "2026-12-31",
  "budget": "100 万"
}
```

**Gate**：
```yaml
gate: "goals non-empty AND acceptance_criteria non-empty"
```

**实现**：
- 复用 `task-book-parser` 专家（已有，在 `backend/agents/profiles.py`）
- 专家调用 `extract_text_from_file()`（已有工具）→ 读取文件内容
- 专家调用 `structure_task_book(text)`（已有工具）→ 结构化 JSON
- 产物落盘 → gate 校验 → 通过 → 下一阶段

---

## 6. 失败 / 暂停 / 恢复

### 6.1 阶段状态机

```
                ┌─── 用户跳过 ───┐
                │                ▼
     ┌──────┐  start   ┌──────┐       ┌────────────┐
     │pend. │ ──────► │run.  │──────►│succeeded / │
     └──────┘          └──┬───┘       │failed /    │
                          │           │skipped     │
                          │ pause     └────────────┘
                          ▼
                     ┌────────┐
                     │paused  │
                     └───┬────┘
                         │ resume
                         ▼
                     ┌──────┐
                     │run.  │
                     └──────┘
```

**新增状态**：
| 状态 | 含义 | TaskCenter 视觉 |
|---|---|---|
| `pending` | 等待上游 gate 通过 | 灰 |
| `running` | lane 在执行 | 蓝 + spinner |
| `paused` | 用户主动暂停 | 黄 + 暂停图标 |
| `awaiting_confirmation` | gate 通过，等用户确认（`required_stages`） | 紫 + 确认按钮 |
| `gate_retry` | gate 失败，AI 在重试 | 橙 + "AI 在补产物" |
| `succeeded` | gate 通过 | 绿 |
| `failed` | lane 失败或 gate 失败超限 | 红 |
| `skipped` | 用户跳过 | 灰 + 删除线 |

### 6.2 失败处理

#### Lane 失败（AI/LLM/工具失败）

- lane 抛错 → task 失败 → 事件 `workflow.stage.failed`
- TaskCenter 卡片显示失败原因 + **重跑本阶段** 按钮
- 重跑：清除本阶段产物 + 重启 lane（trace.jsonl 保留历史）
- 不自动重跑（避免 LLM 错误循环烧 token）

#### Gate 失败

gate 失败 = stage 不通过，但产物还在。

**默认处理（AI 自动修）**：
1. gate evaluator 把失败原因（哪些字段空 / 哪些条件不满足）注入 AI 的 system prompt
2. AI 重新执行，产出新 `outputs.json`
3. gate 再次校验
4. 重试上限 3 次（可配置 `max_gate_retries`）

**gate retry 与 rerun 的产物处理区别**（易混淆点，明确如下）：

| | gate retry | rerun（用户手动重跑） |
|---|---|---|
| 触发 | gate 校验失败，引擎自动 | 用户在 UI 点击"重跑" |
| 旧产物 | **保留**，注入 AI 上下文供改进 | **清除**，AI 从零开始 |
| 旧 trace | 保留并追加（trace.jsonl 累积） | 保留并追加 |
| 重试次数 | 计入 `max_gate_retries`（默认 3） | 不计入 |

**超限后**：
- task 状态转 `failed`
- TaskCenter 显示"gate 失败：{原因}"
- 用户可选：
  - **手动放行**（`manual_override`）→ 标 `manual_overridden=true`，下一阶段启动
  - **编辑产物**（通过"阶段对话"让 AI 再改一遍）
  - **跳过阶段** → 标 `skipped`，下一阶段启动

### 6.3 长任务处理

**典型场景**：数值计算 3-24 h、大规模 LLM 推理、外部 API 调用

#### Timeout 与心跳

- 每阶段可设 `timeout`（默认 1h）
- lane 心跳监控复用 `orchestration/heartbeat.py`（15s tick）
- 超时 → gate 自动失败，提示用户"阶段 X 超时"

#### 外部工具集成

- **bash 脚本**：复用 `BashSessionRegistry`（`backend/tools/bash_session.py`）
- **HPC 提交**：新增 `hpc_submit` 工具（agent 调一次，异步拿 job_id；`hpc_status` 轮询）
- **长时间运行进程**：lane 执行期间可 `await` 异步任务，心跳持续

#### 进度上报

- lane 每 N 秒（或每 tool call）写 `trace.jsonl`（增量事件）
- 前端订阅 NDJSON → 在"阶段对话"面板流式显示
- 用户可看：AI 在想什么、调了什么工具、产物文件变化

### 6.4 跨 session 恢复

**后端重启**：
- 后端启动时扫描 `<workspace>/.sage/workflow/*/manifest.json`
- 重建 `orch_runs` 状态：`completed_stages` + `current_stage`
- 当前 stage 标 `failed`（因为 lane 已死），等用户重跑

**浏览器关闭**：
- TaskCenter 卡片持久化在 SQLite（`scheduled_tasks` 表类似机制）
- 重开浏览器 → TaskCenter 恢复卡片 → 用户可继续操作

**Lane 崩溃**：
- 进程被 kill → heartbeat 超时 → lane 标 failed → task 标 failed
- 产物已落盘（除最后未提交的）
- 用户重跑该阶段

### 6.5 用户操作一览

| 操作 | API | 行为 |
|---|---|---|
| 暂停 | `POST /workflow/runs/{id}/stages/{sid}/pause` | 挂起 lane，保留 trace |
| 恢复 | `POST /workflow/runs/{id}/stages/{sid}/resume` | 重启 lane |
| 重跑 | `POST /workflow/runs/{id}/stages/{sid}/rerun` | 清产物 + 重启 |
| 跳过 | `POST /workflow/runs/{id}/stages/{sid}/skip` | 标 skipped，下一阶段启动 |
| 手动放行 gate | `POST /workflow/runs/{id}/stages/{sid}/override-gate` | 标 manual_overridden |
| 接管 | `POST /workflow/runs/{id}/stages/{sid}/takeover` | lane 转 chat 模式 |
| 确认下一阶段 | `POST /workflow/runs/{id}/stages/{sid}/confirm` | 复用 playbook stage/confirm |

---

## 7. UI 布局

### 7.1 入口（3 处）

| 入口 | 位置 | 触发 |
|---|---|---|
| **项目工作台 Tab** | 项目详情 → 工作流 Tab（与 Playbook / 文件 / 规则并列） | 点击 Tab |
| **聊天快捷** | 新会话时，用户输入"用 XX 工作流"或"从任务书开始" | AI 识别意图 → 触发创建流程 |
| **全局工作流库** | 侧边栏 → 全局工具 → 工作流库（类似 Playbook 全局库） | 点击入口 → 浏览 / 导入 |

### 7.2 项目工作台 Tab 布局

```
┌─────────────────────────────────────────────────────────┐
│ 工作流                                                   │
├─────────────────────────────────────────────────────────┤
│ [+ 新建工作流]  [导入]  [从任务书开始]                     │
├─────────────────────────────────────────────────────────┤
│ 科研课题流程         进行中  3/6 阶段                     │
│ ├─ ✓ parse         已完成                              │
│ ├─ ✓ plan          已完成                              │
│ ├─ ● design        执行中  [暂停] [跳过]                │
│ ├─ ○ compute       待执行                              │
│ ├─ ○ postprocess   待执行                              │
│ └─ ○ report        待执行                              │
│                                                         │
│ 项目公文处理        未启动                               │
│ └─ [开始执行]                                           │
└─────────────────────────────────────────────────────────┘
```

**卡片结构**：
- 左侧：workflow name + 状态徽标（进行中/未启动/已完成）
- 中间：进度条（x/y 阶段）
- 右侧：操作按钮（展开 / 暂停 / 恢复）
- 展开：阶段列表（每项有状态图标 + 操作按钮）

### 7.3 阶段详情面板

点击阶段 → 右侧滑出面板（或新 Tab）：

```
┌─────────────────────────────────────────┐
│ design（设计计算状态）                    │
├─────────────────────────────────────────┤
│ 执行器：primary                            │
│ Gate：states non-empty AND mesh_quality  │
│       ≥ 0.8                              │
│ 输入：parsed_spec (from parse)           │
│ 输出：design_states.json                 │
├─────────────────────────────────────────┤
│ 产物                                     │
│ ├─ design_states.json  [查看] [下载]     │
│ ├─ mesh_quality.json   [查看] [下载]     │
│ └─ files/                                │
│    └─ geometry.stp    [预览]             │
├─────────────────────────────────────────┤
│ 对话记录（trace）                        │
│ ├─ AI: 正在解析 parsed_spec...           │
│ ├─ AI: 调用工具 design_states            │
│ ├─ AI: 产出 design_states.json（3 项）   │
│ └─ AI: gate 校验通过 ✓                   │
├─────────────────────────────────────────┤
│ [暂停] [恢复] [重跑] [跳过] [接管]       │
└─────────────────────────────────────────┘
```

**面板组件**：
- `WorkflowStageDetailPanel`（复用 `PlaybookStageDetail` 的布局模式）
- 产物列表：复用 `ArtifactsList`（已有）
- 对话记录：复用 `ChatBubble`（已有），数据源从 `trace.jsonl` 读

### 7.4 全局工作流库页面

布局：
```
┌─────────────────────────────────────────┐
│ 工作流库                                 │
├─────────────────────────────────────────┤
│ [搜索]  [筛选：全部 / 科研 / 工程 / 公文] │
├─────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────┐         │
│ │ 科研课题    │ │ 项目公文    │         │
│ │ 6 阶段      │ │ 4 阶段      │         │
│ │ 使用 12 次  │ │ 使用 5 次   │         │
│ │ [预览]      │ │ [预览]      │         │
│ │ [导入]      │ │ [导入]      │         │
│ └─────────────┘ └─────────────┘         │
└─────────────────────────────────────────┘
```

**交互**：
- 点击"预览"→ 弹出对话框，显示 workflow markdown 全文
- 点击"导入"→ 选择目标项目 → 创建 `workflow_runs` 行

### 7.5 TaskCenter 集成（7th source）

**数据模型扩展**：
```typescript
// src/features/task-center/unifiedTaskModel.ts
export type UnifiedTaskSource =
  | 'registry' | 'chat' | 'lane' | 'goal' | 'todo' | 'scheduled'
  | 'workflow';  // ← 新增

export interface WorkflowTask {
  source: 'workflow';
  workflowRunId: string;
  workflowName: string;
  currentStageId: string;
  currentStageName: string;
  progress: { completed: number; total: number };
  status: 'running' | 'paused' | 'failed' | 'awaiting_confirmation';
  actions: Array<'pause' | 'resume' | 'rerun' | 'skip'>;
}
```

**TaskCenter 卡片**：
- 标题：workflow name
- 副标题：当前阶段名
- 进度条：x/y
- 操作按钮：暂停 / 恢复 / 重跑 / 跳过
- 点击卡片 → 跳转到项目工作台 Tab（展开该 workflow）

**事件订阅**：
- 后端 `workflow.stage.started` / `workflow.stage.completed` / `workflow.stage.failed` → EventHub → 前端 NDJSON 订阅 → TaskCenter 实时更新

### 7.6 i18n

**zh.json**（新增）：
```json
{
  "workflow.title": "工作流",
  "workflow.stage": "阶段",
  "workflow.pause": "暂停",
  "workflow.resume": "恢复",
  "workflow.skip": "跳过",
  "workflow.takeover": "接管",
  "workflow.rerun": "重跑",
  "workflow.artifacts": "产物",
  "workflow.gate": "门禁",
  "workflow.executor": "执行器",
  "workflow.library": "工作流库",
  "workflow.import": "导入",
  "workflow.preview": "预览",
  "workflow.new": "新建工作流",
  "workflow.fromTaskBook": "从任务书开始"
}
```

**en.json**：
```json
{
  "workflow.title": "Workflow",
  "workflow.stage": "Stage",
  "workflow.pause": "Pause",
  "workflow.resume": "Resume",
  "workflow.skip": "Skip",
  "workflow.takeover": "Takeover",
  "workflow.rerun": "Rerun",
  "workflow.artifacts": "Artifacts",
  "workflow.gate": "Gate",
  "workflow.executor": "Executor",
  "workflow.library": "Workflow Library",
  "workflow.import": "Import",
  "workflow.preview": "Preview",
  "workflow.new": "New Workflow",
  "workflow.fromTaskBook": "Start from Task Book"
}
```

**i18n hook**：
```typescript
// src/features/workflow/useWorkflowI18n.ts
export function useWorkflowI18n() {
  const { t } = useTranslation('workflow');
  return {
    title: t('workflow.title'),
    stage: t('workflow.stage'),
    // ...
  };
}
```

### 7.7 a11y

| 元素 | 无障碍要求 |
|---|---|
| 阶段状态图标 | 颜色 + 图标双重指示（不纯靠颜色）：✓ 绿勾 / ● 蓝圆 / ○ 灰圆 / ✗ 红叉 |
| 操作按钮 | `aria-label` + tooltip（如"暂停当前阶段执行"） |
| 键盘导航 | Tab 切换阶段，Enter 打开详情，Space 触发操作 |
| 进度条 | `role="progressbar"` + `aria-valuenow` / `aria-valuemax` |
| 对话记录 | `role="log"` + `aria-live="polite"`（新消息自动读） |

### 7.8 前端组件清单

| 组件 | 文件路径 | 复用 |
|---|---|---|
| `WorkflowTab` | `src/features/workbench/WorkflowTab.tsx` | 新 |
| `WorkflowCard` | `src/features/workflow/WorkflowCard.tsx` | 新（参考 `PlaybookCard`） |
| `WorkflowStageDetailPanel` | `src/features/workflow/WorkflowStageDetailPanel.tsx` | 新（参考 `PlaybookStageDetail`） |
| `WorkflowLibraryPage` | `src/features/workflow/WorkflowLibraryPage.tsx` | 新（参考 `PlaybookLibraryPage`） |
| `WorkflowTaskCard` | `src/features/task-center/WorkflowTaskCard.tsx` | 新 |
| `useWorkflowI18n` | `src/features/workflow/useWorkflowI18n.ts` | 新 |

---

## 8. 后端 API 与接线清单

### 8.1 新增 API

| 端点 | 方法 | 用途 |
|---|---|---|
| `/workflow/library` | GET | 列出全局工作流库 |
| `/workflow/library/{id}` | GET | 获取单个 workflow markdown |
| `/workflow/import` | POST | 导入 workflow 到项目 |
| `/workflow/runs` | GET | 列出项目内 workflow_runs |
| `/workflow/runs/{id}` | GET | 获取 workflow_run 详情 |
| `/workflow/runs/{id}/stages/{sid}` | GET | 获取阶段详情（产物 + trace） |
| `/workflow/runs/{id}/stages/{sid}/artifacts` | GET | 获取阶段产物列表 |
| `/workflow/runs/{id}/stages/{sid}/pause` | POST | 暂停阶段 |
| `/workflow/runs/{id}/stages/{sid}/resume` | POST | 恢复阶段 |
| `/workflow/runs/{id}/stages/{sid}/rerun` | POST | 重跑阶段 |
| `/workflow/runs/{id}/stages/{sid}/skip` | POST | 跳过阶段 |
| `/workflow/runs/{id}/stages/{sid}/override-gate` | POST | 手动放行 gate |
| `/workflow/runs/{id}/stages/{sid}/takeover` | POST | 接管阶段（转 chat 模式） |
| `/workflow/runs/{id}/trace.ndjson` | GET | NDJSON 流式订阅阶段事件 |

### 8.2 缺口与修复

| 缺口 | 修复位置 | 工作量 |
|---|---|---|
| **G-playbook-spec** | `backend/services/playbook_spec.py` v1.0 → v1.1 | 中 |
| **G-workflow-loader** | 新增 `backend/services/workflow_loader.py` | 小 |
| **G-workflow-library** | 新增 `backend/services/workflow_library.py` | 小 |
| **G-workflow-runs-table** | `backend/data/database.py` 新增 `workflow_runs` 表 | 小 |
| **G-workflow-events-table** | `backend/data/database.py` 新增 `workflow_events` 表 | 小 |
| **G-artifacts-project-id** | `backend/data/database.py` `artifacts` 表加 `project_id` | 小 |
| **G-office-docs-project-id** | `backend/data/database.py` `office_documents` 表加 `project_id` | 小 |
| **G-gate-evaluator** | 新增 `backend/services/workflow_gate_eval.py` | 中 |
| **G-orch-pause-resume** | `backend/api/orch_run_control.py` 加 `pause` / `resume` 端点 | 中 |
| **G-stage-override** | `backend/api/orch_routes.py` 加 `override-gate` | 小 |
| **G-stage-skip** | `backend/api/orch_routes.py` 加 `skip` | 小 |
| **G-stage-takeover** | `backend/api/orch_routes.py` 加 `takeover` | 中 |
| **G-manifest-scan** | `backend/main.py` 启动时扫 workflow 目录 | 小 |
| **G-timeout-config** | `backend/services/playbook_spec.py` v1.1 加 `timeout` 字段 | 小 |
| **G-trace-jsonl** | 复用 chat event 流（已有） | 0（已有） |
| **G-taskcenter-7th** | `src/features/task-center/unifiedTaskModel.ts` 加 `workflow` source | 小 |
| **G-agent-hint-dynamic** | `backend/orchestration/planner.py:113-122` 改动态派发 | 中 |
| **G-orch-routes-agent-hint** | `backend/api/orch_routes.py:564-578` 改动态校验 | 小 |

### 8.3 数据库 schema

**新增表**：

```sql
-- workflow_runs（工作流运行实例）
CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    workflow_id TEXT NOT NULL,  -- 对应 workflow markdown 的 id
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL,  -- running / paused / completed / failed
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    manifest_path TEXT NOT NULL,  -- <workspace>/.sage/workflow/<run_id>/manifest.json
    orch_run_id TEXT REFERENCES orch_runs(id)  -- 关联编排运行实例
);

-- workflow_events（工作流事件埋点）
CREATE TABLE workflow_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    event_type TEXT NOT NULL,  -- stage.started / stage.completed / stage.failed / ...
    stage_id TEXT,
    payload_json TEXT,
    created_at DATETIME NOT NULL
);
```

**修改表**：

```sql
-- artifacts 表加 project_id
ALTER TABLE artifacts ADD COLUMN project_id TEXT REFERENCES projects(id);

-- office_documents 表加 project_id
ALTER TABLE office_documents ADD COLUMN project_id TEXT REFERENCES projects(id);
```

**字段格式约定**：
| 字段 | 格式 | 示例 |
|---|---|---|
| `workflow_runs.id` | `wf_` + UUID4 | `wf_9f3a1c2b-4e5d-6f70-8192-a3b4c5d6e7f8` |
| `workflow_runs.created_at` | ISO8601 UTC | `2026-11-10T14:30:00Z` |
| `workflow_events.created_at` | ISO8601 UTC | `2026-11-10T14:30:05Z` |
| `workflow_events.payload_json` | JSON 序列化字符串 | `{"stage_id":"parse","reason":"..."}` |

---

## 9. 测试策略

### 9.1 单元测试

| 模块 | 测试点 | 覆盖率目标 |
|---|---|---|
| `workflow_gate_eval` | 各种表达式（AND/OR/NOT/嵌套） | 90% |
| `workflow_loader` | markdown 解析、字段校验、v1.0 兼容 | 85% |
| `workflow_library` | 导入 / 导出 / 列表 | 80% |
| `gate_evaluator` 边界 | 空字段、非法表达式、超时 | 85% |

### 9.2 集成测试

| 场景 | 测试点 |
|---|---|
| 完整 workflow 执行 | 6 阶段串行执行，产物传递正确 |
| Gate 失败重试 | gate 失败 → AI 重试 → 通过 |
| Gate 失败超限 | 3 次重试失败 → 用户手动放行 |
| 暂停 / 恢复 | 阶段暂停 → 恢复 → 产物未丢失 |
| 跨 session 恢复 | 后端重启 → manifest 扫描 → 状态重建 |
| TaskCenter 7th source | workflow_run 在 TaskCenter 显示、实时更新 |

### 9.3 E2E 测试

| 场景 | 步骤 |
|---|---|
| 从任务书开始 | 上传任务书 → 创建 workflow → 执行 6 阶段 → 产出报告 |
| 全局库导入 | 浏览全局库 → 导入 → 创建 workflow_run |
| 阶段跳过 | 执行到阶段 3 → 跳过 → 阶段 4 启动 |

---

## 10. 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| **Gate 表达式语法复杂** | 用户写错表达式 → 阶段卡死 | 提供表达式校验 API + 前端实时检查 |
| **长任务超时** | 数值计算 24h+ → 默认 1h 超时不够 | `timeout` 字段可配置，默认 1h，长任务设 24h |
| **跨 session 恢复失败** | manifest.json 损坏 → 状态丢失 | manifest 写两份（主 + 备份），启动时校验 checksum |
| **TaskCenter 性能** | 7th source 增加查询压力 | 分页 + 缓存（TaskCenter 已有分页机制） |
| **Agent 动态派发失败** | agent_id 不存在 → lane 启动失败 | fallback 到 primary agent + 日志告警 |
| **产物路径冲突** | 多个 workflow_run 同名 → 产物覆盖 | workflow_run_id 用 UUID，保证唯一 |
| **py38 兼容** | win7 分支 Python 3.8 | gate parser 不引入新依赖；避免 PEP 604/585 注解 |

---

## 11. 实施路线图

### Phase 1（M1）：后端核心

- [ ] Playbook spec v1.1（`playbook_spec.py`）
- [ ] Workflow loader + library
- [ ] `workflow_runs` + `workflow_events` 表
- [ ] Gate evaluator
- [ ] `workflow_routes.py`（CRUD API）
- [ ] Agent 动态派发（替换 `agent_hint` 硬编码）

### Phase 2（M2）：前端入口

- [ ] 项目工作台 Tab（`WorkflowTab`）
- [ ] `WorkflowCard` + `WorkflowStageDetailPanel`
- [ ] i18n（zh/en）
- [ ] a11y（状态图标、操作按钮）

### Phase 3（M3）：阶段执行

- [ ] 阶段执行引擎（复用 `subagent_runner`）
- [ ] 产物落盘 + 传递
- [ ] Gate 校验 + 重试
- [ ] 暂停 / 恢复 / 重跑 / 跳过 API

### Phase 4（M4）：TaskCenter + 全局库

- [ ] TaskCenter 7th source（`WorkflowTaskCard`）
- [ ] 全局工作流库页面（`WorkflowLibraryPage`）
- [ ] 导入预览 + 逐项 diff

### Phase 5（M5）：对话式阶段发现

- [ ] 聊天快捷入口（"用 XX 工作流"）
- [ ] AI 引导阶段配置对话
- [ ] 阶段内对话模式（自动/确认/介入/接管）

### Phase 6（M6）：长任务 + 恢复

- [ ] Timeout 配置 + 心跳监控
- [ ] 跨 session 恢复（manifest 扫描）
- [ ] NDJSON 流式订阅（阶段 trace）

---

## 12. 参考

- Playbook spec v1.0：`backend/services/playbook_spec.py`
- Orchestration engine：`backend/orchestration/`
- TaskCenter：`src/features/task-center/`
- 用户偏好：对话驱动 + Skill-like markdown + 软/硬约束层级
- 主流 AI 应用参考：Dify / Coze / n8n / LangGraph / CrewAI / Cursor rules / Claude Code CLAUDE.md

---

**文档状态**：设计中，待用户 review  
**下一步**：用户 review → 调用 writing-plans skill → 实施
