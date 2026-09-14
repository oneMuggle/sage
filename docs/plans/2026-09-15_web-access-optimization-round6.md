# 网页访问能力优化 Round 6：子代理浏览器授权（B2 落地）（2026-09-15）

- **状态**：方案完成，实施中
- **上游文档**：Round 1-4（#742/#748、#756/#759、#763/#765、#769）；Round 5 方案 §2.3 的 A1 勘察结论（B2 无审批死锁，需独立契约轮——即本方案）；Round 5 同名批次已由并行会话落地（d445d7bf/fb6f25c5/6ee8e6cd，本方案与其无文件交集）
- **范围**：main 与 release/win7 双分支（后端 only）
- **编号约定**：A = 子代理授权
- **方法**：基于 agent_tool / profiles / permission_gate / registry 勘察（附 `file:line`）

## 0. 结论速览

委派子代理（`agent` 工具的 sub-agent）目前只有只读工具（文件读/目录列/web 搜索抓取/记忆/计算器，agent_tool.py:193-215 显式注册）。研究类委派中"需要登录态/需要交互的动态页面"场景到不了浏览器通道——Round 1 已交付 browser 工具组与持久 profile，缺的只是把浏览器工具接入子代理注册表与 researcher profile。

**勘察结论（Round 5 §2.3 已记录，本轮落地）**：
- 审批流 `ApprovalGate.request`（Future）+ GUI 按 `request_id` 应答，超时 default-deny（permission_gate.py:323-347）——与调用方是否为子代理无关，**无审批死锁**。
- 子代理工具与主代理共用同一注册表/权限边界（registry 收集 risk 供权限引擎，registry.py:28-50）。
- 子代理策略 `subagent_only=True` + 独立 scratch 工作区（agent_tool.py:175-190）——browser 工具的工作区落盘（截图/下载）自动隔离在 scratch 内，随运行清理。

## 1. 差距与证据

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| A1 | 委派子代理注册表无浏览器工具 | agent_tool.py:204-214（仅 7 个只读工具） | **P1** |
| A2 | SUBAGENT_TOOL_WHITELIST 契约清单不含浏览器 | agent_tool.py:89-97 | **P1** |
| A3 | 子代理系统提示词与 agent 工具描述未提浏览器通道 | agent_tool.py:151-153、:253 | **P1** |
| A4 | researcher profile 工具清单无浏览器 | profiles.py:185 | **P1** |

## 2. 方案设计

### 2.1 A1+A2 委派注册表与契约清单

`build_readonly_tool_registry`（agent_tool.py:193）注册浏览器工具组：

- **无条件注册**：`browser_launch`（EXEC）/ `browser_snapshot`（READ）/ `browser_interact`（WRITE_LOCAL）/ `browser_cookies`（WRITE_LOCAL）/ `browser_close`（WRITE_LOCAL）——均为本地操作，风险类审批照常生效。
- **条件注册**：`browser_navigate`（EXTERNAL）——与 web_fetch 同口径，`network_policy.fetch_enabled()` 为真才注册（OFFLINE 模式不暴露出网导航）。
- `browser_screenshot` 不注册（研究委派无需截图落盘，少一个工作区写面）。
- `SUBAGENT_TOOL_WHITELIST` 清单同步加入上述 6 个浏览器工具名（该常量为契约文档 + 测试锚点）。

### 2.2 A3 文案契约

- `SUBAGENT_SYSTEM_PROMPT`：READ-ONLY 表述更新为"只读工具 + 受控浏览器通道"——明确浏览器访问同样受审批与网络模式门禁约束。
- `AgentTool._build_schema` description（:253 附近）：同步提及浏览器通道。

### 2.3 A4 researcher profile

`profiles.py` researcher `tools` 追加 6 个浏览器工具名（与 2.1 一致）。legacy agent 路径经 `profile["tools"]` → `allowed_tools` 生效（core/legacy/agent.py:1776-1783）。

## 3. 双分支实施策略

| 文件 | 两分支状态 | 冲突预测 |
| --- | --- | --- |
| backend/tools/agent_tool.py | 同源 | 零冲突 |
| backend/agents/profiles.py | **已知漂移**（win7 researcher 多 memory_save，注释差异） | cherry 手工对位（Round 1 已演练） |
| backend/tests/unit/test_agent_tool.py | 同源 | 零冲突 |

py3.8 纪律 + 零新依赖不变。并行会话的 web-access 批次集中在 browser_tool/web_tool 内部（头拟真/重试限速），与本方案的 agent_tool/profiles 无交集。

## 4. 实施批次

| 批次 | 内容 | 工作量 |
| --- | --- | --- |
| 批次 1 | A1+A2+A3（agent_tool）+ A4（profiles）+ 单测 | 1 天 |
| 收尾 | cherry(win7) + profiles 手工对位 + 测试 | 0.5 天 |

## 5. 测试与验收

- `test_agent_tool.py` 扩展：子代理注册表含 6 个浏览器工具、navigate 受 fetch_enabled 门禁（OFFLINE 不注册）、白名单清单断言、描述文案含浏览器语义。
- `test_profiles_*` 扩展：researcher 工具清单断言更新（含浏览器工具与 win7 的 memory_save 差异按分支各自锁定）。
- 验收：interactive 模式下委派"打开某页面并摘要"任务 → 子代理内 browser_navigate 触发 GUI 审批 → 批准后返回页面正文。

## 6. 安全口径与已知限制

- **只读契约的边界变更明示**：子代理从此可启动受控浏览器进程（EXEC）并发起出网导航（EXTERNAL）——两者均走既有风险审批（interactive 逐次询问、read-only 模式直接拒绝），网络模式门禁照常约束 navigate；浏览器进程使用临时/持久 profile + scratch 工作区，不接触主工作区。
- 白名单契约变更同步更新模块 docstring 与工具描述，保持"结构上不可用"（未注册即不可见）的既有安全模型。
- 已知限制：子代理运行期间审批提示与主代理审批共用 GUI 队列，审批超时 default-deny 会使子代理的浏览器步骤失败（模型可见错误，可转主代理处理）；`browser_screenshot` 未授权给子代理（截图无研究价值且有工作区写面）。
