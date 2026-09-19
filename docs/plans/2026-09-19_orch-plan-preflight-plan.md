# 编排计划前置 Round 1——需求澄清门 + 侦察先行（plan preflight）

> 日期: 2026-09-19
> 前序: coding-agent-parity round8（单 agent 计划模式）、round32（orch_tasks 用量持久化）
> 目标分支: main（合并后评估 cherry-pick 对齐 release/win7）

## 背景：复杂任务四阶段管线的断点

Sage 已具备"调研（/plan 只读模式、researcher 角色、只读子代理）→ 确认（PlanCard
确认门、ApprovalGate、QuestionGate）→ 方案（Planner DAG、结构化计划）→ 实施
（dispatch_subagents、验证环、验收）"的全部零件，但对照 Claude Code（plan mode
内置澄清 + 侦察）、ChatGPT Deep Research（动手前先反问）存在两个前端断点：

| 断点 | 现状证据 | 后果 |
| --- | --- | --- |
| 需求澄清无产品化位置 | `build_system_base()` 无全局"先澄清"指令；multi 分类门只判 single/multi；Planner 拆解从不提问 | 需求理解错了，用户只能在 PlanCard 改 goal 文本，整批返工 |
| 规划是"一次性拍脑袋" | `Planner.decompose_request(message)` 无 context、无侦察，拆解质量 = 单次 LLM 调用 | research-write 类任务拆出空架子，子代理各自瞎摸 |

本轮只做**管线前端**（澄清 + 侦察），不动执行/验收链路。

## 非目标（登记后续）

- 计划模式 × 编排打通（/plan 批准后走 multi 派发）——跨栈专项，单独成轮。
- 计划 artifact 化 + 执行期逐步对照 + 验收失败定点返工闭环（TaskPacket 激活）。
- `orch_preflight` 状态的前端可视化（本期事件已发，前端忽略未知 state，零风险）。
- OrchSettings 设置 UI 透出（round25/26 模式，本轮只落后端旋钮）。

## 批次 A：需求澄清门（clarify）

新模块 `backend/orchestration/plan_preflight.py`，producer 在
classify=multi 且非 template/非 plan_override 路径上、**decompose_request 之前**
调用 `run_plan_preflight()`：

1. 单次 LLM 调用同时做歧义判定 + 问题生成（省一次往返）：
   `{"need_clarify": bool, "questions": [{question, header, multi_select, options[2-4]}]}`，
   最多 3 问。解析失败/`need_clarify=false` → 静默跳过（判定失败绝不阻塞编排）。
2. 提问复用聊天内 ask_user_question 全套通道——**零前端改动**：
   - 向 producer 队列推 `{"state": "ask_user_question", "user_question": req.to_dict()}`
     （useChat.ts:648/1021 已有通用处理，QuestionDialog 弹出）；
   - `UserQuestionGate.request()` 挂起等待，应答经既有
     `POST /api/v1/questions/{id}/answer`（question_routes.py）回流；
   - 应答渲染复用 `render_answer_result()`；gate 未装配/超时 → 按未澄清继续，
     澄清上下文写"用户未应答，按合理默认值执行并写明假设"。

## 批次 B：侦察先行（scout）

澄清结论并入侦察目标后，构建低预算只读侦察员（复用 agent_tool 的构建方式）：

- `SageAgent(bare=True)` + `build_readonly_tool_registry()`（结构性只读：
  read_file/list_dir/web_search/web_fetch/浏览器/memory_search/calculator，
  无任何写工具，出网受 NetworkPolicy 门禁）+ 注入 settings LLM client。
- 预算：`max_iterations=4`（低于子代理默认 6）、墙钟 `asyncio.wait_for`
  （`SAGE_ORCH_SCOUT_TIMEOUT`，默认 120s）、产出截断 4000 字符。
- 产出为分点事实清单（每条一句 + 来源），作为 `scout_facts` 进 planner context。
- 不镜像 Task/Lane（发生在 run 存在之前），失败/超时静默跳过。

## 批次 C：提示词与配置

- `_PLAN_MODE_DIRECTIVE`（legacy_routes.py）：追加"目标歧义先 ask_user_question
  澄清（≤2 问）再调研；未答按合理默认并在计划中写明假设"——/plan 路径同样澄清先行。
- `build_system_base()`（profiles.py）：新增 `_CLARIFY_GUIDANCE_PROMPT` 全局规则
  （多步骤任务关键约束不明先澄清，≤2 问），插在 todo 指引之后。
- `Planner._build_decomposition_prompt`：context 含 `clarifications`（列表，标注
  "用户澄清结论（必须遵守）"）与 `scout_facts`（"侦察发现"）时以具名区块渲染，
  其余键维持原 JSON dump；指令补一条"澄清结论必须反映进任务 description"。
- 旋钮：`OrchSettings.plan_preflight_enabled` / `plan_scout_enabled`（camelCase
  `planPreflightEnabled` / `planScoutEnabled`，默认开）；env 总闸
  `SAGE_ORCH_PLAN_PREFLIGHT`（=0 关闭，测试 conftest setdefault 0）、
  `SAGE_ORCH_CLARIFY_TIMEOUT`（默认 300s）。

## 事件契约

| 事件 | 方向 | 消费方 |
| --- | --- | --- |
| `{"state": "orch_preflight", "phase": "clarify"/"scout"}` | producer → 流 | 本期前端忽略（预留 UI 挂点） |
| `{"state": "ask_user_question", "user_question": {...}}` | producer → 流 | useChat 既有 QuestionDialog |
| 应答 | 前端 → `POST /api/v1/questions/{id}/answer` | 既有 question_routes |

## 降级纪律（硬约束）

preflight 是增强不是门槛，任何一环失败都不得阻塞编排：
无 LLM 配置 / 歧义判定失败 / gate 缺失 / 提问超时 / 侦察超时或异常 →
跳过对应步骤，行为与现状完全一致（decompose_request(context=None) 等价）。
测试确定性：tests conftest `SAGE_ORCH_PLAN_PREFLIGHT=0`，存量 multi 集成测试
零感知；新行为由专用单测 + 一条 force_multi 集成测试覆盖。

## 验收

- 单测（新增 `backend/tests/unit/test_plan_preflight.py`）：澄清问答闭环、
  need_clarify=false 不提问、畸形 LLM 输出降级、gate 缺失跳过、侦察事实截断、
  总闸关闭时整体直通；planner prompt 对 clarifications/scout_facts 的渲染。
- 集成：force_multi 下 patch preflight 注入 context → 断言
  `decompose_request` 收到 `{"scout_facts": ..., "clarifications": ...}`。
- 存量：`test_chat_orchestration_stream.py` / `test_planner_llm.py` /
  `test_classify_orchestration_mode.py` 全绿。

## 实施与验证记录（2026-09-19）

交付物：
- 新增 `backend/orchestration/plan_preflight.py`（run_plan_preflight /
  _clarify / _parse_clarify_response / _scout / _run_scout_agent）；
- `legacy_routes.py`：multi 非 template 分支 decompose 前调用 preflight
  （emit=entry.queue.put），context 透传 decompose_request；
  `_PLAN_MODE_DIRECTIVE` 追加"歧义先澄清（≤2 问）"；
- `profiles.py`：新增 `_CLARIFY_GUIDANCE_PROMPT` 并入 build_system_base；
- `planner.py`：`_build_decomposition_prompt` 具名渲染
  clarifications（"用户澄清结论（必须遵守）"）/ scout_facts（"侦察发现"），
  其余 context 键维持 JSON dump，澄清存在时追加第 5 条拆解指令；
- `orch_settings.py`：`planPreflightEnabled` / `planScoutEnabled` 旋钮；
- `backend/tests/conftest.py`：`SAGE_ORCH_PLAN_PREFLIGHT=0` 默认关闭。

验证结果：
- 新增单测 18/18 通过；`test_chat_orchestration_stream.py`（含新增
  preflight context 透传集成用例）+ `test_planner_llm.py` +
  `test_classify_orchestration_mode.py` + `test_orch_settings.py` 共 42/42；
- ruff 全部改动文件 0 告警；
- 全量后端回归（xdist -n 12）：8147 passed / 68 failed / 19 errors ——
  失败子集抽样在未改动的 main 工作区（同 commit f1ee2a64d）逐例 1:1
  复现，均为本机环境问题（沙箱 git 不在 PATH、符号链接权限、并发
  资源类断言），与本轮改动无关；改动面测试零失败。

## Win7 对齐

本轮全部为后端 Python（py3.8 兼容写法：`asyncio.TimeoutError` 捕获口径、
禁 `X | Y` 运行时注解），无前端改动，合并后可直接 cherry-pick。
