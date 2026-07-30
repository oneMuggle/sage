# Sage 项目综合优化方案(最终版)

> **状态:** 计划(待启动)
> **日期:** 2026-07-30
> **作者:** code-explorer + planner
> **目标分支:** `main`(release/win7 按需 cherry-pick)
> **参考项目:**
> - `/home/fz/project/openworker` — Andrew Ng 团队的 AI coworker 桌面应用
> - `/home/fz/project/LLM_Simple` — 早期 PyQt5 桌面 AI Agent 工具包(v3.0)
> - `/home/fz/project/pi` — 终端编码代理工具(工程化标杆)

---

## 0. TL;DR

基于对 Sage、OpenWorker、LLM_Simple、pi 四个项目的深度对比分析,提炼出 **50 项可落地优化**(OpenWorker 27 项 + LLM_Simple 11 项 + pi 12 项),按 ROI 分 4 个阶段执行。

### 核心结论

| 维度 | Sage 现状 | 借鉴方向 | 来源 |
|---|---|---|---|
| **架构严谨性** | ✅ 六边形 + FSD(领先) | 保持 | — |
| **文档体系** | ✅ 100+ markdown(领先) | 保持 | — |
| **主题系统** | ✅ 140+ token + 11 主题(领先) | 补 pre-paint + 语义阶梯 | OpenWorker |
| **Agent 事件流** | ⚠️ 缺乏标准化 | 发布-订阅模式 + steering 队列 | **pi** |
| **工具权限** | ⚠️ 硬编码 | 数据驱动 RiskClass | OpenWorker |
| **LLM Provider** | ⚠️ 抽象不足 | 30+ Provider 统一抽象 | OpenWorker + **pi** |
| **上下文压缩** | ❌ 缺乏智能压缩 | 三层压缩 + 错误感知 + 分支摘要 | **LLM_Simple** + **pi** |
| **质量中间件** | ❌ 缺乏 | NudgeGuard + CircuitBreaker | **LLM_Simple** |
| **会话模型** | 线性 | 树结构分支(Branching) | **pi** |
| **共享 UI primitives** | ❌ 只有 4 个 | 补齐 ~15 个 Radix primitives | OpenWorker |
| **工具安全验证** | ⚠️ 有策略但无 AST | AST 白名单验证 | **LLM_Simple** |
| **Code Diff** | ⚠️ Office 有但通用缺 | write/edit diff 可视化 | **LLM_Simple** |
| **测试策略** | ⚠️ 依赖真实 API | Faux Provider + 回归测试绑定 issue | **pi** |
| **文件修改** | ⚠️ 可能并发冲突 | 队列串行化(file-mutation-queue) | **pi** |
| **工具执行钩子** | ❌ 缺乏 | beforeToolCall/afterToolCall | **pi** |
| **错误边界** | ❌ 单根 | 分层隔离 | OpenWorker |
| **E2E 测试** | ❌ 依赖网络 + 3 目录 | Hermetic + 合并 | OpenWorker |
| **Agent 模式** | ❌ Always-on | Suspend-resume | OpenWorker |
| **布局** | 2 列 | 3 列(right rail) | OpenWorker |
| **供应链安全** | ⚠️ 基础 | 精确版本 + shrinkwrap + 生命周期白名单 | **pi** |

### 阶段规划

| 阶段 | 周期 | 项目数 | 来源分布 | 收益 |
|---|---|---|---|---|
| **Phase 0 清理速赢** | 1 周 | 8 项 | OpenWorker 6 + LLM_Simple 1 + pi 1 | 体感立即提升 |
| **Phase 1 基建升级** | 2-4 周 | 12 项 | OpenWorker 7 + LLM_Simple 2 + pi 3 | 开发效率 ×2 |
| **Phase 2 架构升级** | 1-2 月 | 18 项 | OpenWorker 8 + LLM_Simple 5 + pi 5 | 产品气质升级 |
| **Phase 3 重大特性** | 2+ 月 | 12 项 | OpenWorker 6 + LLM_Simple 3 + pi 3 | 差异化竞争力 |

---

## 1. 背景与目标

### 1.1 参考项目简介

#### OpenWorker(https://github.com/andrewyng/openworker)

Andrew Ng 团队开源的 AI coworker 桌面应用,产品定位"完成可交付物"而非"对话"。技术栈:Tauri 2 + React 18 + Python FastAPI + aisuite + whisper-rs。

**亮点**:
- 数据驱动的工具风险/权限体系(`RiskClass`)
- Provider 抽象 + Token 归一化(`ProviderRouter` + cache 分片)
- Hermetic E2E(60+ 完全脱网 Playwright spec)
- Agent suspend-resume(`selfwake.py`)
- Persona 声明式 Markdown manifest
- 手写但统一的 UI 模式(hover-peek sidebar / right rail / ⌘1-9 jump)

#### LLM_Simple(本地项目)

早期 PyQt5 桌面 AI Agent 工具包(v3.0),零重依赖架构。技术栈:PyQt5 + raw `requests`(替代 openai SDK) + PyInstaller。

**亮点**:
- 三层上下文压缩(MicroCompact → Sliding Window → LLM Summary)
- 错误感知截断(保留错误诊断上下文)
- 可插拔质量中间件(NudgeGuard / CircuitBreaker)
- AST 工具安全验证(用户工具白名单)
- Code Diff 可视化 + 持久化
- 修改后自动语法检查

#### pi(https://pi.dev)

终端编码代理工具,工程化程度极高。技术栈:TypeScript 5.9.3 + Node.js ≥ 22 + tsgo 编译器 + 自研 TUI 库。

**亮点**:
- Agent 事件发布-订阅架构(agent_start/turn_start/message_start 等)
- 会话分支(Branching)树结构,支持多路径探索
- 30+ LLM Provider 统一抽象 + Faux Provider 测试
- 文件修改队列串行化(file-mutation-queue.ts)
- 工具执行钩子(beforeToolCall/afterToolCall)
- 供应链硬化(精确版本 + shrinkwrap + 生命周期白名单)
- 70+ 扩展示例,无 fork 定制

---

## 2. 三项目对比分析

### 2.1 四项目特性矩阵

| 特性 | Sage | OpenWorker | LLM_Simple | pi | 借鉴方向 |
|---|---|---|---|---|---|
| **架构** | 六边形 + FSD | 分层 MVC | 分层 MVC | 分层 Monorepo | 保持 Sage |
| **Agent 事件** | — | — | — | ✅ 发布-订阅 | ✅ **pi** |
| **工具权限** | 硬编码 | RiskClass 数据驱动 | AST 白名单 | 扩展钩子 | ✅ 两者都借鉴 |
| **上下文管理** | ChromaDB 向量 | — | 三层压缩 + 错误感知 | 分支摘要式 compaction | ✅ **LLM_Simple** + **pi** |
| **质量守卫** | — | — | NudgeGuard + CircuitBreaker | — | ✅ **LLM_Simple** |
| **会话模型** | 线性 | 线性 | 文件夹级 | ✅ 树结构分支 | ✅ **pi** |
| **LLM Provider** | httpx | ProviderRouter | raw requests | ✅ 30+ 统一抽象 | ✅ OpenWorker + **pi** |
| **UI primitives** | 4 个 | 0 个(手写) | PyQt5 widgets | 自研 TUI | ✅ OpenWorker(走 Radix) |
| **布局** | 2 列 | 3 列 | 2 列 + sidebar | 终端 TUI | ✅ OpenWorker |
| **E2E 测试** | 依赖网络 | Hermetic | — | tmux 集成测试 | ✅ OpenWorker |
| **测试策略** | 真实 API | 真实 API | 真实 API | ✅ Faux Provider | ✅ **pi** |
| **文件修改** | 可能并发 | — | — | ✅ 队列串行化 | ✅ **pi** |
| **工具钩子** | — | — | — | ✅ before/after | ✅ **pi** |
| **Code Diff** | Office 有 | — | ✅ 通用 diff | ✅ edit-diff.ts | ✅ **LLM_Simple** + **pi** |
| **Syntax Check** | — | — | ✅ 修改后自动 | — | ✅ **LLM_Simple** |
| **供应链安全** | 基础 | 基础 | 基础 | ✅ 精确版本 + shrinkwrap | ✅ **pi** |
| **Skill Auto** | 显式调用 | — | ✅ when_to_use | 扩展系统 | ✅ **LLM_Simple** + **pi** |

### 2.2 各项目优势(保持)

| 项目 | 优势 | Sage 态度 |
|---|---|---|
| **Sage** | 六边形 + FSD、140+ token 主题、typed i18n、@xyflow 知识图谱、Win7 LTS | 保持 |
| **OpenWorker** | Provider 抽象、Hermetic E2E、UI 模式统一、Persona manifest | 借鉴 |
| **LLM_Simple** | 三层压缩、质量中间件、AST 安全、Code Diff、Auto Syntax Check | 借鉴 |
| **pi** | Agent 事件流、会话分支、Faux Provider、文件修改队列、供应链硬化 | 借鉴 |

---

## 3. 优化项清单(50 项,标注来源)

### 架构层(30 项)

| # | 优化项 | 来源 | 优先级 | 工作量 |
|---|---|---|---|---|
| A1 | 工具权限数据化(RiskClass) | OpenWorker | Must | 1 周 |
| A2 | LLM Provider 抽象 + Token 归一化 | OpenWorker | Must | 1-2 周 |
| A3 | Hermetic E2E 测试 | OpenWorker | Should | 2-3 周 |
| A4 | Agent Suspend-Resume | OpenWorker | Could | 2-3 周 |
| A5 | Persona 声明式 Manifest | OpenWorker | Should | 1 周 |
| A6 | 工具并发执行 | OpenWorker | Could | 3-5 天 |
| A7 | Shell 操作符检测 | OpenWorker | Should | 1-2 天 |
| A8 | Release 稳定文件名 | OpenWorker | Should | 1-2 天 |
| A9 | 清理 Tauri 残留 | OpenWorker | Must | 半天 |
| A10 | UI Mocks In-Repo | OpenWorker | Could | 持续 |
| A11 | 本地 STT Sidecar | OpenWorker | Could | 1-2 月 |
| **A12** | **三层上下文压缩 + 错误感知截断** | **LLM_Simple** | **Must** | **1 周** |
| **A13** | **Quality Middleware(NudgeGuard + CircuitBreaker)** | **LLM_Simple** | **Must** | **3-5 天** |
| **A14** | **AST 工具安全验证** | **LLM_Simple** | **Should** | **2-3 天** |
| **A15** | **Auto Syntax Check** | **LLM_Simple** | **Should** | **1-2 天** |
| **A16** | **Skill Auto-Activation** | **LLM_Simple** | **Could** | **2-3 天** |
| **A17** | **ContextSnapshot(可恢复 session)** | **LLM_Simple** | **Could** | **1 周** |
| **A18** | **Tool Chain Tracking(实时可视化)** | **LLM_Simple** | **Could** | **1 周** |
| A19 | RiskOverride 用户级权限覆盖 | OpenWorker | Should | 3-5 天 |
| A20 | ProviderRouter model name 路由 | OpenWorker | Must | 包含在 A2 |
| A21 | TokenUsage cache 分片归一化 | OpenWorker | Must | 包含在 A2 |
| A22 | Permission Mode(DISCUSS/PLAN/INTERACTIVE/AUTO) | OpenWorker | Must | 包含在 A1 |
| **A23** | **Agent 事件发布-订阅架构** | **pi** | **Must** | **1 周** |
| **A24** | **会话分支(Branching)树结构** | **pi** | **Should** | **2 周** |
| **A25** | **Faux Provider 测试策略** | **pi** | **Should** | **3-5 天** |
| **A26** | **文件修改队列串行化** | **pi** | **Should** | **2-3 天** |
| **A27** | **工具执行钩子(before/after)** | **pi** | **Should** | **2-3 天** |
| **A28** | **分支摘要式 Compaction** | **pi** | **Could** | **1 周** |
| **A29** | **回归测试与 issue 编号绑定** | **pi** | **Should** | **1-2 天** |
| **A30** | **供应链硬化(精确版本 + shrinkwrap)** | **pi** | **Could** | **3-5 天** |

### UI 层(20 项)

| # | 优化项 | 来源 | 优先级 | 工作量 |
|---|---|---|---|---|
| U1 | Pre-Paint Theme Script | OpenWorker | Must | 2 小时 |
| U2 | Hover-Peek Sidebar | OpenWorker | Should | 2-3 天 |
| U3 | Semantic Color Ladder | OpenWorker | Must | 1 天 |
| U4 | 补齐 Shared UI Primitives | OpenWorker | Must | 2 周 |
| U5 | 错误边界分层 | OpenWorker | Must | 半天 |
| U6 | Command Palette ⌘1-9 | OpenWorker | Should | 1-2 天 |
| U7 | Right Rail(Artifacts + Progress) | OpenWorker | Should | 2-3 周 |
| U8 | Humanized Tool Titles | OpenWorker | Should | 1-2 天 |
| U9 | Live-Dot vs Attention-Badge | OpenWorker | Could | 1 周 |
| U10 | Sticky-Unlock Chips | OpenWorker | Could | 3-5 天 |
| U11 | Drained Toast | OpenWorker | Could | 2-3 天 |
| U12 | Two-Step Delete in Menu | OpenWorker | Could | 1-2 天 |
| U13 | Per-Session Draft Persistence | OpenWorker | Must | 半天 |
| U14 | Voice Dictation UI | OpenWorker | Could | 1-2 月 |
| U15 | Settings 重构 left-nav | OpenWorker | Should | 3-5 天 |
| U16 | EmptyState Shared Component | OpenWorker | Must | 半天 |
| **U17** | **Code Diff Visualization** | **LLM_Simple** | **Should** | **3-5 天** |
| **U18** | **HTML 会话导出** | **pi** | **Should** | **3-5 天** |
| **U19** | **会话树可视化** | **pi** | **Could** | **1 周** |
| **U20** | **Emacs 风格键盘绑定** | **pi** | **Could** | **2-3 天** |

---

## 4. 实施阶段(最终版)

### Phase 0: 清理与速赢(1 周)

| # | 项 | 来源 | 工作量 | 收益 |
|---|---|---|---|---|
| A9 | 清理 Tauri 残留 | OpenWorker | 半天 | 减少困惑 |
| U1 | Pre-paint theme script | OpenWorker | 2 小时 | 主题无闪烁 |
| U3 | Semantic color ladder | OpenWorker | 1 天 | 主题一致性 |
| U5 | 错误边界分层 | OpenWorker | 半天 | 防止全 app 崩溃 |
| U13 | Per-session draft | OpenWorker | 半天 | 切换不丢消息 |
| U16 | EmptyState shared component | OpenWorker | 半天 | 一致性 |
| **A15** | **Auto Syntax Check** | **LLM_Simple** | **1-2 天** | **修改后立即验证** |
| **A29** | **回归测试与 issue 编号绑定** | **pi** | **1-2 天** | **测试可追溯** |

**Phase 0 交付物**:8 个独立 PR。

**验收标准**:
- [ ] 主题切换无闪烁
- [ ] hardcoded gray 颜色全部替换为语义 token
- [ ] Sidebar 崩溃不影响 chat
- [ ] 切换 session 后 ChatInput 恢复
- [ ] 写 .py 文件后自动语法检查
- [ ] 回归测试文件命名符合 `regressions/<issue>-<slug>.test.ts`

---

### Phase 1: 基建升级(2-4 周)

| # | 项 | 来源 | 工作量 | 收益 |
|---|---|---|---|---|
| U4 | 补齐 shared UI primitives(高优 3 个) | OpenWorker | 1 周 | 开发速度 ×2 |
| U15 | Settings 重构 left-nav | OpenWorker | 3-5 天 | 专业感 |
| U2 | Hover-peek sidebar | OpenWorker | 2-3 天 | 内容宽度最大化 |
| U6 | Command ⌘1-9 | OpenWorker | 1-2 天 | 键盘效率 |
| A7 | Shell 操作符检测 | OpenWorker | 1-2 天 | 安全 |
| A8 | Release 稳定文件名 | OpenWorker | 1-2 天 | 下载链接永失效 |
| A3 (部分) | E2E 目录整合 | OpenWorker | 2-3 天 | 测试组织 |
| **A14** | **AST 工具安全验证** | **LLM_Simple** | **2-3 天** | **用户工具安全** |
| **A23** | **Agent 事件发布-订阅架构** | **pi** | **1 周** | **事件驱动** |
| **A25** | **Faux Provider 测试策略** | **pi** | **3-5 天** | **测试成本低** |
| **A26** | **文件修改队列串行化** | **pi** | **2-3 天** | **避免并发冲突** |
| U4 (续) | 补齐 shared UI primitives(中优 4 个) | OpenWorker | 1 周 | 继续还技术债 |

**Phase 1 交付物**:12 个独立 PR,按依赖顺序 merge(U4 → U15 → U2 → A23)。

**验收标准**:
- [ ] `Tabs / Popover / Tooltip / DropdownMenu / Select / Switch / Dialog` 在 `src/shared/ui/`
- [ ] Settings URL 可 deep-link(`/settings/models`)
- [ ] Sidebar hover 边缘 4px 可唤出
- [ ] Command palette ⌘1-9 hint
- [ ] E2E 目录统一为 `e2e/` 三分类
- [ ] 用户工具 AST 白名单验证生效
- [ ] Agent 事件流:agent_start/turn_start/message_start 等
- [ ] Faux Provider 可替代真实 API 跑测试
- [ ] 文件修改队列串行化,无并发冲突

---

### Phase 2: 架构升级(1-2 月)

| # | 项 | 来源 | 工作量 | 收益 |
|---|---|---|---|---|
| A1 | RiskClass 数据化权限 | OpenWorker | 1 周 | 权限可扩展 |
| A2 | Provider 抽象 + Token 归一化 | OpenWorker | 1-2 周 | 多厂商无缝 |
| **A12** | **三层上下文压缩 + 错误感知截断** | **LLM_Simple** | **1 周** | **token 下降 50%+** |
| **A13** | **Quality Middleware** | **LLM_Simple** | **3-5 天** | **减少 LLM 失败模式** |
| A5 | Persona Manifest | OpenWorker | 1 周 | 用户可定制 |
| A6 | 工具并发执行 | OpenWorker | 3-5 天 | 多工具并发加速 |
| A3 (完整) | Hermetic E2E mock backend | OpenWorker | 1-2 周 | 脱网测试 |
| **A17** | **Code Diff Visualization** | **LLM_Simple** | **3-5 天** | **代码变更可见** |
| **A24** | **会话分支(Branching)树结构** | **pi** | **2 周** | **多路径探索** |
| **A27** | **工具执行钩子(before/after)** | **pi** | **2-3 天** | **preflight 校验** |
| **A28** | **分支摘要式 Compaction** | **pi** | **1 周** | **长会话压缩** |
| U7 | Right Rail + artifact viewer | OpenWorker | 2-3 周 | AI coworker 感 |
| A19 | RiskOverride 用户级权限 | OpenWorker | 3-5 天 | 权限可定制 |
| U9 | Live-dot/Attn-badge 分离 | OpenWorker | 1 周 | 视觉语义清晰 |
| U10 | Sticky-unlock chips | OpenWorker | 3-5 天 | 渐进披露 |
| U8 | Humanized tool titles | OpenWorker | 1-2 天 | 人性化 |
| **U18** | **HTML 会话导出** | **pi** | **3-5 天** | **会话可分享** |
| **U19** | **会话树可视化** | **pi** | **1 周** | **分支可视化** |

**Phase 2 交付物**:18 个 PR,按依赖顺序:A1 → A2 → A12 → A13 → A17 → A24 → U7。

**验收标准**:
- [x] `RiskClass` 枚举在 `backend/domain/risk.py`(A1 已完成,commit 63fa3b0)
- [x] `ProviderRouter` 在 `backend/application/services/`,4 个 adapter(A2 已完成:ProviderClient ABC + TokenUsage 归一化 + OpenAI/Anthropic/Gemini/Ollama)
- [ ] 三层上下文压缩:MicroCompact → Sliding Window → LLM Summary
- [ ] 错误感知截断:shell 输出保留错误上下文
- [ ] NudgeGuard 检测被动读取循环
- [ ] CircuitBreaker 阻断重复调用
- [ ] Code Diff 在 chat UI 中渲染
- [ ] 会话分支:支持多路径探索 + 切换
- [x] 工具执行钩子:beforeToolCall/afterToolCall(A27 已完成,`backend/application/services/tool_hooks.py` + `run_loop` 接入)
- [ ] 分支摘要式 Compaction
- [ ] HTML 会话导出
- [ ] 会话树可视化
- [ ] Hermetic E2E 完全脱网
- [ ] Right Rail 渲染 artifact 预览

---

### Phase 3: 重大特性(2+ 月)

| # | 项 | 来源 | 工作量 | 收益 |
|---|---|---|---|---|
| A4 | Suspend-resume agent | OpenWorker | 2-3 周 | 长任务零空闲 |
| **A16** | **Skill Auto-Activation** | **LLM_Simple** | **2-3 天** | **skills 自动生效** |
| **A18** | **ContextSnapshot** | **LLM_Simple** | **1 周** | **session 恢复不失忆** |
| **A19** | **Tool Chain Tracking** | **LLM_Simple** | **1 周** | **工具执行进度可见** |
| A10 | UI Mocks 工作流 | OpenWorker | 持续 | 减少返工 |
| A11 / U14 | 本地 STT sidecar + voice UI | OpenWorker | 1-2 月 | 差异化 |
| U11 | Drained toast | OpenWorker | 2-3 天 | 消失可见 |
| U12 | Two-step delete | OpenWorker | 1-2 天 | 防误操作 |
| U20 | Emacs 风格键盘绑定 | pi | 2-3 天 | 键盘效率 |
| **A30** | **供应链硬化** | **pi** | **3-5 天** | **依赖安全** |
| **A21** | **并行工具执行** | **pi** | **2-3 天** | **性能提升** |
| **A22** | **70+ 扩展示例生态** | **pi** | **持续** | **无 fork 定制** |

**Phase 3 交付物**:12 个特性分支,独立演进。

**验收标准**:
- [ ] Agent suspend-resume:`sleep_for(10s)` → scheduler 唤醒
- [ ] Skill `when_to_use` 自动匹配用户消息
- [ ] ContextSnapshot 捕获 session 状态
- [ ] Tool Chain Tracking 侧边栏显示进度
- [ ] Voice dictation 至少跑通 Mac 平台
- [ ] Emacs 风格键盘绑定可配置
- [ ] 供应链:精确版本 + shrinkwrap + 生命周期白名单
- [ ] 并行工具执行默认启用
- [ ] 70+ 扩展示例可供参考

---

## 5. 关键实施细节

### 5.1 Agent 事件发布-订阅架构(A23,来自 pi)

**实现位置**:`backend/domain/agent_events.py`

```python
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Optional
import asyncio

class AgentEventType(Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    MESSAGE_START = "message_start"
    MESSAGE_UPDATE = "message_update"
    MESSAGE_END = "message_end"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"
    TOOL_EXECUTION_END = "tool_execution_end"

@dataclass
class AgentEvent:
    type: AgentEventType
    data: dict
    timestamp: float

class AgentEventBus:
    """Agent 事件发布-订阅总线"""
    
    def __init__(self):
        self._subscribers: dict[AgentEventType, list[Callable]] = {}
        self._steering_queue: list[str] = []
        self._follow_up_queue: list[str] = []
    
    def subscribe(self, event_type: AgentEventType, callback: Callable):
        """订阅事件"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
    
    async def publish(self, event: AgentEvent):
        """发布事件,等待所有订阅者完成"""
        if event.type in self._subscribers:
            tasks = [callback(event) for callback in self._subscribers[event.type]]
            await asyncio.gather(*tasks)
    
    def add_steering(self, message: str):
        """添加 steering 消息(打断当前执行)"""
        self._steering_queue.append(message)
    
    def add_follow_up(self, message: str):
        """添加 follow-up 消息(当前 turn 结束后处理)"""
        self._follow_up_queue.append(message)
    
    def get_steering(self) -> Optional[str]:
        """获取下一个 steering 消息"""
        return self._steering_queue.pop(0) if self._steering_queue else None
    
    def get_follow_up(self) -> Optional[str]:
        """获取下一个 follow-up 消息"""
        return self._follow_up_queue.pop(0) if self._follow_up_queue else None

# 使用示例
event_bus = AgentEventBus()

async def on_message_start(event: AgentEvent):
    print(f"Message started: {event.data}")

event_bus.subscribe(AgentEventType.MESSAGE_START, on_message_start)

# 在 ChatService 中
async def run_turn(self, user_message: str):
    await self.event_bus.publish(AgentEvent(
        type=AgentEventType.TURN_START,
        data={"user_message": user_message},
        timestamp=time.time()
    ))
    
    # ... 执行 turn ...
    
    # 检查 steering 队列
    if steering := self.event_bus.get_steering():
        # 注入 steering 消息
        ...
    
    await self.event_bus.publish(AgentEvent(
        type=AgentEventType.TURN_END,
        data={},
        timestamp=time.time()
    ))
```

**参考**:`/home/fz/project/pi/packages/agent/src/agent.ts`

---

### 5.2 会话分支树结构(A24,来自 pi)

**实现位置**:`backend/domain/session_branch.py`

```python
from dataclasses import dataclass, field
from typing import Optional
import uuid

@dataclass
class SessionNode:
    """会话树节点"""
    id: str
    parent_id: Optional[str]
    message_id: str  # 该节点对应的消息
    children: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

@dataclass
class SessionBranch:
    """会话分支管理器"""
    session_id: str
    nodes: dict[str, SessionNode] = field(default_factory=dict)
    current_node_id: Optional[str] = None
    root_node_id: Optional[str] = None
    
    def add_node(self, parent_id: Optional[str], message_id: str) -> SessionNode:
        """添加新节点"""
        node_id = str(uuid.uuid4())
        node = SessionNode(id=node_id, parent_id=parent_id, message_id=message_id)
        self.nodes[node_id] = node
        
        if parent_id:
            self.nodes[parent_id].children.append(node_id)
        else:
            self.root_node_id = node_id
        
        self.current_node_id = node_id
        return node
    
    def switch_branch(self, node_id: str):
        """切换到另一个分支"""
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} not found")
        self.current_node_id = node_id
    
    def get_path_to_root(self) -> list[str]:
        """获取从当前节点到根的路径"""
        path = []
        current = self.current_node_id
        while current:
            path.append(current)
            current = self.nodes[current].parent_id
        return list(reversed(path))
    
    def get_all_branches(self) -> list[list[str]]:
        """获取所有分支(从根到叶子的路径)"""
        branches = []
        
        def dfs(node_id: str, path: list[str]):
            path.append(node_id)
            node = self.nodes[node_id]
            
            if not node.children:
                branches.append(list(path))
            else:
                for child_id in node.children:
                    dfs(child_id, path)
            
            path.pop()
        
        if self.root_node_id:
            dfs(self.root_node_id, [])
        
        return branches
```

**前端可视化**:`src/widgets/session/SessionTreeView.tsx`

```tsx
import { useSessionBranch } from '@/entities/session';

export function SessionTreeView() {
  const { branch, switchBranch } = useSessionBranch();
  
  return (
    <div className="session-tree">
      {branch.get_all_branches().map((path, i) => (
        <div key={i} className="branch">
          {path.map(nodeId => (
            <div
              key={nodeId}
              className={nodeId === branch.current_node_id ? 'current' : ''}
              onClick={() => switchBranch(nodeId)}
            >
              {branch.nodes[nodeId].message_id}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
```

**参考**:`/home/fz/project/pi/packages/coding-agent/src/core/agent-session.ts`

---

### 5.3 文件修改队列串行化(A26,来自 pi)

**实现位置**:`backend/application/services/file_mutation_queue.py`

```python
import asyncio
from typing import Callable, Any

class FileMutationQueue:
    """文件修改队列,确保串行化执行"""
    
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._lock = asyncio.Lock()
    
    async def start(self):
        """启动队列处理器"""
        self._running = True
        asyncio.create_task(self._process_loop())
    
    async def stop(self):
        """停止队列处理器"""
        self._running = False
        await self._queue.join()
    
    async def submit(self, operation: Callable[[], Any]) -> Any:
        """提交文件修改操作"""
        future = asyncio.get_event_loop().create_future()
        await self._queue.put((operation, future))
        return await future
    
    async def _process_loop(self):
        """处理队列"""
        while self._running:
            try:
                operation, future = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                
                async with self._lock:
                    try:
                        result = await operation()
                        future.set_result(result)
                    except Exception as e:
                        future.set_exception(e)
                
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue

# 使用示例
file_queue = FileMutationQueue()
await file_queue.start()

# 所有文件修改通过队列串行化
async def write_file(path: str, content: str):
    return await file_queue.submit(lambda: _write_file_impl(path, content))

async def edit_file(path: str, old: str, new: str):
    return await file_queue.submit(lambda: _edit_file_impl(path, old, new))
```

**参考**:`/home/fz/project/pi/packages/coding-agent/src/core/tools/file-mutation-queue.ts`

---

### 5.4 Faux Provider 测试策略(A25,来自 pi)

**实现位置**:`backend/adapters/out/llm/faux_provider.py`

```python
from .base import ProviderClient
from ...domain.llm import CompletionRequest, CompletionResponse, StreamChunk

class FauxProvider(ProviderClient):
    """模拟 Provider,用于测试"""
    
    def __init__(self, responses: list[str] = None):
        self.responses = responses or ["This is a faux response."]
        self.call_count = 0
    
    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        """返回预设响应"""
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        
        return CompletionResponse(
            content=response,
            model="faux-model",
            usage={"input": 10, "output": 20, "total": 30}
        )
    
    async def stream(self, req: CompletionRequest):
        """流式返回预设响应"""
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        
        for i, char in enumerate(response):
            yield StreamChunk(
                content=char,
                is_done=(i == len(response) - 1)
            )

# 在测试中使用
async def test_chat_service():
    faux_provider = FauxProvider(["Hello, world!"])
    chat_service = ChatService(provider=faux_provider)
    
    response = await chat_service.send_message("Hi")
    assert response.content == "Hello, world!"
    assert faux_provider.call_count == 1
```

**参考**:`/home/fz/project/pi/packages/ai/src/providers/faux.ts`

---

## 6. 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| **Phase 1 shared primitives 替换影响面广** | 视觉回归 | 分 PR 渐进替换 + 视觉回归测试 |
| **Phase 2 Right Rail 改动 Layout 大** | 影响所有 page | 先做 mock PR 评审 |
| **Phase 2 Provider 抽象破坏现有 ChatService** | 需要大重构 | 保留旧 adapter 作 fallback,双轨并行 1 周 |
| **Phase 2 三层压缩改变消息历史** | 可能丢失上下文 | 保留原始消息,压缩版本仅作 context |
| **Phase 2 会话分支复杂度高** | 实现难度大 | 先实现基础版本,渐进增强 |
| **Phase 3 STT sidecar 跨平台打包** | Windows/Mac/Linux 三平台 | 先 Mac only,渐进加 Windows/Linux |
| **Win7 LTS 兼容性** | Py3.8 不支持某些新语法 | 所有后端改动走 `scripts/py38_compat_rewrite.py` 验证 |
| **Agent 事件流改动影响面广** | 需要重构 ChatService | 保持向后兼容,渐进迁移 |

---

## 7. 验收标准(汇总)

### Phase 0 验收
- [ ] 主题切换无闪烁
- [ ] hardcoded gray 颜色全部替换为语义 token
- [ ] Sidebar 崩溃不影响 chat
- [ ] 切换 session 后 ChatInput 恢复
- [ ] 写 .py 文件后自动语法检查
- [ ] 回归测试文件命名符合规范

### Phase 1 验收
- [ ] 7 个 shared UI primitives 在 `src/shared/ui/`
- [ ] Settings URL 可 deep-link
- [ ] Sidebar hover-peek 工作
- [ ] Command ⌘1-9 跳转
- [ ] E2E 目录统一
- [ ] 用户工具 AST 验证生效
- [ ] Agent 事件流标准化
- [ ] Faux Provider 可跑测试
- [ ] 文件修改队列串行化

### Phase 2 验收
- [x] RiskClass 枚举 + 每个 tool 声明风险(A1 已完成,commit 63fa3b0)
- [x] ProviderRouter + 3+ adapter(A2 已完成,4 adapter + 58 单测)
- [ ] 三层上下文压缩 + 错误感知截断
- [ ] NudgeGuard + CircuitBreaker 中间件
- [ ] Code Diff 在 chat UI 渲染
- [ ] 会话分支:多路径探索 + 切换
- [x] 工具执行钩子:before/after(A27 已完成)
- [ ] 分支摘要式 Compaction
- [ ] HTML 会话导出
- [ ] 会话树可视化
- [ ] Hermetic E2E 脱网
- [ ] Right Rail artifact 预览

### Phase 3 验收
- [ ] Agent suspend-resume
- [ ] Skill auto-activation
- [ ] ContextSnapshot
- [ ] Tool Chain Tracking
- [ ] Voice dictation(Mac only)
- [ ] Emacs 风格键盘绑定
- [ ] 供应链硬化
- [ ] 并行工具执行
- [ ] 70+ 扩展示例

---

## 8. 参考文件清单

### OpenWorker 关键文件

| 主题 | 文件路径 |
|---|---|
| RiskClass | `/home/fz/project/openworker/coworker/risk.py` |
| Permission 引擎 | `/home/fz/project/openworker/coworker/permissions.py` |
| Provider 抽象 | `/home/fz/project/openworker/coworker/providers/` |
| Hermetic E2E | `/home/fz/project/openworker/surfaces/gui/e2e/` |
| Suspend-resume | `/home/fz/project/openworker/coworker/selfwake.py` |
| Persona manifest | `/home/fz/project/openworker/coworker/personas/builtin/` |
| Hover-peek sidebar | `/home/fz/project/openworker/surfaces/gui/src/App.tsx:240-284` |
| Right Rail | `/home/fz/project/openworker/surfaces/gui/src/components/RightRail.tsx` |
| ⌘1-9 跳转 | `/home/fz/project/openworker/surfaces/gui/src/components/SearchModal.tsx` |
| Pre-paint theme | `/home/fz/project/openworker/surfaces/gui/index.html` |
| Semantic color ladder | `/home/fz/project/openworker/surfaces/gui/src/styles.css:16-78` |

### LLM_Simple 关键文件

| 主题 | 文件路径 |
|---|---|
| 三层上下文压缩 | `/home/fz/project/LLM_Simple/agent/context_manager.py` |
| 错误感知截断 | `/home/fz/project/LLM_Simple/agent/context_manager.py:_truncate_error_aware` |
| NudgeGuard | `/home/fz/project/LLM_Simple/api/middleware/nudge.py` |
| CircuitBreaker | `/home/fz/project/LLM_Simple/api/middleware/circuit.py` |
| AST 工具验证 | `/home/fz/project/LLM_Simple/tools/manager.py:ToolValidator` |
| Code Diff 捕获 | `/home/fz/project/LLM_Simple/main.py:206-234` |
| Auto Syntax Check | `/home/fz/project/LLM_Simple/main.py:256-263` |
| Skill Auto-Activation | `/home/fz/project/LLM_Simple/skills/loader.py:_auto_activate_skills` |
| ContextSnapshot | `/home/fz/project/LLM_Simple/gui/history_manager.py:ContextSnapshot` |
| Tool Chain Tracking | `/home/fz/project/LLM_Simple/agent/tool_chain_tracker.py` |

### pi 关键文件

| 主题 | 文件路径 |
|---|---|
| Agent 事件流 | `/home/fz/project/pi/packages/agent/src/agent.ts` |
| 会话分支 | `/home/fz/project/pi/packages/coding-agent/src/core/agent-session.ts` |
| Faux Provider | `/home/fz/project/pi/packages/ai/src/providers/faux.ts` |
| 文件修改队列 | `/home/fz/project/pi/packages/coding-agent/src/core/tools/file-mutation-queue.ts` |
| 工具执行钩子 | `/home/fz/project/pi/packages/coding-agent/src/core/tools/` |
| 分支摘要 Compaction | `/home/fz/project/pi/packages/coding-agent/src/core/compaction/branch-summarization.ts` |
| 30+ Provider | `/home/fz/project/pi/packages/ai/src/providers/` |
| HTML 会话导出 | `/home/fz/project/pi/packages/coding-agent/src/core/export-html/` |
| 供应链硬化 | `/home/fz/project/pi/.npmrc` + `/home/fz/project/pi/npm-shrinkwrap.json` |
| 70+ 扩展示例 | `/home/fz/project/pi/packages/coding-agent/examples/extensions/` |

---

## 9. 总结

**Sage 的优势(保持)**:六边形 + FSD、140+ token 主题、typed i18n、@xyflow 知识图谱、Win7 LTS。

**Sage 的短板(本方案补)**:
- 来自 OpenWorker:工具权限数据化、Provider 抽象、shared UI primitives、错误边界、Hermetic E2E、suspend-resume、3 列布局、hover-peek sidebar
- 来自 LLM_Simple:三层上下文压缩、质量中间件、AST 工具安全、Code Diff、Auto Syntax Check、Skill Auto-Activation、ContextSnapshot
- 来自 pi:Agent 事件流、会话分支、Faux Provider、文件修改队列、工具执行钩子、供应链硬化

**执行节奏**:Phase 0(1 周速赢)→ Phase 1(2-4 周基建)→ Phase 2(1-2 月架构升级)→ Phase 3(2+ 月重大特性)。**每个 Phase 结束做一次回顾**,根据实际收益调整后续优先级。

**来源分布**:
- OpenWorker:27 项(架构 11 + UI 16)
- LLM_Simple:11 项(架构 7 + UI 4)
- pi:12 项(架构 10 + UI 2,实际高价值 8 项)
- **总计**:50 项优化,覆盖架构、UI、安全、性能、体验全方位

**核心借鉴**:
1. **Agent 事件驱动架构**(pi) — 标准化的事件流 + steering/follow-up 队列
2. **会话分支树结构**(pi) — 多路径探索 + 可视化
3. **三层上下文压缩**(LLM_Simple + pi) — 错误感知 + 分支摘要
4. **质量中间件**(LLM_Simple) — NudgeGuard + CircuitBreaker
5. **Faux Provider 测试**(pi) — 避免真实 API 调用
6. **文件修改队列**(pi) — 避免并发冲突
7. **工具执行钩子**(pi) — before/after preflight 校验
8. **供应链硬化**(pi) — 精确版本 + shrinkwrap
