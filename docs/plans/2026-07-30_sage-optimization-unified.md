# Sage 项目综合优化方案(统一版)

> **状态:** 已被取代 — 本文为 38 项中间版本，最终执行的是 50 项的
> `2026-07-30_sage-optimization-final.md`。
> **实施状态与真实分支映射请看 → [`2026-07-31_optimization-implementation-status.md`](2026-07-31_optimization-implementation-status.md)**
> （47/50 已实现，3 项跳过；含堆叠链、冲突矩阵与建议合并顺序）
> **日期:** 2026-07-30
> **作者:** code-explorer + planner
> **目标分支:** `main`(release/win7 按需 cherry-pick)
> **参考项目:**
> - `/home/fz/project/openworker` — Andrew Ng 团队的 AI coworker 桌面应用
> - `/home/fz/project/LLM_Simple` — 早期 PyQt5 桌面 AI Agent 工具包(v3.0)

---

## 0. TL;DR

基于对 Sage、OpenWorker、LLM_Simple 三个项目的深度对比分析,提炼出 **38 项可落地优化**(OpenWorker 27 项 + LLM_Simple 11 项),按 ROI 分 4 个阶段执行。

### 核心结论

| 维度 | Sage 现状 | 借鉴方向 | 来源 |
|---|---|---|---|
| **架构严谨性** | ✅ 六边形 + FSD(领先) | 保持 | — |
| **文档体系** | ✅ 100+ markdown(领先) | 保持 | — |
| **主题系统** | ✅ 140+ token + 11 主题(领先) | 补 pre-paint + 语义阶梯 | OpenWorker |
| **工具权限** | ⚠️ 硬编码 | 数据驱动 RiskClass | OpenWorker |
| **LLM Provider** | ⚠️ 抽象不足 | ProviderRouter + Token 归一化 | OpenWorker |
| **上下文压缩** | ❌ 缺乏智能压缩 | 三层压缩 + 错误感知 | **LLM_Simple** |
| **质量中间件** | ❌ 缺乏 | NudgeGuard + CircuitBreaker | **LLM_Simple** |
| **共享 UI primitives** | ❌ 只有 4 个 | 补齐 ~15 个 Radix primitives | OpenWorker |
| **工具安全验证** | ⚠️ 有策略但无 AST | AST 白名单验证 | **LLM_Simple** |
| **Code Diff** | ⚠️ Office 有但通用缺 | write/edit diff 可视化 | **LLM_Simple** |
| **错误边界** | ❌ 单根 | 分层隔离 | OpenWorker |
| **E2E 测试** | ❌ 依赖网络 + 3 目录 | Hermetic + 合并 | OpenWorker |
| **Agent 模式** | ❌ Always-on | Suspend-resume | OpenWorker |
| **布局** | 2 列 | 3 列(right rail) | OpenWorker |

### 阶段规划

| 阶段 | 周期 | 项目数 | 来源分布 | 收益 |
|---|---|---|---|---|
| **Phase 0 清理速赢** | 1 周 | 7 项 | OpenWorker 6 + LLM_Simple 1 | 体感立即提升 |
| **Phase 1 基建升级** | 2-4 周 | 9 项 | OpenWorker 7 + LLM_Simple 2 | 开发效率 ×2 |
| **Phase 2 架构升级** | 1-2 月 | 13 项 | OpenWorker 8 + LLM_Simple 5 | 产品气质升级 |
| **Phase 3 重大特性** | 2+ 月 | 9 项 | OpenWorker 6 + LLM_Simple 3 | 差异化竞争力 |

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

### 1.2 目标(MoSCoW 优先级)

| 优先级 | 目标 | 来源 |
|---|---|---|
| **Must** | 消除首帧主题闪烁(pre-paint script) | OpenWorker |
| **Must** | 统一语义颜色阶梯,消灭 hardcoded gray | OpenWorker |
| **Must** | 补齐 ~15 个 shared UI primitives | OpenWorker |
| **Must** | 错误边界分层 | OpenWorker |
| **Must** | 工具权限数据化(RiskClass) | OpenWorker |
| **Must** | LLM Provider 抽象 + Token 归一化 | OpenWorker |
| **Must** | 三层上下文压缩 + 错误感知截断 | **LLM_Simple** |
| **Must** | 质量中间件(NudgeGuard + CircuitBreaker) | **LLM_Simple** |
| **Should** | AST 工具安全验证 | **LLM_Simple** |
| **Should** | Code Diff 可视化 | **LLM_Simple** |
| **Should** | Hover-peek sidebar + Right rail | OpenWorker |
| **Should** | Settings 重构为 left-nav | OpenWorker |
| **Should** | Command palette ⌘1-9 | OpenWorker |
| **Should** | Hermetic E2E | OpenWorker |
| **Could** | Agent suspend-resume | OpenWorker |
| **Could** | Voice dictation UI | OpenWorker |
| **Won't** | 替换 Electron / 删除 FSD / 删除 Win7 LTS | — |

---

## 2. 对比分析摘要

### 2.1 三项目特性矩阵

| 特性 | Sage | OpenWorker | LLM_Simple | 借鉴方向 |
|---|---|---|---|---|
| **架构** | 六边形 + FSD | 分层 MVC | 分层 MVC | 保持 Sage |
| **工具权限** | 硬编码 | RiskClass 数据驱动 | AST 白名单 | ✅ 两者都借鉴 |
| **上下文管理** | ChromaDB 向量 | — | 三层压缩 + 错误感知 | ✅ LLM_Simple |
| **质量守卫** | — | — | NudgeGuard + CircuitBreaker | ✅ LLM_Simple |
| **LLM Provider** | httpx | ProviderRouter | raw requests | ✅ OpenWorker |
| **UI primitives** | 4 个 | 0 个(手写) | PyQt5 widgets | ✅ OpenWorker(走 Radix) |
| **布局** | 2 列 | 3 列 | 2 列 + sidebar | ✅ OpenWorker |
| **E2E 测试** | 依赖网络 | Hermetic | — | ✅ OpenWorker |
| **Code Diff** | Office 有 | — | ✅ 通用 diff | ✅ LLM_Simple |
| **Syntax Check** | — | — | ✅ 修改后自动 | ✅ LLM_Simple |
| **Skill Auto** | 显式调用 | — | ✅ when_to_use | ✅ LLM_Simple |

### 2.2 各项目优势(保持)

| 项目 | 优势 | Sage 态度 |
|---|---|---|
| **Sage** | 六边形 + FSD、140+ token 主题、typed i18n、@xyflow 知识图谱、Win7 LTS | 保持 |
| **OpenWorker** | Provider 抽象、Hermetic E2E、UI 模式统一、Persona manifest | 借鉴 |
| **LLM_Simple** | 三层压缩、质量中间件、AST 安全、Code Diff、Auto Syntax Check | 借鉴 |

---

## 3. 优化项清单(38 项,标注来源)

### 架构层(22 项)

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

### UI 层(16 项,全部来自 OpenWorker)

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

---

## 4. 实施阶段(统一版)

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

**Phase 0 交付物**:7 个独立 PR。

**验收标准**:
- [ ] 主题切换无闪烁
- [ ] `grep -r 'text-gray-500\|bg-red-50' src/shared/ui` 无结果
- [ ] Sidebar 崩溃不影响 chat
- [ ] 切换 session 后 ChatInput 恢复
- [ ] 写 .py 文件后自动语法检查

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
| U4 (续) | 补齐 shared UI primitives(中优 4 个) | OpenWorker | 1 周 | 继续还技术债 |

**Phase 1 交付物**:9 个独立 PR,按依赖顺序 merge(U4 → U15 → U2)。

**验收标准**:
- [ ] `Tabs / Popover / Tooltip / DropdownMenu / Select / Switch / Dialog` 在 `src/shared/ui/`
- [ ] Settings URL 可 deep-link(`/settings/models`)
- [ ] Sidebar hover 边缘 4px 可唤出
- [ ] Command palette ⌘1-9 hint
- [ ] E2E 目录统一为 `e2e/` 三分类
- [ ] 用户工具 AST 白名单验证生效

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
| U7 | Right Rail + artifact viewer | OpenWorker | 2-3 周 | AI coworker 感 |
| A19 | RiskOverride 用户级权限 | OpenWorker | 3-5 天 | 权限可定制 |
| U9 | Live-dot/Attn-badge 分离 | OpenWorker | 1 周 | 视觉语义清晰 |
| U10 | Sticky-unlock chips | OpenWorker | 3-5 天 | 渐进披露 |
| U8 | Humanized tool titles | OpenWorker | 1-2 天 | 人性化 |

**Phase 2 交付物**:13 个 PR,按依赖顺序:A1 → A2 → A12 → A13 → A17 → U7。

**验收标准**:
- [ ] `RiskClass` 枚举在 `backend/domain/risk.py`
- [ ] `ProviderRouter` 在 `backend/application/services/`,3+ adapter
- [ ] 三层上下文压缩:MicroCompact → Sliding Window → LLM Summary
- [ ] 错误感知截断:shell 输出保留错误上下文
- [ ] NudgeGuard 检测被动读取循环
- [ ] CircuitBreaker 阻断重复调用
- [ ] Code Diff 在 chat UI 中渲染
- [ ] Hermetic E2E 完全脱网
- [x] Right Rail 渲染 artifact 预览(U7 已完成,commit 0bf07af @ feat/right-rail-u7:RightRail 三段式 + ArtifactViewer md/code/pdf/image 预览 + Layout 条件第三列 + sidebar 自动折叠 + 12 单测)
- [x] Humanized tool titles(U8 已完成,commit 57bcb71 @ feat/humanized-tool-titles-u8:humanize.ts 覆盖全部后端工具 + MCP 命名空间 + subagent 合成名,Message 工具卡片人性化标题 + local/external scope 标签 + 弱化原始工具名 + 移除 args JSON dump,26 单测 + 2 渲染测试)

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
| U14 | Voice dictation(如不做 A11) | OpenWorker | 1-2 月 | 差异化 |

**Phase 3 交付物**:9 个特性分支,独立演进。

**验收标准**:
- [ ] Agent suspend-resume:`sleep_for(10s)` → scheduler 唤醒
- [ ] Skill `when_to_use` 自动匹配用户消息
- [x] ContextSnapshot 捕获 session 状态（A18 已完成，feat/context-snapshot-a18：domain dataclass + SQLite upsert + 每轮 best-effort 捕获 + resume block 注入双路径 system prompt + 33 单测）
- [x] Tool Chain Tracking 侧边栏显示进度（A19 已完成，commit a512742 @ feat/tool-chain-tracking-a19：domain/tool_chain.py 纯领域模型 + run_loop TOOL_CHAIN_UPDATE 快照事件 + ToolChainWidget 浮动侧栏(步骤图标/名称/参数/耗时/进度条,延迟淡出) + 32 后端单测 + 11 组件测试）
- [ ] Voice dictation 至少跑通 Mac 平台
- [x] Two-step delete 菜单内二次确认(U12 已完成,commit 825d0ed @ feat/two-step-delete-u12:`TwoStepDelete` 共享组件 + SessionItem/SkillCard/MemoryItem 接入,移除 3 处 `confirm()`,15 用例 + 全量 985 绿)

---

## 5. 关键实施细节

### 5.1 三层上下文压缩(A12,来自 LLM_Simple)

**实现位置**:`backend/application/services/context_compactor.py`

```python
class ContextCompactor:
    """三层上下文压缩策略"""
    
    def compact(self, messages: list[Message], max_tokens: int) -> list[Message]:
        # Layer 1: MicroCompact(按工具类型策略截断,无需 LLM)
        messages = self._micro_compact(messages)
        
        # Layer 2: Sliding Window(system prompt + 最近 N 条)
        messages = self._sliding_window(messages, keep_last=12)
        
        # Layer 3: LLM Summary(可选,用模型生成摘要)
        if self._estimate_tokens(messages) > max_tokens:
            messages = self._llm_summary(messages)
        
        return messages
    
    def _micro_compact(self, messages: list[Message]) -> list[Message]:
        """按工具类型策略截断"""
        for msg in messages:
            if msg.tool_name == 'read_file':
                # 保留行号 + 首 1/3 尾 1/6
                msg.content = self._truncate_with_line_numbers(msg.content, keep_ratio=(1/3, 1/6))
            elif msg.tool_name == 'run_shell':
                # 错误感知截断
                msg.content = self._truncate_error_aware(msg.content, max_lines=100)
            elif msg.tool_name == 'list_directory':
                # 头 50 尾 20
                msg.content = self._truncate_head_tail(msg.content, head=50, tail=20)
        return messages
    
    def _truncate_error_aware(self, content: str, max_lines: int) -> str:
        """智能截断 shell 输出,保留错误诊断上下文"""
        lines = content.split('\n')
        if len(lines) <= max_lines:
            return content
        
        # 1. 保留前 30 行(命令 + 初始输出)
        result = lines[:30]
        
        # 2. 扫描错误模式(20+ 种异常类型)
        error_windows = []
        for i, line in enumerate(lines[30:], 30):
            if any(pattern.search(line) for pattern in _ERROR_PATTERNS):
                start = max(30, i - 2)
                end = min(len(lines), i + 3)
                error_windows.append((start, end))
        
        # 3. 合并错误窗口
        for start, end in error_windows:
            result.append(f"... [跳过 {start - len(result)} 行] ...")
            result.extend(lines[start:end])
        
        # 4. 总是包含最后 5 行
        result.extend(lines[-5:])
        return '\n'.join(result)

_ERROR_PATTERNS = [
    re.compile(r'Traceback \(most recent call last\)'),
    re.compile(r'\w+Error:'),
    re.compile(r'Exception:'),
    re.compile(r'FAILED'),
    re.compile(r'AssertionError'),
    re.compile(r'SyntaxError'),
    re.compile(r'ImportError'),
    re.compile(r'NameError'),
    re.compile(r'TypeError'),
    re.compile(r'ValueError'),
    re.compile(r'KeyError'),
    re.compile(r'AttributeError'),
    re.compile(r'FileNotFoundError'),
    re.compile(r'PermissionError'),
    re.compile(r'ConnectionError'),
    re.compile(r'TimeoutError'),
    re.compile(r'UnicodeDecodeError'),
    re.compile(r'JSONDecodeError'),
    re.compile(r'YAMLException'),
    re.compile(r'fatal error:'),
]
```

**参考**:`/home/fz/project/LLM_Simple/agent/context_manager.py`

---

### 5.2 Quality Middleware(A13,来自 LLM_Simple)

**实现位置**:`backend/application/services/middleware/`

#### NudgeGuard(防被动读取循环)

```python
class NudgeGuard:
    """检测 agent 陷入被动读取循环,注入推动消息"""
    
    PASSIVE_TOOLS = {'read_file', 'list_directory', 'search_files', 'grep'}
    ACTION_KEYWORDS = {'write', 'create', 'fix', '实现', '创建', '修改', '删除', '更新'}
    
    def check(self, turn: Turn, user_message: str) -> Optional[str]:
        """如果所有工具调用都是被动读取 + 用户要求动作 → 注入推动"""
        if not any(kw in user_message for kw in self.ACTION_KEYWORDS):
            return None
        
        if turn.tool_calls and all(tc.name in self.PASSIVE_TOOLS for tc in turn.tool_calls):
            return "Stop reading. You have gathered enough information. Now COMPLETE the user's request."
        
        return None
```

#### CircuitBreaker(防重复调用)

```python
class CircuitBreaker:
    """追踪 (tool, args) 元组,重复 3+ 次则阻断"""
    
    def __init__(self, max_repeats: int = 3):
        self.call_history: dict[tuple[str, str], int] = {}
        self.max_repeats = max_repeats
    
    def should_block(self, tool_name: str, args: dict) -> bool:
        key = (tool_name, json.dumps(args, sort_keys=True))
        self.call_history[key] = self.call_history.get(key, 0) + 1
        return self.call_history[key] >= self.max_repeats
    
    def block_message(self, tool_name: str) -> str:
        return f"You've called {tool_name} multiple times with the same arguments but it's not working. Try a DIFFERENT approach."
```

**集成到 ChatService**:

```python
# backend/application/services/chat_service.py
class ChatService:
    def __init__(self, ...):
        self.middlewares = [NudgeGuard(), CircuitBreaker()]
    
    async def run_turn(self, turn: Turn, user_message: str):
        # 1. 检查中间件
        for middleware in self.middlewares:
            if block := middleware.check(turn, user_message):
                await self.inject_system_message(block)
                return
        
        # 2. 正常执行
        ...
```

**参考**:`/home/fz/project/LLM_Simple/api/middleware/nudge.py` + `circuit.py`

---

### 5.3 AST 工具安全验证(A14,来自 LLM_Simple)

**实现位置**:`backend/domain/tool_validator.py`

```python
import ast

class ToolValidator:
    """AST 白名单验证用户创建的工具"""
    
    ALLOWED_IMPORTS = {'csv', 'json', 're', 'math', 'pathlib', 'requests', 'datetime'}
    FORBIDDEN_CALLS = {'eval', 'exec', 'os.system', 'subprocess.run', '__import__'}
    
    def validate(self, code: str) -> ValidationResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(False, f"Syntax error: {e}")
        
        # 检查 import 语句
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in self.ALLOWED_IMPORTS:
                        return ValidationResult(False, f"禁止导入: {alias.name}")
            
            # 检查函数调用
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node)
                if func_name in self.FORBIDDEN_CALLS:
                    return ValidationResult(False, f"禁止调用: {func_name}")
        
        # 必须导出 TOOL_DEFINITION 和 execute
        if not self._has_required_exports(tree):
            return ValidationResult(False, "必须导出 TOOL_DEFINITION 和 execute")
        
        return ValidationResult(True)
    
    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return f"{self._get_call_name(node.func.value)}.{node.func.attr}"
        return None
    
    def _has_required_exports(self, tree: ast.Module) -> bool:
        # 检查是否有 TOOL_DEFINITION = ... 和 def execute(...)
        has_definition = any(
            isinstance(node, ast.Assign) and 
            any(isinstance(t, ast.Name) and t.id == 'TOOL_DEFINITION' for t in node.targets)
            for node in ast.walk(tree)
        )
        has_execute = any(
            isinstance(node, ast.FunctionDef) and node.name == 'execute'
            for node in ast.walk(tree)
        )
        return has_definition and has_execute

@dataclass
class ValidationResult:
    valid: bool
    reason: Optional[str] = None
```

**集成到工具注册**:

```python
# backend/adapters/out/skill/user_tool_loader.py
class UserToolLoader:
    def __init__(self):
        self.validator = ToolValidator()
    
    def load_tool(self, code: str, name: str) -> Tool:
        result = self.validator.validate(code)
        if not result.valid:
            raise ToolValidationError(f"Tool {name} failed validation: {result.reason}")
        
        # 执行代码,提取 TOOL_DEFINITION 和 execute
        ...
```

**参考**:`/home/fz/project/LLM_Simple/tools/manager.py`

---

### 5.4 Code Diff Visualization(A17,来自 LLM_Simple)

**实现位置**:
- 后端:`backend/application/services/tool_execution_service.py`
- 前端:`src/widgets/chat/CodeDiffViewer.tsx`

#### 后端捕获 diff

```python
# backend/application/services/tool_execution_service.py
class ToolExecutionService:
    async def execute(self, tool_call: ToolCall) -> ToolResult:
        # 1. 如果是 write/edit,捕获修改前内容
        before_content = None
        if tool_call.name in ('write_file', 'edit_file'):
            path = tool_call.args['path']
            if await self.file_exists(path):
                before_content = await self.read_file(path)
        
        # 2. 执行工具
        result = await self._execute_tool(tool_call)
        
        # 3. 如果是 write/edit,生成 diff
        if tool_call.name in ('write_file', 'edit_file') and before_content is not None:
            path = tool_call.args['path']
            after_content = await self.read_file(path)
            diff = self._generate_diff(before_content, after_content, path)
            result.metadata['code_diff'] = {
                'path': path,
                'before': before_content,
                'after': after_content,
                'diff': diff
            }
        
        return result
    
    def _generate_diff(self, before: str, after: str, path: str) -> str:
        """生成 unified diff"""
        import difflib
        before_lines = before.splitlines(keepends=True)
        after_lines = after.splitlines(keepends=True)
        diff = difflib.unified_diff(before_lines, after_lines, fromfile=path, tofile=path)
        return ''.join(diff)
```

#### 前端渲染 diff

```tsx
// src/widgets/chat/CodeDiffViewer.tsx
import { DiffViewer } from 'react-diff-viewer';

interface CodeDiffViewerProps {
  diff: {
    path: string;
    before: string;
    after: string;
  };
}

export function CodeDiffViewer({ diff }: CodeDiffViewerProps) {
  return (
    <div className="my-4 border border-line rounded-lg overflow-hidden">
      <div className="bg-panel px-4 py-2 border-b border-line flex items-center gap-2">
        <FileIcon className="h-4 w-4 text-faint" />
        <span className="text-sm font-mono text-ink">{diff.path}</span>
      </div>
      <DiffViewer
        oldValue={diff.before}
        newValue={diff.after}
        splitView={false}
        useDarkTheme={document.documentElement.classList.contains('dark')}
      />
    </div>
  );
}
```

**集成到 MessageRenderer**:

```tsx
// src/widgets/chat/MessageRenderer.tsx
export function MessageRenderer({ message }: { message: Message }) {
  return (
    <div>
      <MarkdownRenderer content={message.content} />
      {message.metadata?.code_diff && (
        <CodeDiffViewer diff={message.metadata.code_diff} />
      )}
    </div>
  );
}
```

**持久化**:diff 存入 SQLite message 表的 `metadata` JSON 字段。

**参考**:`/home/fz/project/LLM_Simple/main.py:206-234`

---

## 6. 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| **Phase 1 shared primitives 替换影响面广** | 视觉回归 | 分 PR 渐进替换 + 视觉回归测试 |
| **Phase 2 Right Rail 改动 Layout 大** | 影响所有 page | 先做 mock PR 评审 |
| **Phase 2 Provider 抽象破坏现有 ChatService** | 需要大重构 | 保留旧 adapter 作 fallback,双轨并行 1 周 |
| **Phase 2 三层压缩改变消息历史** | 可能丢失上下文 | 保留原始消息,压缩版本仅作 context |
| **Phase 3 STT sidecar 跨平台打包** | Windows/Mac/Linux 三平台 | 先 Mac only,渐进加 Windows/Linux |
| **Win7 LTS 兼容性** | Py3.8 不支持某些新语法 | 所有后端改动走 `scripts/py38_compat_rewrite.py` 验证 |

---

## 7. 验收标准(汇总)

### Phase 0 验收
- [ ] 主题切换无闪烁
- [ ] hardcoded gray 颜色全部替换为语义 token
- [ ] Sidebar 崩溃不影响 chat
- [ ] 切换 session 后 ChatInput 恢复
- [ ] 写 .py 文件后自动语法检查

### Phase 1 验收
- [ ] 7 个 shared UI primitives 在 `src/shared/ui/`
- [ ] Settings URL 可 deep-link
- [ ] Sidebar hover-peek 工作
- [ ] Command ⌘1-9 跳转
- [ ] E2E 目录统一
- [ ] 用户工具 AST 验证生效

### Phase 2 验收
- [ ] RiskClass 枚举 + 每个 tool 声明风险
- [ ] ProviderRouter + 3+ adapter
- [ ] 三层上下文压缩 + 错误感知截断
- [ ] NudgeGuard + CircuitBreaker 中间件
- [ ] Code Diff 在 chat UI 渲染
- [ ] Hermetic E2E 脱网
- [x] Right Rail artifact 预览(U7 已完成,commit 0bf07af @ feat/right-rail-u7)
- [x] Humanized tool titles(U8 已完成,commit 57bcb71 @ feat/humanized-tool-titles-u8)

### Phase 3 验收
- [ ] Agent suspend-resume
- [ ] Skill auto-activation
- [ ] ContextSnapshot
- [ ] Tool Chain Tracking
- [ ] Voice dictation(Mac only)

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

---

## 9. 总结

**Sage 的优势(保持)**:六边形 + FSD、140+ token 主题、typed i18n、@xyflow 知识图谱、Win7 LTS。

**Sage 的短板(本方案补)**:
- 来自 OpenWorker:工具权限数据化、Provider 抽象、shared UI primitives、错误边界、Hermetic E2E、suspend-resume、3 列布局、hover-peek sidebar
- 来自 LLM_Simple:三层上下文压缩、质量中间件、AST 工具安全、Code Diff、Auto Syntax Check、Skill Auto-Activation、ContextSnapshot

**执行节奏**:Phase 0(1 周速赢)→ Phase 1(2-4 周基建)→ Phase 2(1-2 月架构升级)→ Phase 3(2+ 月重大特性)。**每个 Phase 结束做一次回顾**,根据实际收益调整后续优先级。

**来源分布**:
- OpenWorker:27 项(架构 11 + UI 16)
- LLM_Simple:11 项(架构 7 + UI 4,实际高价值 5 项)
- **总计**:38 项优化,覆盖架构、UI、安全、性能、体验全方位
