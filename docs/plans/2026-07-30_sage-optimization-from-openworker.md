# Sage 项目综合优化方案 (借鉴 OpenWorker)

> **状态：** 计划（待启动）
> **日期：** 2026-07-30
> **作者：** code-explorer + planner
> **目标分支：** `main`（release/win7 按需 cherry-pick）
> **参考项目：** `/home/fz/project/openworker`（Andrew Ng 团队的 AI coworker 桌面应用）

---

## 0. TL;DR

基于对 Sage 与 OpenWorker 两个项目的深度对比分析（架构层 + UI 层），提炼出 **27 项可落地优化**，按 ROI 分 4 个阶段执行。核心结论：

| 维度 | Sage 现状 | 借鉴方向 |
|---|---|---|
| **架构严谨性** | ✅ 六边形 + FSD 严格分层（领先） | 保持 |
| **文档体系** | ✅ 100+ markdown 文件（领先） | 保持 |
| **主题系统** | ✅ 140+ token + 11 主题（领先） | 补 pre-paint 防闪烁 + 语义阶梯 |
| **工具权限** | ❌ 硬编码 | 数据驱动 RiskClass |
| **LLM Provider** | ❌ 抽象不足 | ProviderRouter + Token 归一化 |
| **共享 UI primitives** | ❌ 只有 4 个 | 补齐 ~15 个 Radix primitives |
| **Modal 一致性** | ❌ 3 种实现共存 | 统一到 Radix Dialog |
| **错误边界** | ❌ 单根 | 分层隔离 |
| **E2E 测试** | ❌ 依赖网络 + 3 个目录分散 | Hermetic + 合并 |
| **Agent 模式** | ❌ Always-on | Suspend-resume（零空闲成本） |
| **布局** | 2 列 | 3 列（right rail + artifacts） |

| 阶段 | 周期 | 项目数 | 收益 |
|---|---|---|---|
| **Phase 0 清理速赢** | 1 周 | 6 项 | 体感立即提升 |
| **Phase 1 基建升级** | 2-4 周 | 8 项 | 开发效率 ×2 |
| **Phase 2 架构升级** | 1-2 月 | 9 项 | 产品气质升级 |
| **Phase 3 重大特性** | 2+ 月 | 4 项 | 差异化竞争力 |

---

## 1. 背景与目标

### 1.1 背景

**OpenWorker**（https://github.com/andrewyng/openworker）是 Andrew Ng 团队开源的 AI coworker 桌面应用，产品定位"完成可交付物"而非"对话"。技术栈：Tauri 2 + React 18 + Python FastAPI + aisuite + whisper-rs。Sage 与之高度同质（桌面 AI 助手），但在若干维度上 OpenWorker 的解法更成熟：

- 数据驱动的工具风险/权限体系（`RiskClass`）
- Provider 抽象 + Token 归一化（`ProviderRouter` + cache 分片）
- Hermetic E2E（60+ 完全脱网 Playwright spec）
- Agent suspend-resume（`selfwake.py`）
- Persona 声明式 Markdown manifest
- 手写但统一的 UI 模式（hover-peek sidebar / right rail / dual-density approval / ⌘1-9 jump）

Sage 在架构严谨性（六边形 + FSD）、主题完备性（11 主题 + 用户自定义 CSS）、i18n、知识图谱可视化等方面已领先，本方案**不动 Sage 的强项**，只补 OpenWorker 做得更好的点。

### 1.2 目标（按 MoSCoW 排序）

| 优先级 | 目标 |
|---|---|
| **Must** | 消除首帧主题闪烁（pre-paint script） |
| **Must** | 统一语义颜色阶梯（ink/muted/faint/line/line-strong），消灭 hardcoded gray |
| **Must** | 补齐 ~15 个 shared UI primitives（Tabs/Popover/Tooltip/Dropdown/Switch/Dialog…） |
| **Must** | 错误边界分层（sidebar / page / widget 独立崩溃） |
| **Must** | 工具权限数据化（`RiskClass` 取代硬编码） |
| **Must** | LLM Provider 抽象 + Token 归一化 |
| **Should** | Hover-peek sidebar + Right rail（3 列布局） |
| **Should** | Settings 重构为 left-nav + URL deep-link |
| **Should** | Command palette ⌘1-9 跳转 |
| **Should** | Hermetic E2E（mock backend 脱网跑） |
| **Should** | Persona Markdown manifest + Provider 声明式 |
| **Could** | Agent suspend-resume（长任务零空闲成本） |
| **Could** | 工具并发执行（低风险工具 asyncio.gather） |
| **Could** | Voice dictation UI（本地 STT） |
| **Won't (this plan)** | 替换 Tauri（Sage 用 Electron，不迁移） |
| **Won't (this plan)** | 引入 shadcn/ui（继续用 Radix，与既有 Tailwind 一致） |
| **Won't (this plan)** | 删除 FSD 分层（这是 Sage 的护城河） |

### 1.3 非目标

- 不替换 Electron（OpenWorker 用 Tauri 不是 Sage 要学的点）
- 不删除六边形/FSD 严格分层（Sage 优势）
- 不引入新的状态管理库（Zustand + React Query 已够）
- 不动 i18n 框架（typed zh/en 已成熟）
- 不动 Win7 LTS 双分支策略（到 2027-12-13 EOL 前维持）

---

## 2. 对比分析摘要

### 2.1 架构层对比（详见 §3）

| 维度 | Sage | OpenWorker | 借鉴方向 |
|---|---|---|---|
| **工具权限** | 硬编码 WRITE_TOOLS/SHELL_TOOL | 数据驱动 `RiskClass` (READ/WRITE_LOCAL/EXEC/EXTERNAL) + 用户级 `RiskOverride` | ✅ 借鉴 |
| **LLM Provider** | httpx adapter | `ProviderClient` ABC + `ProviderRouter` + `TokenUsage` cache 分片归一化 | ✅ 借鉴 |
| **E2E 测试** | 3 目录分散 + 依赖真实后端 | Hermetic (mock `/v1` + WebSocket) + live smoke 分离 | ✅ 借鉴 |
| **Agent 模式** | Always-on | Suspend-resume (`selfwake.py` + scheduler) | ✅ 长期 |
| **Persona** | 代码定义 | Markdown + YAML frontmatter 声明式 | ✅ 借鉴 |
| **工具并发** | 串行执行 | 低风险 `asyncio.to_thread` 并发 | ✅ 借鉴 |
| **Shell 安全** | 无前缀绕过检测 | `_SHELL_OPERATORS` 检测（`; & | > < \` $(`） | ✅ 速赢 |
| **Release 产物** | 版本化命名 | 版本化 + 稳定命名（`latest.dmg`） | ✅ 速赢 |
| **Tauri 残留** | `.gitignore`/`archive/`/`CLAUDE.md` 仍引用 | 干净 | ✅ 速赢 |

### 2.2 UI 层对比（详见 §4）

| 维度 | Sage | OpenWorker | 借鉴方向 |
|---|---|---|---|
| **首帧主题** | React 挂载后设置（闪烁风险） | Pre-paint inline script（无闪烁） | ✅ 速赢 |
| **语义颜色阶梯** | 140+ token 但组件 hardcoded | `ink/muted/faint/line/line-strong` 5 级统一 | ✅ 速赢 |
| **Shared primitives** | 4 个（Button/Input/Modal/Skeleton） | 0 个（deliberately hand-rolled） | ✅ 借鉴但走 Radix 路线 |
| **错误边界** | 单根 | 无 | ✅ Sage 应做得更好 |
| **布局** | 2 列（sidebar + main） | 3 列（left nav + main + right rail） | ✅ 借鉴 |
| **Sidebar 折叠** | 可 resize 但占宽度 | Hover-peek（离开 grid + hover 滑出） | ✅ 借鉴 |
| **Command palette** | cmdk 基础好，内容少 | ⌘1-9 跳转 | ✅ 速赢 |
| **Composer** | 功能丰富（slash/@-mention/drag-drop） | 同样丰富 + voice dictation + usage chip | 部分借鉴（usage chip） |
| **Settings** | 7 tabs 水平（溢出无处理） | 左侧 sub-nav + 居中面板 | ✅ 借鉴 |
| **Approval 卡片** | 技术化（write_file(path=…)） | Humanized + 双密度（compact vs full） | ✅ 借鉴 |
| **Indicator 语义** | 可能混用 | Live-dot (活跃) vs Attn-badge (紧急) 显式分离 | ✅ 借鉴 |
| **渐进披露** | 默认全显 | Sticky-unlock chips（首次使用后常驻） | ✅ 借鉴 |
| **Toast** | sonner（装了，低使用率，突然消失） | Drained bar（可见消失进度） | ✅ 借鉴 |
| **破坏性操作** | Modal 或直执行 | Kebab menu 内两步确认（无 modal） | ✅ 借鉴 |
| **Composer draft** | 切换 session 残留 | Per-session resetKey + localStorage | ✅ 速赢 |
| **Empty state** | 各自手写 | 统一组件 | ✅ 速赢 |

---

## 3. 架构层优化项（11 项）

### A1. 工具权限数据化（RiskClass）

**现状**：`backend/domain/tool.py` 等位置硬编码 `WRITE_TOOLS` / `SHELL_TOOL` 名字集合，新增工具需改权限判断逻辑。

**OpenWorker 做法**：`coworker/risk.py` 定义 `RiskClass(READ, WRITE_LOCAL, EXEC, EXTERNAL)` 枚举，每个工具声明风险，权限引擎按等级裁决；`coworker/permissions.py` 的 `Mode(DISCUSS, PLAN, INTERACTIVE, AUTO, CUSTOM)` 驱动 allow/deny/ask；`coworker/overrides.py` 支持用户级覆盖。

**实施方案**：

1. 新增 `backend/domain/risk.py`：
   ```python
   class RiskClass(str, Enum):
       READ = "read"           # 无副作用
       WRITE_LOCAL = "write_local"  # 改 workspace
       EXEC = "exec"           # 跑命令
       EXTERNAL = "external"   # 出站副作用（Slack/邮件/API）
   ```

2. 每个 Tool 注册时声明 `risk: RiskClass`：
   ```python
   Tool(name="write_file", risk=RiskClass.WRITE_LOCAL, ...)
   Tool(name="run_shell", risk=RiskClass.EXEC, ...)
   Tool(name="search_web", risk=RiskClass.EXTERNAL, ...)
   ```

3. 新增 `backend/domain/permission.py`：
   ```python
   class Mode(str, Enum):
       DISCUSS = "discuss"       # 只读对话
       PLAN = "plan"             # 只读 + 规划流程
       INTERACTIVE = "interactive"  # 默认，写/执行需审批
       AUTO = "auto"             # 全开
       CUSTOM = "custom"         # interactive + auto_allow 列表
   ```

4. 新增 `backend/adapters/out/permission/`：SQLite 持久化用户级 `RiskOverride`。

5. 权限引擎统一裁决：`PermissionEngine.decide(tool, args, mode) -> Allow | Deny | AskUser`。

**收益**：权限策略可审计/可扩展/可用户定制；为"无人值守模式"（Inbox routing）铺路。

**工作量**：1 周。

**参考**：
- `/home/fz/project/openworker/coworker/risk.py`
- `/home/fz/project/openworker/coworker/permissions.py`
- `/home/fz/project/openworker/coworker/overrides.py`

---

### A2. LLM Provider 抽象 + Token 归一化

**现状**：`backend/adapters/out/llm/` 有 httpx 实现，但缺乏多厂商抽象；token 计数、cache 分片口径不一致。

**OpenWorker 做法**：`coworker/providers/` 目录：`ProviderClient` ABC + `ProviderRouter` 按 model name 路由；`TokenUsage` 统一 `input/output/cache_read/cache_write` 4 字段；UI 显示 "Uncached input" 当 cache 分片存在。

**实施方案**：

1. 新增 `backend/ports/llm.py`（如未完善）：
   ```python
   class ProviderClient(ABC):
       async def complete(self, req: CompletionRequest) -> CompletionResponse: ...
       async def stream(self, req: CompletionRequest) -> AsyncIterator[StreamChunk]: ...
   ```

2. 新增 `backend/adapters/out/llm/anthropic.py` / `openai.py` / `gemini.py` / `ollama.py`。

3. 新增 `backend/application/services/provider_router.py`：
   ```python
   class ProviderRouter:
       def route(self, model: str) -> ProviderClient: ...
   ```

4. 归一化 `TokenUsage`：每个 adapter 输出统一的 4 字段结构。

5. 前端新增 UsageChip：显示 cache 命中 / 未缓存输入 / 输出。

**收益**：多厂商无缝切换；token 成本可视化；prompt caching 收益可量化。

**工作量**：1-2 周。

**参考**：
- `/home/fz/project/openworker/coworker/providers/`
- `/home/fz/project/openworker/surfaces/gui/src/components/Composer.tsx:572-695`（UsageChip）

---

### A3. Hermetic E2E 测试

**现状**：Sage 的 E2E 分散在 `tests/e2e/`、`tests/electron/`、`e2e/` 三处，依赖真实后端。

**OpenWorker 做法**：
- `surfaces/gui/e2e/` — 60+ 个 Playwright spec，**完全脱网**，mock `/v1` + WebSocket
- `surfaces/gui/e2e-live/` — 少量 live smoke（真实后端）

**实施方案**：

1. **合并目录**：统一到 `e2e/`，按子目录分类：
   ```
   e2e/
   ├── hermetic/      # 完全脱网，mock backend
   ├── live/          # 真实后端（smoke only）
   └── electron/      # Electron 特有测试
   ```

2. **Mock backend**：新建 `e2e/fixtures/mock_backend.py`（FastAPI with canned responses），路由 `/v1/chat`、`/v1/completions` 返回固定流。

3. **Playwright config** 拆 3 个 project：
   ```ts
   projects: [
     { name: 'hermetic', testDir: 'e2e/hermetic', use: { baseURL: 'http://localhost:1420' } },
     { name: 'live', testDir: 'e2e/live', use: { baseURL: 'http://localhost:1420' } },
     { name: 'electron', testDir: 'e2e/electron' },
   ]
   ```

4. **CI**：`hermetic` 跑在每次 push，`live` 只在 main/release 跑。

**收益**：CI 不再因 LLM API 抖动而红；测试速度快 5-10 倍；可本地跑 E2E。

**工作量**：2-3 周。

**参考**：
- `/home/fz/project/openworker/surfaces/gui/e2e/`（hermetic 模式）
- `/home/fz/project/openworker/surfaces/gui/e2e-live/`（live smoke）

---

### A4. Agent Suspend-Resume

**现状**：Sage 的 agent 是 always-on，空闲时仍占用资源；Scheduler 是独立组件。

**OpenWorker 做法**：`coworker/selfwake.py` 定义 `Wake` 概念（timer / completion / event 三种触发），agent 可以 `sleep_for` / `sleep_until` / `wake_on`，scheduler tick 扫描 `due()` 的 wake 恢复 session。

**实施方案**：

1. 新增 `backend/domain/wake.py`：
   ```python
   class WakeKind(str, Enum):
       TIMER = "timer"           # sleep_for / sleep_until
       COMPLETION = "completion" # wake_on 后台任务完成
       EVENT = "event"           # webhook 触发（Phase 3）

   @dataclass
   class Wake:
       id: str
       session_id: str
       kind: WakeKind
       state: str  # pending / due / fired
       fire_at: Optional[datetime]
   ```

2. 新增 `backend/application/services/wake_store.py`：SQLite 持久化。

3. 扩展现有 `ChatStreamRegistry`：active stream 可以"挂起"并注册 wake 条件。

4. Scheduler tick 时扫描 `due()` 的 wake，恢复对应 session 的 stream。

**收益**：多 agent 并发时内存/CPU 占用大幅下降；长任务（后台文件处理、批量总结）可行。

**工作量**：2-3 周。

**参考**：
- `/home/fz/project/openworker/coworker/selfwake.py`
- `/home/fz/project/openworker/coworker/automation/scheduler.py`

---

### A5. Persona 声明式 Manifest

**现状**：Sage 的 agent 在代码里定义（`backend/domain/agent.py`），修改 persona 需改代码。

**OpenWorker 做法**：`coworker/personas/builtin/ops.md` — Markdown + YAML frontmatter 声明：
```markdown
---
id: ops
name: Ops Coworker
icon: 🛠️
tools: [shell, files, git, search]
connectors:
  core: [github, jira]
  optional: [slack]
recommended_models: [claude-sonnet-4-5, gpt-4-1]
default_mode: interactive
---

# Ops Coworker
You are a senior DevOps engineer...
```

**实施方案**：

1. 新增 `backend/adapters/out/skill/personas/` 放 `.md` 文件。

2. 扩展现有 `SkillLoader` 为 `PersonaLoader`：启动时扫描目录，解析 frontmatter。

3. 前端 Settings → Personas 页可热加载（无需重启）。

4. Persona 可以像 skill 一样分享（agentskills.io 兼容）。

**收益**：用户可自定义 persona 不碰代码；persona 生态可分享。

**工作量**：1 周。

**参考**：
- `/home/fz/project/openworker/coworker/personas/builtin/`
- `/home/fz/project/openworker/surfaces/gui/src/components/Onboarding.tsx`（persona gallery UI）

---

### A6. 工具并发执行

**现状**：Sage 的工具执行是串行的（`adapters/out/tool/` 按序调用）。

**OpenWorker 做法**：低风险工具（`READ` 类）通过 `asyncio.to_thread` 并发执行；写入/shell 严格串行。

**实施方案**：

1. `ToolExecutionService` 按 `RiskClass` 分流：
   ```python
   if tool.risk == RiskClass.READ:
       await asyncio.gather(*[exec(t) for t in tools])
   else:
       for t in tools:
           await exec(t)
   ```

2. 保持 `ToolPolicy` 的 max_calls 约束（并发场景下用 `asyncio.Semaphore`）。

**收益**：多工具并发 chat turn 耗时显著下降（同时搜索 + 读多个文件）。

**工作量**：3-5 天。

**参考**：`/home/fz/project/openworker/coworker/engine.py`（并发执行部分）

---

### A7. Shell 操作符检测（防 allowlist 绕过）

**现状**：Sage 的工具策略允许特定 shell 命令前缀，但没检测操作符链接。

**OpenWorker 做法**：
```python
_SHELL_OPERATORS = (";", "&", "|", ">", "<", "`", "$(", "(", "\n", "\r")
# 任何 allowlist 命令含上述字符 → 必须走审批
def _has_shell_operators(command: str) -> bool:
    return any(op in command for op in _SHELL_OPERATORS)
```

**实施方案**：在 `backend/adapters/out/tool/shell.py` 增加检查：
```python
def decide_shell_allowlist(cmd: str, allowlist: list[str]) -> bool:
    if _has_shell_operators(cmd):
        return False  # 必须走审批
    return any(cmd.startswith(prefix) for prefix in allowlist)
```

**收益**：堵住 allowlist 绕过漏洞（如 `rm -rf / ; cat /etc/passwd`），安全审计更扎实。

**工作量**：1-2 天。

**参考**：`/home/fz/project/openworker/coworker/permissions.py:_has_shell_operators`

---

### A8. Release Artifacts 稳定文件名

**现状**：Sage 的 release 产物是 `sage-v0.4.5-beta.2-win7.exe`，下载链接每次变化。

**OpenWorker 做法**：每个 installer 同时上传**版本化名字**和**稳定名字**（`OpenWorker-macos-arm64.dmg`），网站下载链接永远指向 `releases/latest/download/<稳定名>`。

**实施方案**：在 `.github/workflows/release.yml` 和 `release-win7.yml` 中额外上传：
```yaml
- name: Upload versioned
  uses: actions/upload-release-asset@v1
  with:
    asset_name: sage-${{ github.ref_name }}-windows.exe
- name: Upload stable
  uses: actions/upload-release-asset@v1
  with:
    asset_name: sage-latest-windows.exe  # 稳定名
```

**收益**：文档、论坛分享的下载链接永不失效；自动更新检查更简单。

**工作量**：1-2 天。

**参考**：`/home/fz/project/openworker/.github/workflows/release.yml`

---

### A9. 清理 Tauri 残留

**现状**：`.gitignore` 仍引用 `src-tauri/`、`Cargo.lock`、Rust targets；`archive/` 有旧 Tauri 代码；`CLAUDE.md` 仍提 Tauri 命令。

**实施方案**：

1. `.gitignore` 删 Tauri 相关行（或移到 `archive/tauri/`）。
2. `archive/tauri/` 明确归档 + README 说明。
3. `CLAUDE.md` 删 Tauri 构建章节（保留 Electron）。
4. `scripts/` 如有 `tauri-*` 脚本也清理。

**收益**：减少新人认知负担；避免"为什么有 Tauri 但又用 Electron"的困惑。

**工作量**：半天。

---

### A10. UI Mocks In-Repo

**现状**：UI 改动主要靠口头描述或截图，缺乏可点击原型。

**OpenWorker 做法**：`ui-mocks/` 目录存放静态 HTML 原型（`redesign.html` 65KB 全 app mockup — 是 Tailwind config 的参考源）。

**实施方案**：

1. 新建 `mocks/` 目录（或 `docs/mocks/`）。
2. 重大 UI 改动先丢一个 HTML mock，设计评审通过再进 FSD。
3. Tailwind config 与 mock 共享 utility 名（保证设计 → 实现零翻译损耗）。

**收益**：减少"做完才发现方向错"的返工；新人 onboarding 可看 mock 理解设计意图。

**工作量**：持续实践，无一次性工作量。

**参考**：`/home/fz/project/openworker/ui-mocks/redesign.html`

---

### A11. 本地 STT Sidecar（长期）

**现状**：Sage 没有语音输入。

**OpenWorker 做法**：`stt/` Rust crate（`whisper-rs` + `cpal`），独立于 Tauri shell，任何消费方都能用。

**实施方案**（如要做）：

1. **先做 Rust crate**（独立可复用）：`packages/stt/`，whisper-rs 封装。
2. **Electron 集成**：通过 NAPI 或 sidecar 调用。
3. **UI**：Composer 内 `mic` 按钮 → 波形 → 转写 → append。

**收益**：本地 STT 保护隐私；独立 crate 可被 drawio-mcp-server 等复用。

**工作量**：1-2 月（可选）。

**参考**：`/home/fz/project/openworker/stt/`（Rust crate）

---

## 4. UI 层优化项（16 项）

### U1. Pre-Paint Theme Script（消除首帧闪烁）

**现状**：`ThemeProvider.applyThemeColors()` 在 React 挂载后执行，首帧可能显示错误主题再切回。

**OpenWorker 做法**：`index.html` 内嵌 `<script>` 在 DOM 解析前同步读取 `localStorage.openwork-theme` 并设置 `data-theme` 属性，**第一帧就是正确颜色**。

**实施方案**：

```html
<!-- src/index.html -->
<script>
  (function() {
    try {
      const theme = localStorage.getItem('sage-theme');
      const mode = localStorage.getItem('sage-theme-mode');
      const prefersDark = matchMedia('(prefers-color-scheme: dark)').matches;
      const resolved = mode === 'dark' || (!mode && prefersDark) ? 'dark' : 'light';
      if (theme) document.documentElement.dataset.theme = theme;
      if (resolved === 'dark') document.documentElement.classList.add('dark');
    } catch (e) {}
  })();
</script>
```

**收益**：主题切换无闪烁，体感立刻提升。

**工作量**：2 小时。

**参考**：`/home/fz/project/openworker/surfaces/gui/index.html`

---

### U2. Hover-Peek Sidebar（兼得宽度与导航）

**现状**：Sage 的 sidebar 要么显示（占宽度）要么隐藏（完全不可达，需快捷键）。

**OpenWorker 做法**：折叠后 sidebar 离开 grid（内容真正占满宽度），左边缘留 4px `.nav-hover-zone`，鼠标靠近时 sidebar 作为浮动 overlay 滑出（`translateX`）。

**实施方案**：

1. `Layout.tsx` 增加 hover-peek 模式：
   ```css
   .app.collapsed { grid-template-columns: 1fr; }
   .nav-hover-zone {
     position: fixed; left: 0; top: 0;
     width: 4px; height: 100vh;
     z-index: 100;
   }
   .nav-hover-zone:hover + .sidebar {
     transform: translateX(0);
   }
   .sidebar {
     transform: translateX(calc(-100% + 4px));
     transition: transform 0.18s ease;
   }
   ```

2. 焦点离开后 300ms 自动收起（`onMouseLeave` + `setTimeout`）。

**收益**：内容区宽度最大化 + 导航仍可鼠标触及，优于传统"icon rail"方案。

**工作量**：2-3 天。

**参考**：
- `/home/fz/project/openworker/surfaces/gui/src/App.tsx:240-284`
- `/home/fz/project/openworker/surfaces/gui/src/styles.css:119-140`

---

### U3. Semantic Color Ladder（统一"安静程度"词汇）

**现状**：Sage 的 token 系统虽丰富，但共享组件仍用 hardcoded `bg-red-50` / `text-gray-500`，在 Cyberpunk 主题下格格不入。

**OpenWorker 做法**：5 级灰阶语义 token — `ink`（主文本）/ `muted`（次要）/ `faint`（安静）/ `line`（分割线）/ `line-strong`（强调分割），所有"quiet"都用 `text-faint`，永远不会出现 `#888`。

**实施方案**：

1. 新增 token（`src/index.css`）：
   ```css
   :root {
     --color-ink-rgb: ...;
     --color-muted-rgb: ...;
     --color-faint-rgb: ...;
     --color-line-rgb: ...;
     --color-line-strong-rgb: ...;
   }
   ```

2. Tailwind 扩展（`tailwind.config.js`）：
   ```js
   colors: {
     ink: 'rgb(var(--color-ink-rgb) / <alpha-value>)',
     muted: 'rgb(var(--color-muted-rgb) / <alpha-value>)',
     faint: 'rgb(var(--color-faint-rgb) / <alpha-value>)',
     line: 'rgb(var(--color-line-rgb) / <alpha-value>)',
   }
   ```

3. **全代码库 grep 替换**：
   ```bash
   # 一次性替换
   rg -l 'text-gray-500|text-gray-400|text-gray-600' src/ | xargs sed -i 's/text-gray-500/text-faint/g; ...'
   rg -l 'border-gray-200|border-gray-300' src/ | xargs sed -i 's/border-gray-200/border-line/g; ...'
   ```

**收益**：主题一致性立刻提升，Cyberpunk 主题不再出现蓝色灰色残留。

**工作量**：1 天（含 grep 替换 + 视觉回归测试）。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/styles.css:16-78`

---

### U4. 补齐 Shared UI Primitives（最紧迫技术债）

**现状**：`src/shared/ui/` 只有 Button/Input/Modal/Skeleton，每个页面都在重建 Tabs/Card/Popover/Tooltip。

**OpenWorker 做法**：虽然也手写所有 primitives，但**每个只写一次**，全 app 共用。

**Sage 建议**：继续用 Radix（与既有 Tailwind + Headless UI 一致），不要照抄 OpenWorker 全手写。优先级：

| Priority | Primitive | 当前状态 | 影响范围 |
|---|---|---|---|
| 🔥 高 | `Tabs` (Radix) | Settings 用自定义 tab bar | Settings / Orchestration / Office |
| 🔥 高 | `Popover` (Radix) | Slash menu / knowledge picker 是绝对定位 div | Chat / Composer |
| 🔥 高 | `Tooltip` (Radix) | 几乎没有 tooltip | 全局 |
| 🟡 中 | `DropdownMenu` (Radix) | Sidebar kebab menu 手写 | Sidebar / Table actions |
| 🟡 中 | `Select` (Radix) | 各处 `<select>` 裸元素 | Settings / Filters |
| 🟡 中 | `Switch` (Headless UI) | Settings `Toggle` 是自定义按钮 | Settings |
| 🟡 中 | `Dialog` (Radix 替换 Headless UI) | 3 种 Modal 实现 | 全局 |
| 🟢 低 | `Badge`, `Avatar`, `Card`, `Separator`, `ScrollArea` | 散落各处 | 渐进补齐 |

**实施顺序**：先补 🔥 高优 3 个（1 周），再补 🟡 中优 4 个（1 周），最后按需补 🟢。

**收益**：每个新页面开发速度 ×2，视觉一致性自动保证。

**工作量**：2 周（渐进）。

---

### U5. 错误边界分层

**现状**：Sage 只有单个根 `ErrorBoundary`，Sidebar 崩溃会让整个 app 白屏。

**实施方案**：在 FSD 每个 page 和关键 widget 包一层 `ErrorBoundary`：

```tsx
// src/app/providers/AppProviders.tsx
<ErrorBoundary fallback={<AppErrorFallback />}>
  <Layout>
    <ErrorBoundary fallback={<SidebarErrorFallback />}>
      <Sidebar />
    </ErrorBoundary>
    <ErrorBoundary fallback={<PageErrorFallback />}>
      <Outlet />
    </ErrorBoundary>
  </Layout>
</ErrorBoundary>
```

**收益**：Sidebar 崩溃不影响 chat，单个 page 崩溃不 reload 整个 app。

**工作量**：半天。

---

### U6. Command Palette ⌘1-9 跳转

**现状**：Sage 的 cmdk 只有 ↑/↓ 导航，键盘党仍需多次按键。

**OpenWorker 做法**：`SearchModal` 每行右侧显示 `<kbd>⌘1</kbd>` ~ `<kbd>⌘9</kbd>` hint，按数字直接跳转。

**实施方案**：在 `src/widgets/command/CommandPalette.tsx`：

```tsx
{results.slice(0, 9).map((item, i) => (
  <CommandItem key={item.id} onSelect={() => item.action()}>
    <span>{item.label}</span>
    <kbd className="ml-auto text-xs text-faint">⌘{i + 1}</kbd>
  </CommandItem>
))}
```

**收益**：键盘重度用户效率显著提升。

**工作量**：1-2 天。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/components/SearchModal.tsx`

---

### U7. Right Rail（Artifacts + Progress + Access）

**现状**：Sage 只有 2 列布局，生成的文件（PDF、图片、markdown）没有 in-app 预览，需要外部打开。

**OpenWorker 做法**：第三列 `RightRail` 含三 section：
- **Progress** — todo 列表 + 工具调用计数
- **Artifacts** — 生成的文件列表，点击展开预览（PDF / 图片 / 代码 / markdown）
- **Access** — session-scoped 设置

**实施方案**：

1. 新增 `src/widgets/rail/RightRail.tsx`。
2. `Layout.tsx` 增加条件第三列：
   ```css
   .app { grid-template-columns: 264px 1fr; }
   .app.with-rail { grid-template-columns: 264px 1fr 332px; }
   ```
3. Artifact 预览：
   - Markdown：`react-markdown`（已装）
   - 代码：`shiki`（已装）
   - PDF：`pdfjs-dist`（需新装）
   - 图片：`<img>` 原生
4. **细节**：打开预览时 sidebar 自动折叠（给更多宽度）— OpenWorker 这个细节很赞。

**收益**：生成的内容无需离开 app 即可审阅，大幅提升"AI coworker"感。

**工作量**：2-3 周。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/components/RightRail.tsx`

---

### U8. Humanized Approval / Action Titles

**现状**：Sage 的工具执行反馈偏技术化（"write_file(path=...)"）。

**OpenWorker 做法**：`humanize.ts` 把工具调用翻译成人性化语句 — "Write **src/App.tsx**, stays on this Mac"（加粗对象 + 范围描述）。

**实施方案**：新增 `src/shared/lib/humanize.ts`：

```ts
export function humanizeToolCall(tool: string, args: any): { verb: string; object: string; scope?: string } {
  switch (tool) {
    case 'write_file': return { verb: 'Write', object: args.path };
    case 'read_file': return { verb: 'Read', object: args.path };
    case 'run_shell': return { verb: 'Run', object: args.command, scope: 'local' };
    case 'search_web': return { verb: 'Search', object: args.query, scope: 'external' };
    default: return { verb: tool, object: '' };
  }
}
```

在 tool execution feedback UI 中使用。

**收益**：非技术用户更易懂，产品气质从"工具"升级到"助手"。

**工作量**：1-2 天。

**参考**：
- `/home/fz/project/openworker/surfaces/gui/src/humanize.ts`
- `/home/fz/project/openworker/surfaces/gui/src/components/ApprovalCard.tsx`

---

### U9. Live-Dot vs Attention-Badge 分离

**现状**：Sage 的 sidebar 活跃度指示器可能混用"活动状态"和"待处理数量"两种语义。

**OpenWorker 做法**：显式区分两种视觉词汇：
- **LiveDot** — 无数字的小圆点，表示"正在工作/睡眠"
- **AttnBadge** — 带数字的 accent 气泡，表示"需要你注意"

**实施方案**：在 `src/widgets/sidebar/` 引入两个原语，全局统一使用。

**收益**：用户对"需要我做什么 vs 正在发生什么"有清晰感知。

**工作量**：1 周。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/components/Sidebar.tsx`

---

### U10. Sticky-Unlock Chips（渐进式功能披露）

**现状**：Sage 的 sidebar footer 可能常驻显示所有功能入口。

**OpenWorker 做法**：Inbox chip **默认不可见**，直到第一次有 inbox 项目后才永久出现（写入 localStorage）。这是"progressive disclosure"的经典模式。

**实施方案**：Skills / Orchestration / Office 等高级入口，首次使用前隐藏，首次使用后解锁：

```ts
const [unlocked, setUnlocked] = useLocalStorage<Set<string>>('sage-feature-unlock', new Set());
// 首次使用某功能后：
setUnlocked(prev => new Set([...prev, featureKey]));
```

**收益**：新用户不被复杂功能吓到，老用户不失去访问路径。

**工作量**：3-5 天。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/components/Sidebar.tsx`（account row inbox chip）

---

### U11. Drained Toast（可见的自动消失进度）

**现状**：Sage 的 sonner toast 4 秒后突然消失，用户可能没注意到。

**OpenWorker 做法**：Toast 底部有 2px `.toast-drain` 动画条，与 auto-dismiss timer 同步，视觉上"看得到在消失"。

**实施方案**：sonner 支持自定义 component，写一个 `DrainedToast` wrapper：

```css
.toast-drain {
  position: absolute; bottom: 0; left: 0; height: 2px;
  background: currentColor; opacity: 0.3;
  animation: drain linear forwards;
  animation-duration: var(--toast-duration);
}
@keyframes drain { from { width: 100%; } to { width: 0%; } }
```

**收益**：减少"咦，刚才那个提示去哪了"的困惑。

**工作量**：2-3 天。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/App.tsx:1204-1240`

**实施记录**：✅ 已实施（2026-07-31，`feat/drained-toast-u11`）。适配点：sonner v2 移除了 v1 的 `component` prop，无法全局替换 toast 内容组件；改为 `toastOptions.classNames.toast` 挂类名 + CSS `::after` 挂 drain 条（`src/index.css` `@keyframes drain`），动画时长读取 `--sage-toast-duration` CSS 变量（经 `toastOptions.style` 写到每个 toast li，与 dismiss 计时器同源）；sonner 悬停/展开堆叠时暂停计时器，CSS 以 `animation-play-state: paused` 同步暂停。文件：`src/shared/ui/DrainedToast.tsx`（Toaster 包装器 + 常量导出）、`src/shared/ui/__tests__/DrainedToast.test.tsx`（5 用例，含组件↔CSS 契约测试）、`src/app/providers/ToastProvider.tsx`、`src/index.css`。

---

### U12. Two-Step Delete in Kebab Menu（无 modal 的二次确认）

**现状**：Sage 的 destructive actions 要么用 modal 二次确认（重），要么直接执行（险）。

**OpenWorker 做法**：在 kebab menu 内，第一次点"Delete"变成 armed 状态（"Delete?"），第二次才真正删除。**不弹 modal**，但同样防误操作。

**实施方案**：sidebar session 删除、skill 卸载等场景适用：

```tsx
const [armed, setArmed] = useState<string | null>(null);
<Menu.Item onClick={() => {
  if (armed === sessionId) { deleteSession(sessionId); setArmed(null); }
  else setArmed(sessionId);
}}>
  {armed === sessionId ? 'Delete?' : 'Delete'}
</Menu.Item>
```

**收益**：轻量但有效的防误操作。

**工作量**：1-2 天。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/components/Sidebar.tsx`（rowActions）

**状态**：✅ 已完成（2026-07-31，commit 825d0ed @ `feat/two-step-delete-u12`，基于 origin/main @ 7f78773）。共享组件 `src/widgets/sidebar/TwoStepDelete.tsx`（armed → 3s 自动 disarm / Esc 解除 / 阻止冒泡）；已应用到 SessionItem（会话删除）、SkillCard（技能卸载，Skills 页 `window.confirm` 同步移除）、MemoryItem（记忆删除）；新增 i18n 键 `common.delete_confirm`；15 个新/改用例（TwoStepDelete 7 + SessionItem.delete 3 + SkillCard/MemoryItem/Skills.delete 5），全量 985 passed / 0 failed。

---

### U13. Per-Session Composer Draft Persistence

**现状**：Sage 切换 session 时，ChatInput 的内容可能残留或丢失。

**OpenWorker 做法**：`Composer` 接收 `resetKey={sessionId}`，每次 session 切换清空 + 从 localStorage 恢复该 session 的 draft。

**实施方案**：在 `useChatInput` hook 中：

```ts
const [drafts, setDrafts] = useLocalStorage<Record<string, string>>('sage-drafts', {});
const currentDraft = drafts[sessionId] ?? '';
const updateDraft = (text: string) => setDrafts(prev => ({ ...prev, [sessionId]: text }));
```

**收益**：用户切换 session 不丢半成品消息。

**工作量**：半天。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/components/Composer.tsx`（resetKey + prefill nonce）

---

### U14. Voice Dictation UI（长期）

**现状**：Sage 完全没有语音输入能力。

**OpenWorker 做法**：Composer 内 `mic` 按钮触发：
- 10Hz 轮询 mic RMS，渲染 14 条滚动波形
- Timer 显示 `m:ss`
- Esc 取消
- Transcribe-then-append 模式

**实施方案**：

1. Rust STT crate（参考 A11）
2. Electron 集成（NAPI / sidecar）
3. UI 状态机：`idle | recording | transcribing | error`

**收益**：桌面 app 差异化竞争力。

**工作量**：1-2 月（可选，放长期）。

**参考**：
- `/home/fz/project/openworker/stt/`（Rust crate）
- `/home/fz/project/openworker/ui-mocks/voice-input-composer-states.html`

---

### U15. Settings 页面重构

**现状**：Sage 的 Settings 7 tabs 水平排列，窄屏溢出无处理，不能 URL deep-link，不持久化 active tab。

**OpenWorker 做法**：左侧 sub-nav（208px）+ 右侧居中滚动面板（`max-w-3xl`），所有 settings 类页面复用这套 shell。

**实施方案**：

1. 改为**左侧垂直 sub-nav**（类似 Notion / Linear Settings）。
2. URL 路由：`/settings/general`、`/settings/models` — 可 deep-link。
3. 持久化：`useSessionStorage` 记住最后 active tab。
4. 复用 Radix `Tabs` primitive（vertical orientation）。

**收益**：专业感提升，可分享设置页链接。

**工作量**：3-5 天。

**参考**：`/home/fz/project/openworker/surfaces/gui/src/components/SettingsView.tsx`

---

### U16. EmptyState Shared Component

**现状**：Sage 各区域的空状态都是手写文本，风格不一。

**实施方案**：新增 `src/shared/ui/EmptyState.tsx`：

```tsx
interface EmptyStateProps {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      {Icon && <Icon className="h-12 w-12 text-faint mb-4" />}
      <h3 className="text-ink text-lg font-medium">{title}</h3>
      {description && <p className="text-muted mt-1">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
```

**收益**：一致性 + 开发速度。

**工作量**：半天。

---

## 5. 实施阶段

### Phase 0：清理与速赢（1 周）

| # | 项 | 工作量 | 收益 |
|---|---|---|---|
| A9 | 清理 Tauri 残留 | 半天 | 减少困惑 |
| U1 | Pre-paint theme script | 2 小时 | 主题无闪烁 |
| U3 | Semantic color ladder | 1 天 | 主题一致性 |
| U5 | 错误边界分层 | 半天 | 防止全 app 崩溃 |
| U13 | Per-session draft | 半天 | 切换 session 不丢消息 |
| U16 | EmptyState shared component | 半天 | 一致性 |

**Phase 0 交付物**：6 个独立 PR，每个可单独 merge。

---

### Phase 1：基建升级（2-4 周）

| # | 项 | 工作量 | 收益 |
|---|---|---|---|
| U4 | 补齐 shared UI primitives（高优 3 个） | 1 周 | 开发速度 ×2 |
| U15 | Settings 重构 left-nav | 3-5 天 | 专业感 |
| U2 | Hover-peek sidebar | 2-3 天 | 内容宽度最大化 |
| U6 | Command ⌘1-9 | 1-2 天 | 键盘效率 |
| A7 | Shell 操作符检测 | 1-2 天 | 安全 |
| A8 | Release 稳定文件名 | 1-2 天 | 下载链接永失效 |
| A3 (部分) | E2E 目录整合 | 2-3 天 | 测试组织 |
| U4 (续) | 补齐 shared UI primitives（中优 4 个） | 1 周 | 继续还技术债 |

**Phase 1 交付物**：8 个独立 PR，按依赖顺序 merge（U4 → U15 → U2）。

---

### Phase 2：架构升级（1-2 月）

| # | 项 | 工作量 | 收益 |
|---|---|---|---|
| A1 | RiskClass 数据化权限 | 1 周 | 权限可扩展 |
| A2 | Provider 抽象 + Token 归一化 | 1-2 周 | 多厂商无缝 |
| A5 | Persona Manifest | 1 周 | 用户可定制 |
| A6 | 工具并发执行 | 3-5 天 | 多工具并发加速 |
| A3 (完整) | Hermetic E2E mock backend | 1-2 周 | 脱网测试 |
| U7 | Right Rail + artifact viewer | 2-3 周 | AI coworker 感 |
| U9 | Live-dot/Attn-badge 分离 | 1 周 | 视觉语义清晰 |
| U10 | Sticky-unlock chips | 3-5 天 | 渐进披露 |
| U11 | Drained toast | 2-3 天 | 消失可见 |
| U12 | Two-step delete | 1-2 天 | 防误操作 |
| U8 | Humanized tool titles | 1-2 天 | 人性化 |

**Phase 2 交付物**：11 个 PR，按依赖顺序：A1 → A2 → A5 → A6 → A3 → U7。

---

### Phase 3：重大特性（2+ 月）

| # | 项 | 工作量 | 收益 |
|---|---|---|---|
| A4 | Suspend-resume agent | 2-3 周 | 长任务零空闲 |
| A10 | UI Mocks 工作流 | 持续 | 减少返工 |
| A11 / U14 | 本地 STT sidecar + voice UI | 1-2 月 | 差异化 |

**Phase 3 交付物**：3 个重大特性分支，独立演进。

---

## 6. 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| **Phase 1 的 shared primitives 替换影响面广** | 视觉回归 | 分 PR 渐进替换 + 视觉回归测试 |
| **Phase 2 的 Right Rail 改动 Layout 大** | 影响所有 page | 先做 mock PR 评审 |
| **Phase 2 的 Provider 抽象破坏现有 ChatService** | 需要大重构 | 保留旧 adapter 作 fallback，双轨并行 1 周 |
| **Phase 3 的 STT sidecar 跨平台打包** | Windows/Mac/Linux 三平台 whisper 二进制 | 先 Mac only，渐进加 Windows/Linux |
| **Win7 LTS 兼容性** | Py3.8 不支持某些新语法 | 所有后端改动走 `scripts/py38_compat_rewrite.py` 验证 |

---

## 7. 验收标准

### Phase 0 验收
- [ ] 主题切换无闪烁（Lighthouse 跑首帧颜色正确）
- [ ] `grep -r 'text-gray-500\|bg-red-50\|border-gray-200' src/shared/ui src/widgets src/pages` 无结果
- [ ] Sidebar 崩溃不影响 chat 页
- [ ] 切换 session 后 ChatInput 内容正确恢复

### Phase 1 验收
- [ ] `Tabs / Popover / Tooltip / DropdownMenu / Select / Switch / Dialog` 7 个 primitive 在 `src/shared/ui/` 中
- [ ] Settings 页 URL 可 deep-link（`/settings/models`）
- [ ] Sidebar 折叠后 hover 边缘 4px 可唤出
- [ ] Command palette 每行显示 ⌘1-9 hint
- [ ] CI E2E 测试目录统一为 `e2e/` 三分类

### Phase 2 验收
- [ ] `RiskClass` 枚举在 `backend/domain/risk.py`，每个 tool 注册时声明
- [ ] `ProviderRouter` 在 `backend/application/services/`，3+ adapter 实现
- [ ] Persona manifest 在 `backend/adapters/out/skill/personas/`，可热加载
- [ ] Hermetic E2E 完全脱网跑通（CI 不依赖 LLM API）
- [ ] Right Rail 渲染 artifact 预览（Markdown + 代码 + PDF）

### Phase 3 验收
- [ ] Agent suspend-resume 跑通：`sleep_for(10s)` → scheduler 唤醒恢复
- [ ] Voice dictation 至少跑通 Mac 平台（whisper-rs 集成）

---

## 8. 不在本方案范围

- ❌ 替换 Electron 为 Tauri（OpenWorker 用 Tauri 不是 Sage 要学的点）
- ❌ 引入 shadcn/ui（继续用 Radix，与既有 Tailwind 一致）
- ❌ 删除 FSD 分层（Sage 的护城河）
- ❌ 删除六边形架构约束（Sage 领先 OpenWorker 的点）
- ❌ 删除 Win7 LTS 双分支策略（到 2027-12-13 EOL 前维持）
- ❌ 重写 i18n 框架（typed zh/en 已成熟）
- ❌ 引入新的状态管理库（Zustand + React Query 已够）

---

## 9. 关键参考文件清单

| 主题 | 文件路径 |
|---|---|
| RiskClass 定义 | `/home/fz/project/openworker/coworker/risk.py` |
| Permission 引擎 | `/home/fz/project/openworker/coworker/permissions.py` |
| RiskOverride | `/home/fz/project/openworker/coworker/overrides.py` |
| Provider 抽象 | `/home/fz/project/openworker/coworker/providers/` |
| UsageChip UI | `/home/fz/project/openworker/surfaces/gui/src/components/Composer.tsx:572-695` |
| Hermetic E2E | `/home/fz/project/openworker/surfaces/gui/e2e/` |
| Live smoke | `/home/fz/project/openworker/surfaces/gui/e2e-live/` |
| Suspend-resume | `/home/fz/project/openworker/coworker/selfwake.py` |
| Scheduler | `/home/fz/project/openworker/coworker/automation/scheduler.py` |
| Persona manifest | `/home/fz/project/openworker/coworker/personas/builtin/` |
| Humanize 引擎 | `/home/fz/project/openworker/surfaces/gui/src/humanize.ts` |
| ApprovalCard 双密度 | `/home/fz/project/openworker/surfaces/gui/src/components/ApprovalCard.tsx` |
| Hover-peek sidebar | `/home/fz/project/openworker/surfaces/gui/src/App.tsx:240-284` + `styles.css:119-140` |
| ⌘1-9 跳转 | `/home/fz/project/openworker/surfaces/gui/src/components/SearchModal.tsx` |
| Right Rail | `/home/fz/project/openworker/surfaces/gui/src/components/RightRail.tsx` |
| Live-dot vs Attn-badge | `/home/fz/project/openworker/surfaces/gui/src/components/Sidebar.tsx` |
| Drained toast | `/home/fz/project/openworker/surfaces/gui/src/App.tsx:1204-1240` |
| Pre-paint theme | `/home/fz/project/openworker/surfaces/gui/index.html` |
| Semantic color ladder | `/home/fz/project/openworker/surfaces/gui/src/styles.css:16-78` |
| Fixed-height wizard | `/home/fz/project/openworker/surfaces/gui/src/components/Onboarding.tsx` |
| Release stable-name | `/home/fz/project/openworker/.github/workflows/release.yml` |
| STT Rust crate | `/home/fz/project/openworker/stt/` |
| UI mock 范例 | `/home/fz/project/openworker/ui-mocks/redesign.html` |

---

## 10. 总结

**Sage 的优势（保持）**：六边形 + FSD 严格分层、140+ token + 11 主题、typed i18n、@xyflow 知识图谱、Win7 LTS 双分支。

**Sage 的短板（本方案补）**：工具权限数据化、LLM Provider 抽象、shared UI primitives、错误边界分层、Hermetic E2E、agent suspend-resume、3 列布局、hover-peek sidebar、pre-paint theme、语义颜色阶梯。

**执行节奏**：Phase 0（1 周速赢）→ Phase 1（2-4 周基建）→ Phase 2（1-2 月架构升级）→ Phase 3（2+ 月重大特性）。**每个 Phase 结束做一次回顾**，根据实际收益调整后续优先级。
