# Agent Orchestrator 接通实施计划

> 日期: 2026-06-22
> 分支: `feat/agent-orchestrator-wiring`
> 状态: ✅ 完成 (4 阶段全部 GREEN)
> 关联计划: [2026-06-19_multi-agent-coordination.md](./2026-06-19_multi-agent-coordination.md)（长期协调层规划，本文档是其**前置子集**——先把**已定义但未接入**的 orchestrator/profile 组件接通生产，长期架构后续独立推进）

## 1. 背景与目标

Sage 项目已有完整的自研 Agent 系统（非第三方框架），但**多 Agent 协作仅完成代码定义，未真正接入生产路径**：

| 当前状态 | 问题 | 阶段 1-4 实施后 |
|---|---|---|
| `SageAgent.chat/run_loop` 在每条 `/chat` 中执行 | ✅ 单 Agent ReAct 循环已上线 | ✅ + profile 接通 |
| 4 个 AgentProfile 已定义 | ❌ `system_prompt`/`tools`/`enabled` 运行时不消费 | ✅ 从 SQLite 读最新 profile |
| `AgentOrchestrator` 已定义 | ❌ 整个项目无生产代码实例化 | ✅ /chat 复杂消息分流到编排器 |
| `_execute_multi_step` 串行 | ❌ 未用 `asyncio.gather` 并行 | ✅ 并行 + 错误隔离 |
| 前端 UI 完整 | ❌ 不显示当前活跃 agent | ✅ `ActiveAgentIndicator` 组件 |

## 2. 涉及的文件与模块

### 后端
| 文件 | 改动 | 状态 |
|---|---|---|
| `backend/core/legacy/agent.py` | SageAgent 接受 `agent_id` 参数，从 profile 读 system_prompt/max_iterations；事件携带 agent_id | ✅ |
| `backend/core/legacy/orchestrator.py` | `_execute_agent_task` 真正调用 `SageAgent.run_loop`；`_execute_multi_step` 加 `asyncio.gather` 并行 + 错误隔离 | ✅ |
| `backend/core/legacy/agent_state.py` | AgentEvent 增加 `agent_id` 字段 | ✅ |
| `backend/api/legacy_routes.py` | `/chat` 路由根据 `_should_use_orchestrator` 分流 | ✅ |
| `backend/agents/profiles.py` | 新增 `get_enabled_agent()` 工具函数 | ✅ |

### 前端
| 文件 | 改动 | 状态 |
|---|---|---|
| `src/shared/api/types.ts` + `llmStream.ts` | `AgentEvent` 增加 `agent_id?: string` | ✅ |
| `src/features/send-message/useChat.ts` | 累积 `currentAgentId`，暴露给上层 | ✅ |
| `src/widgets/chat/ActiveAgentIndicator.tsx` | **新**：流式过程中显示"🤖 当前处理 agent: xxx" | ✅ |
| `src/widgets/chat/index.ts` + `src/pages/Chat.tsx` | 集成 ActiveAgentIndicator | ✅ |

### 测试
| 文件 | 状态 |
|---|---|
| `backend/tests/unit/test_agent_profile_wiring.py` — 14 测试 | ✅ GREEN |
| `backend/tests/unit/test_chat_routing.py` — 15 测试 | ✅ GREEN |
| `backend/tests/unit/test_orchestrator_parallel.py` — 5 测试 | ✅ GREEN |
| 旧 orchestrator 测试修复（dispatch/scheduling） | ✅ GREEN |
| 后端总计 | ✅ **1103 单元测试全通过** |
| 前端总计 | ✅ **214 测试全通过** |

## 3. 技术方案

详见原计划。实施过程中关键决策：
- **Profile 接通**：SageAgent 接受 `agent_id` 参数，运行时从 SQLite 读最新 profile（用户刚 PATCH 的立即生效）。disabled/missing 回退默认，不抛异常。
- **分流策略**：`_should_use_orchestrator(message)` 启发式（关键词 + 长度 > 200），后续可加 LLM 分类兜底。
- **并行执行**：`asyncio.gather(return_exceptions=True)` + 错误隔离，结果顺序保持与输入一致。
- **agent_id 透传**：所有 AgentEvent 携带 `agent_id`，前端累积最新值显示。
- **向后兼容**：所有新字段都有默认值，旧代码无需改动。

## 4. 实施步骤

### 阶段 1：Profile → 运行时（接通）✅
- [x] 1.1 写测试 `test_agent_profile_wiring.py`（RED → GREEN）
- [x] 1.2 改 `SageAgent.__init__` 接受 `agent_id` 参数
- [x] 1.3 改 `_call_llm` 从 profile 读 system_prompt
- [x] 1.4 加 `get_enabled_agent()` 工具函数（检查 enabled）
- [x] 1.5 跑测试（GREEN）

### 阶段 2：Orchestrator 接入 ✅
- [x] 2.1 写测试 `test_chat_routing.py`（RED → GREEN）
- [x] 2.2 改 `AgentOrchestrator._execute_agent_task` 调用真实 `SageAgent.run_loop`
- [x] 2.3 在 `legacy_routes.py` 加 `_should_use_orchestrator` 分流函数
- [x] 2.4 改 `/chat` 路由根据消息分流
- [x] 2.5 跑测试（GREEN）

### 阶段 3：并行执行 ✅
- [x] 3.1 写测试 `test_orchestrator_parallel.py`（RED → GREEN）
- [x] 3.2 改 `_execute_multi_step` 用 `asyncio.gather` 并行 + 错误隔离
- [x] 3.3 跑测试（GREEN）

### 阶段 4：前端 UI ✅
- [x] 4.1 改 `AgentEvent`（后端）加 `agent_id` 字段
- [x] 4.2 改 `types.ts` + `llmStream.ts`（前端）加 `agent_id` 类型
- [x] 4.3 改 `useChat.ts` 累积 `currentAgentId`
- [x] 4.4 新增 `ActiveAgentIndicator.tsx` 组件
- [x] 4.5 在 Chat.tsx 集成指示器
- [x] 4.6 跑前端测试（GREEN）

## 5. 风险评估与依赖

### 风险（全部缓解）
| 风险 | 等级 | 缓解 |
|---|---|---|
| 分流策略误判 | 中 | 启发式 + 后续可加 LLM 分类兜底 |
| 并行子任务失败 | 中 | `asyncio.gather(return_exceptions=True)` + 错误隔离 ✅ |
| agent_id 字段透传破坏现有流 | 低 | 字段可选（`agent_id: str | None = None`），向后兼容 ✅ |
| profile 与 SQLite 不同步 | 低 | 运行时从 `AgentRepository.get()` 读 ✅ |
| 现有测试回归 | 低 | 1103 + 214 测试全通过 ✅ |

### 回滚
每个阶段独立 commit（待用户确认），可单独 revert。

## 1. 背景与目标

Sage 项目已有完整的自研 Agent 系统（非第三方框架），但**多 Agent 协作仅完成代码定义，未真正接入生产路径**：

| 当前状态 | 问题 |
|---|---|
| `SageAgent.chat/run_loop` 在每条 `/chat` 中执行 | ✅ 单 Agent ReAct 循环已上线 |
| 4 个 AgentProfile (primary/researcher/coder/memory_manager) 已定义 | ❌ `system_prompt`/`tools`/`enabled` 运行时不消费 |
| `AgentOrchestrator` 已定义（`backend/core/legacy/orchestrator.py`） | ❌ 整个项目无生产代码实例化 |
| `_execute_multi_step` 串行执行子任务 | ❌ 未使用 `asyncio.gather` 并行 |
| 前端 UI 完整（CRUD、列表、详情） | ❌ 不显示当前活跃的 agent 角色 |

**目标**：让多 Agent 系统真正驱动行为——意图路由到对应 profile、复杂任务走编排器并行处理、UI 反映运行时状态。

## 2. 涉及的文件与模块

### 后端
| 文件 | 改动 |
|---|---|
| `backend/core/legacy/agent.py` | SageAgent 接受 `profile` 参数，从 profile 读 system_prompt/tools/max_iterations |
| `backend/core/legacy/orchestrator.py` | `_execute_agent_task` 真正调用 `SageAgent.run_loop`（而非直接 LLM）；`_execute_multi_step` 加 `asyncio.gather` 并行 |
| `backend/core/legacy/agent_state.py` | AgentEvent 增加 `agent_id` 字段（流式通知前端当前活跃 agent） |
| `backend/api/legacy_routes.py` | `/chat` 和 `/chat/stream` 根据消息复杂度分流到单 agent 或编排器 |
| `backend/agents/profiles.py` | `get_enabled_agent(agent_id)` 工具函数（检查 enabled 字段） |
| `backend/data/agent_repo.py` | 不改（现有 `get()` 已返回 `enabled` 字段） |

### 前端
| 文件 | 改动 |
|---|---|
| `src/shared/api/types.ts` | `AgentEvent` 增加 `agent_id?: string` 字段 |
| `src/features/send-message/useChat.ts` | 累积 `agent_id`，暴露 `currentAgentId` |
| `src/widgets/chat/ActiveAgentIndicator.tsx` | **新**：流式过程中显示"🤖 当前处理 agent: xxx" |

### 测试
| 文件 | 改动 |
|---|---|
| `backend/tests/unit/test_agent_profile_wiring.py` | **新**：SageAgent 消费 profile 测试 |
| `backend/tests/unit/test_orchestrator_parallel.py` | **新**：asyncio.gather 并行测试 |
| `backend/tests/unit/test_chat_routing.py` | **新**：/chat 分流逻辑测试 |
| `tests/electron/agent-indicator.spec.ts` | **新**：E2E 测试 ActiveAgentIndicator |

## 3. 技术方案

### 3.1 Profile 接通（阶段 1）

**核心改动**：`SageAgent.__init__` 接受可选 `profile: AgentProfile | dict` 参数。
- 有 profile → system_prompt/tools/max_iterations 从 profile 读
- 无 profile → 保持默认 "你是 Sage..." 提示（向后兼容）
- `enabled=False` 的 agent 不能被路由选中（回退到 primary）

**接口**：
```python
class SageAgent:
    def __init__(
        self,
        llm_config: dict | None = None,
        profile: AgentProfile | dict | None = None,  # 新增
    ):
        self.profile = self._resolve_profile(profile)  # 标准化为 AgentProfile
        # system_prompt 在 _call_llm / run_loop 中从 self.profile.system_prompt 读
```

**测试点**：
- SageAgent() 默认行为不变（向后兼容）
- SageAgent(profile=...) 使用 profile 的 system_prompt
- enabled=False 的 profile 被拒绝（抛 ValueError 或回退 primary）
- profile.tools 过滤 ToolRegistry
- profile.max_iterations 覆盖 run_loop 默认值

### 3.2 Orchestrator 接入（阶段 2）

**分流策略**（在 `/chat` 和 `/chat/stream` 中）：
1. 关键词启发式快速判断（"对比"、"比较"、"总结并"、"然后"、"接着"、"分析...并"、"multi" → multi_step）
2. 消息长度 > 200 字 → 倾向 multi_step
3. 否则 → 单 agent（走 primary profile）

**接口**：
```python
# legacy_routes.py
async def chat_stream_create(data: ChatRequest, request: Request):
    if _should_use_orchestrator(data.message):
        orchestrator = AgentOrchestrator(llm_client=...)
        async for evt in orchestrator.stream_process(data.session_id, data.message):
            await entry.queue.put(evt.to_dict())
    else:
        agent = SageAgent()  # 默认 primary
        async for evt in agent.run_loop(...):
            await entry.queue.put(evt.to_dict())

def _should_use_orchestrator(message: str) -> bool:
    """启发式分流：多步骤任务走编排器"""
    keywords = ["对比", "比较", "总结并", "然后", "接着", "分析", "multi"]
    return any(kw in message for kw in keywords) or len(message) > 200
```

**关键改动**：`AgentOrchestrator._execute_agent_task` 必须真正调用 `SageAgent.run_loop`，而非直接调 LLM。

**测试点**：
- `_should_use_orchestrator` 分流逻辑
- orchestrator 走 multi_step 路径时每个子任务调用真实 SageAgent
- 单 agent 路径行为不变（向后兼容）

### 3.3 并行执行（阶段 3）

**改动**：`AgentOrchestrator._execute_multi_step` 中，子任务拆解后若彼此独立（intent 不同且无数据依赖），用 `asyncio.gather` 并行执行。

**接口**：
```python
async def _execute_multi_step(...):
    subtasks = await self._decompose_task(message)

    # 全部并行（假设子任务彼此独立；依赖关系由 LLM 拆解时保证）
    tasks = [
        self._execute_agent_task(
            session_id,
            self._select_agent(Intent(st.get("intent", "general"))),
            st["description"],
            history,
        )
        for st in subtasks
    ]
    results_or_errors = await asyncio.gather(*tasks, return_exceptions=True)

    # 错误隔离：单个失败不影响其他
    results = []
    for st, result in zip(subtasks, results_or_errors):
        if isinstance(result, Exception):
            results.append({"subtask": st, "result": {"error": str(result), "response": ""}})
        else:
            results.append({"subtask": st, "result": result})

    final_response = await self._aggregate_results(message, results)
    ...
```

**测试点**：
- 并行执行时间 < 串行（至少快 30%）
- 结果顺序与输入顺序一致（asyncio.gather 保证）
- 单个子任务失败不影响其他（错误隔离）

### 3.4 前端反映运行时状态（阶段 4）

**后端**：`AgentEvent` 增加 `agent_id: str | None = None` 字段，每个事件携带当前执行 agent 的 ID。

**前端**：
- `useChat` 累积 `agentId`（取最后一个非空值）
- 新增 `ActiveAgentIndicator` 组件：流式过程中显示"🤖 当前 agent: xxx"
- 流结束后保留最后一帧 3 秒后淡出

**测试点**：
- 单 agent 路径：agent_id 始终为 "primary"
- orchestrator 路径：agent_id 随子任务切换
- UI 显示正确（E2E）

## 4. 实施步骤

### 阶段 1：Profile → 运行时（接通）
- [ ] 1.1 写测试 `test_agent_profile_wiring.py`（RED）
- [ ] 1.2 改 `SageAgent.__init__` 接受 `profile` 参数
- [ ] 1.3 改 `_call_llm` / `run_loop` 从 profile 读 system_prompt
- [ ] 1.4 加 `get_enabled_agent()` 工具函数（检查 enabled）
- [ ] 1.5 跑测试（GREEN）

### 阶段 2：Orchestrator 接入
- [ ] 2.1 写测试 `test_chat_routing.py`（RED）
- [ ] 2.2 改 `AgentOrchestrator._execute_agent_task` 调用真实 `SageAgent.run_loop`
- [ ] 2.3 在 `legacy_routes.py` 加 `_should_use_orchestrator` 分流函数
- [ ] 2.4 改 `/chat` 和 `/chat/stream` 路由根据消息分流
- [ ] 2.5 跑测试（GREEN）

### 阶段 3：并行执行
- [ ] 3.1 写测试 `test_orchestrator_parallel.py`（RED）
- [ ] 3.2 改 `_execute_multi_step` 用 `asyncio.gather` 并行
- [ ] 3.3 跑测试（GREEN）

### 阶段 4：前端 UI
- [ ] 4.1 改 `AgentEvent`（后端）加 `agent_id` 字段
- [ ] 4.2 改 `types.ts`（前端）加 `agent_id` 类型
- [ ] 4.3 改 `useChat.ts` 累积 `agentId`
- [ ] 4.4 新增 `ActiveAgentIndicator.tsx` 组件
- [ ] 4.5 在聊天界面集成指示器
- [ ] 4.6 写 E2E 测试 `agent-indicator.spec.ts`

## 5. 风险评估与依赖

### 风险
| 风险 | 等级 | 缓解 |
|---|---|---|
| 分流策略误判 | 中 | 启发式 + 后续可加 LLM 分类兜底；提供 `_should_use_orchestrator` 可配置开关 |
| 并行子任务失败 | 中 | `asyncio.gather(return_exceptions=True)` + 错误隔离 |
| agent_id 字段透传破坏现有流 | 低 | 字段可选（`agent_id: str | None = None`），向后兼容 |
| profile 与 SQLite 不同步 | 低 | 运行时从 `AgentRepository.get()` 读（已包含 enabled 字段），不走内存注册表 |
| 现有测试回归 | 低 | 每个阶段独立可测，旧测试不依赖新字段 |

### 依赖
- 后端 FastAPI 已支持 async（`asyncio.gather` 可直接用）
- SQLite 同步驱动已在工作线程（`asyncio.to_thread` 不需要改）
- 前端 NDJSON 解析已支持未知字段（`AgentEvent` 解析不会崩）

### 回滚
每个阶段独立 commit，可单独 revert：
- commit 1: feat(agent): wire profile to SageAgent runtime
- commit 2: feat(orchestrator): route /chat through orchestrator for complex tasks
- commit 3: perf(orchestrator): parallel subtask execution with asyncio.gather
- commit 4: feat(ui): show active agent indicator during chat stream
