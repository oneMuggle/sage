# ZCode 启发的 Sage 系统化优化设计

> 日期：2026-09-21
> 状态：待用户审阅
> 路径：方案 A（渐进式四阶段）
> 输出形式：每阶段一个独立 PR + cherry-pick 到 release/win7

## 1. 背景与目标

### 1.1 触发原因

对 `/home/fz/project/ZCode` 项目（ZCode v3.14.0，pnpm workspaces 多包架构）进行横向对比后，
发现 Sage 在以下 4 个维度存在系统性差距：

| 维度 | ZCode 现状 | Sage 现状 | 差距级别 |
|---|---|---|---|
| 架构治理 | `architecture-policy.yaml` + 模块声明 + 全局规则 + 静态检查脚本 | `src/` 仅前端 FSD ESLint 规则；`backend/` 和 `electron/` 无统一治理 | **大** |
| 设计系统 | 30KB 的 `DESIGN.md` + 强制 `text-ui-*` 标尺 + 语义颜色 + 圆角阶梯 | 无 DESIGN.md；`text-base` 与 `text-[13px]` 散乱；a11y 缺口（[[sage-settings-toggle-a11y-gap]]） | **大** |
| 领域词汇 | 13KB 的 `CONTEXT.md`（Plugin Store 领域词汇表） | 散落各处；`WorkingMemory` 非单例等教训频发 | **中** |
| 工程化工具 | `knip` + `dep:refs` + `count-lines` + `architecture-context` | ruff + ESLint + tsc + pytest（基础健全，但缺依赖反查和架构上下文生成） | **中** |

### 1.2 目标

通过**四阶段渐进式落地**，把 ZCode 的工程化优势移植到 Sage，而不破坏：
- 双分支（main + release/win7）的长期共存
- 现有功能的稳定性（Office CRUD、Arena、Scheduler、MCP、Plugin 等子系统）
- Python 3.8 + Chromium 106 的兼容性基线

### 1.3 范围与约束

- **范围**：4 个阶段（架构治理、设计系统、领域词汇+日志、工程化工具）
- **路径**：渐进式（每阶段独立 PR + cherry-pick win7）
- **不在此设计范围内**：
  - 远程/本地链路分离（ZCode 有此概念，但 Sage 当前是纯本地架构，无需引入）
  - 插件商店系统（Sage 已有 plugins 子系统，ZCode 的 Plugin Store 词汇表不直接适用）
  - Python 3.8 → 3.10 升级（双分支约束禁止）

## 2. 四阶段总体方案

```
阶段 1: 架构治理 (Architecture Governance)
  ├── 引入 architecture-policy.yaml（静态规则：最大行数、循环引用、模块边界）
  ├── scripts/architecture-check.mjs 护栏（集成到 PR / pre-push）
  └── 引入 knip.json 清理死导出与未用依赖

阶段 2: 设计系统与 Token (Design System & Tokens)
  ├── 建立 DESIGN.md（规范：text-ui-* 标尺、语义色彩、圆角阶梯）
  ├── tailwind.config.js 引入 text-ui-* scale 与语义颜色变量
  └── 渐进迁移首批组件（Settings Toggle、Card、Button），修补 a11y 缺口

阶段 3: 领域词汇表与日志标准化 (Glossary & ServiceLogger)
  ├── 建立 docs/GLOSSARY.md（统一 Office、Schedule、Arena、Memory 术语）
  ├── Python backend / Electron / UI 统一 serviceLogger / createLogger 模式
  └── 明确"单一状态所有者"原则，根绝多写路径与串味

阶段 4: 工程化工具链 (Engineering Tools)
  ├── scripts/dep-refs.mjs（符号依赖反查）
  └── scripts/architecture-context.mjs（受控上下文生成）
```

每阶段的详细设计见 §3 ~ §6。

## 3. 阶段 1：架构治理

### 3.1 `architecture-policy.yaml`

借鉴 ZCode 的 `architecture-policy.yaml`，针对 Sage 的双语言技术栈（Electron + Python）定义：

```yaml
version: 1

global:
  maxFileLines: 800       # 与 common/coding-style.md 保持一致；存量超标文件逐步收敛
  maxContractLines: 300   # contract / interface 类文件
  forbidCycles: true      # 禁止循环依赖
  forbidDeepImports: true # 禁止深层导入（只 import public entrypoints）
  managedOnly: true       # 所有模块必须在 policy 中声明

# 前端模块划分（对齐现有 FSD 结构：src/{app,processes,pages,widgets,features,entities,shared}）
modules:
  - id: frontend-shared
    roots: [src/shared]

  - id: frontend-entities
    roots: [src/entities]
    requires: [frontend-shared]

  - id: frontend-features
    roots: [src/features]
    requires: [frontend-shared, frontend-entities]

  - id: frontend-widgets
    roots: [src/widgets]
    requires: [frontend-shared, frontend-entities, frontend-features]

  - id: frontend-pages
    roots: [src/pages]
    requires: [frontend-shared, frontend-entities, frontend-features, frontend-widgets]

  # 后端分层护栏（与 import-linter 结合）
  - id: backend-domain
    roots: [backend/domain]

  - id: backend-ports
    roots: [backend/ports]
    requires: [backend-domain]

  - id: backend-application
    roots: [backend/application]
    requires: [backend-domain, backend-ports]

  - id: backend-adapters
    roots: [backend/adapters]
    requires: [backend-domain, backend-ports, backend-application]

  - id: backend-api
    roots: [backend/api]
    requires: [backend-domain, backend-ports, backend-application]
```

### 3.2 `scripts/architecture-check.mjs`

纯 Node.js 脚本（零依赖，保证 win7 CI 与本地开发开箱即用）。

**功能**：
1. 统计文件行数，输出超过 `maxFileLines` 的违规文件清单。
2. 检测跨层深层导入（例如 `frontend-shared` 直接 import `frontend-pages` 内的实现）。
3. 基于 `architecture-policy.yaml` 检查模块声明是否齐全。

**集成点**：
- `package.json` 新增 `scripts`:
  ```json
  {
    "architecture:check": "node scripts/architecture-check.mjs check",
    "architecture:check:changed": "node scripts/architecture-check.mjs check --changed",
    "architecture:report": "node scripts/architecture-check.mjs report",
    "verify:pre-push": "npm run lint && npm run architecture:check:changed"
  }
  ```
- 首次运行建立 `architecture-baseline.json`（存量违规清单），后续仅检查新增违规。
- CI 中 `--changed` 模式只检查当前 PR 变更的文件，避免阻塞存量问题。

### 3.3 `knip.json` 引入

针对 `src/` 与 `electron/` 的未使用导出、未使用依赖扫描：

```json
{
  "entry": ["src/main.tsx", "electron/main.ts"],
  "project": ["src/**/*.{ts,tsx}", "electron/**/*.ts"],
  "ignoreBinaries": ["eslint"],
  "rules": {
    "exports": "warn",
    "dependencies": "warn"
  }
}
```

**集成点**：
- `package.json` 新增 `"knip": "knip"` 脚本。
- 首阶段配置为 `warn` 模式（只告警不阻断），清理冗余后逐步升级为 `error`。

### 3.4 双分支兼容

- 所有脚本使用纯 Node.js 或 Python stdlib，无需新增 npm 依赖。
- `architecture-policy.yaml` 和 `architecture-baseline.json` 为纯文本/JSON 文件，cherry-pick 零冲突。
- Python 3.8 / Chromium 106 兼容性无影响（脚本不参与运行时）。

## 4. 阶段 2：设计系统与 Token

### 4.1 引入根目录 `DESIGN.md`（契约文档）

借鉴 ZCode 的核心约束，建立四条不可动摇的最高优先级约束：

1. **统一字体标尺 (`text-ui-*`)**：所有操作界面文本只能采用 `text-ui-xl`、`text-ui-lg`、`text-ui-base`、`text-ui-caption`、`text-ui-sm`、`text-ui-xs`。代码预览/Diff 等特殊视口允许保持等宽字号。
2. **基准字号与缩放**：由设置中的 `--ui-font-size`（默认 14px）驱动，**严禁修改根 `html` 的 `font-size`**（避免破坏第三方库如 CodeMirror/Monaco 的渲染）。
3. **颜色语义阶梯**：区分 Background、Card、Surface、Popover/Menu，禁止直接用 `text-white/60` 或 `border-black/10` 等临时拼凑色。
4. **圆角阶梯标准（Radius Nesting）**：最外层 rounded-xl，内部递减 rounded-lg → rounded-md → rounded-sm。输入框/弹窗特批 rounded-2xl。

**DESIGN.md 章节结构**（与 ZCode 对齐）：
- Product Character（产品定位：calm、dense、operational）
- Theme Modes（System/Light/Dark）
- Color Palette（语义颜色）
- Typography（`text-ui-*` 标尺）
- Spacing（4px 基础单元）
- Radius（容器阶梯）
- Components（Buttons / Inputs / Cards / Menus / Dialogs）
- Elevation and Depth（背景对比优先于阴影）
- Motion（快速、低戏剧）

### 4.2 `tailwind.config.js` 扩展

在现有配置中增加基于 CSS 变量的配置，无缝继承 Sage 现有的主题切换：

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      fontSize: {
        'ui-xl': 'calc(var(--ui-font-size, 14px) + 4px)',     // 18px
        'ui-lg': 'calc(var(--ui-font-size, 14px) + 2px)',     // 16px
        'ui-base': 'var(--ui-font-size, 14px)',               // 14px (默认正文)
        'ui-caption': 'calc(var(--ui-font-size, 14px) - 1px)',// 13px (紧凑说明)
        'ui-sm': 'calc(var(--ui-font-size, 14px) - 2px)',     // 12px (次要信息)
        'ui-xs': 'calc(var(--ui-font-size, 14px) - 4px)',     // 10px (快捷键徽标)
      },
      colors: {
        'ui-bg': 'var(--color-background)',
        'ui-card': 'var(--color-card)',
        'ui-surface': 'var(--color-surface)',
        'ui-popover': 'var(--color-popover)',
        'ui-border': 'var(--color-border)',
        'ui-foreground': 'var(--color-foreground)',
        'ui-subtle': 'var(--color-foreground-subtle)',
      }
    }
  }
}
```

**`src/index.css` 补充**：
```css
:root {
  --ui-font-size: 14px;

  /* Light theme defaults */
  --color-background: #ffffff;
  --color-card: #f8f9fa;
  --color-surface: #f3f4f6;
  --color-popover: #ffffff;
  --color-border: #e5e7eb;
  --color-foreground: #111827;
  --color-foreground-subtle: #6b7280;
}

[data-theme='dark'] {
  --color-background: #0f172a;
  --color-card: #1e293b;
  --color-surface: #334155;
  --color-popover: #1e293b;
  --color-border: #334155;
  --color-foreground: #f1f5f9;
  --color-foreground-subtle: #94a3b8;
}
```

### 4.3 首批典型组件迁移

- **Settings Toggle 组件修复**：结合 [[sage-settings-toggle-a11y-gap]]（跨 5 个设置 Tab 的 Toggle 缺 `role="switch"` 和 `aria-checked`），使用标准化 Token 重构该组件，一次性解决 a11y 缺陷。
- **Card / Button 统一样式**：统一 `src/shared/components/` 中的 Button 和 Card 变体，消除各业务页面自造样式的情况。

### 4.4 双分支兼容

- `text-ui-*` 使用标准 CSS 变量 + `calc()`，Chromium 106 已完全支持。
- 设计 Token 仅影响视觉层，无运行时依赖，cherry-pick 到 win7 零风险。
- Win7 LTS 分支继续维护自己的主题变量（如需微调颜色值）。

## 5. 阶段 3：领域词汇表 + 日志标准化 + 状态所有者

### 5.1 领域词汇表 `docs/GLOSSARY.md`

借鉴 CONTEXT.md 的"是什么 / 不是什么 / 常见误读"范式，为 Sage 的领域术语建统一表：

| 术语 | 正确定义 | 常见误读/禁用词 |
|---|---|---|
| **Office** | 用户文档工作区（Office CRUD 的抽象） | 不要与 Office Template / Office Tool 混淆 |
| **Office Tool** | 工具集中的具体工具（`office_read` / `office_write` / `office_list` / `office_archive`） | 不要简称 "office" |
| **Sandbox Tool** | 由 profile 白名单暴露给 agent 的工具集合 | 不是所有内置工具都是 sandbox tool |
| **Agent Profile** | 定义 agent 可见工具集 + 系统 prompt 的配置对象 | 不要与 agent 混淆（agent 是运行时实例） |
| **Scheduler** | `SchedulerService` + `register_evolution_task`（apscheduler 3.10.4 驱动） | 不要叫 cron；`cron.py` 已删除 |
| **Working Memory** | `WorkingMemory` 实例——**非单例**，必须通过 `agent.memory_manager.working` 共享 | 不能直接 `WorkingMemory()` 新建实例 |
| **Arena** | 模型评测池（CDP + 账户池） | 默认已隐藏（PR #1347/#1349），不是主路径 |
| **MCP Server** | 外部进程通信协议实例 | 不要与 builtin tool 混淆 |
| **Lockstep** | 双分支版本号同步（main + release/win7） | 仅对 `package.json` + `CHANGELOG`；不应用于功能性改动 |
| **Cherry-pick** | 单/批 commit 跨分支搬运 | 不用 `merge release → develop`（会带入 release 元数据） |

### 5.2 日志标准化（`serviceLogger` 模式）

借鉴 ZCode 的 `createServiceLogger(scope)`，为 Sage 建立三级统一规范：

| 层级 | 工具 | 文件位置 | 语义 |
|---|---|---|---|
| Python backend | `create_service_logger(scope: str)` | `backend/loggers.py`（新建） | 替代零散 `print` / `logging.debug()` |
| Electron main | `createLogger(scope)` | `electron/loggers.ts`（新建） | 替代 `electron-log` 直接调用 |
| Frontend | `createLogger(scope)` | `src/shared/logger.ts`（新建） | 替代 `console.log` |

**四级语义定义**（全栈对齐）：

| 级别 | 用途 | 落盘策略 |
|---|---|---|
| `debug` | 协议原始数据、流式 chunk、逐条工具更新 | 生产环境**不落盘** |
| `info` | 进程生命周期、权限结果、一次性初始化事件 | 落盘 |
| `warn` | 可恢复异常（如降级到 fallback） | 落盘 |
| `error` | 崩溃、握手失败、鉴权丢失等不可恢复错误 | 落盘 + 告警 |

**护栏**：
- Frontend: ESLint `no-console: ['error', { allow: ['warn', 'error'] }]`
- Backend: ruff T20（禁止 `print`）+ TID252（禁止裸 `logging`）
- Electron: ESLint `no-console: ['error', { allow: ['warn', 'error'] }]`

### 5.3 状态所有者原则

写入 `docs/technical/15-state-ownership.md`（新章节），三条铁律：

1. **单一状态所有者**：每个状态有且仅有一个写入路径，禁止重复状态或多条写入路径。
   - 反例：[[sage-working-memory-not-singleton]] —— `WorkingMemory()` 新建空实例导致 context_reset 串味。
2. **接口 + 依赖方向 + 事件顺序 + 幂等边界**：UI 组件通过 hooks 访问服务，不直接调用实现；backend 服务层必须定义 ports（接口），adapters 实现。
3. **跨模块事件传播**：状态变更通过事件广播，而不是直接修改消费者状态。
   - 示例：后端状态变更时通过 WebSocket 推送事件，前端通过 hooks 订阅事件并更新 Zustand store。

### 5.4 双分支兼容

- `docs/GLOSSARY.md` 为纯 Markdown，cherry-pick 零冲突。
- `loggers.py` / `loggers.ts` 使用 Python stdlib + 轻量 JS 封装，无新依赖。
- `docs/technical/15-state-ownership.md` 为 docs-only 改动，可直接 cherry-pick。

## 6. 阶段 4：工程化工具链

### 6.1 `scripts/dep-refs.mjs`（依赖反查）

借鉴 ZCode 的 `dep:refs` 命令，为 Sage 建立：

```bash
node scripts/dep-refs.mjs --list-exports backend/office/tool_service.py
# 输出：哪些文件 import 了 tool_service 的哪些 symbol
#
# 示例输出：
# backend/office/tool_service.py
#   - OfficeReadTool    → imported by backend/office/router.py, backend/tools/registry.py
#   - OfficeWriteTool   → imported by backend/tools/registry.py
#   - process_document  → imported by backend/office/worker.py
```

- 基于 AST 分析：
  - Python: `ast` 模块（零依赖）
  - TypeScript: `typescript` 的 Compiler API（已安装）
- 用于理解"改了 X 会影响 Y"，避免意外破坏。

### 6.2 `scripts/architecture-context.mjs`（受控上下文生成）

为 AI agent（如 Claude Code 子 agent）生成某个模块的"只读上下文包"：

```bash
node scripts/architecture-context.mjs frontend-features
# 输出：
# Module: frontend-features
# Roots: src/features
# Requires: frontend-shared, frontend-entities
# Public entrypoints:
#   - src/features/chat/index.ts
#   - src/features/settings/index.ts
# Key files (non-private):
#   - src/features/chat/ChatView.tsx (142 lines)
#   - src/features/settings/SettingsPage.tsx (98 lines)
```

- 与 `architecture-policy.yaml` 联动：只列出 public entrypoints 和声明的依赖。
- 用于解决 agent 被无关文件淹没的问题。

### 6.3 `scripts/count-lines.sh`（文件行数统计）

追踪架构治理阶段的成效：

```bash
bash scripts/count-lines.sh
# 输出：
# Files exceeding maxFileLines (800):
#   backend/agent/tools.py          923 lines  (+123 over limit)
#   electron/main.ts                847 lines  (+47 over limit)
#
# Distribution:
#   0-200 lines:    142 files  (68%)
#   200-400 lines:   45 files  (22%)
#   400-800 lines:   18 files  (8%)
#   800+ lines:       5 files  (2%)
```

- 集成到 CI（`.github/workflows/ci.yml` 新增 `count-lines` job），追踪"超标文件数"随时间下降。
- 用于评估架构治理的进展。

### 6.4 双分支兼容

- 所有脚本为纯 Node.js / Python stdlib，无新依赖，win7 零冲突。
- 脚本本身不参与运行时，cherry-pick 到 win7 无风险。

## 7. 成功标准

### 7.1 阶段 1（架构治理）

- [ ] `architecture-policy.yaml` 定义所有模块（前端 FSD + 后端 DDD + Electron）。
- [ ] `scripts/architecture-check.mjs` 在 CI 中跑通（`--changed` 模式）。
- [ ] `knip.json` 配置完成，存量未使用导出/依赖清理 50% 以上。
- [ ] 无新增超过 800 行的文件。

### 7.2 阶段 2（设计系统）

- [ ] `DESIGN.md` 完成（覆盖 Product Character / Theme / Color / Typography / Radius / Components）。
- [ ] `tailwind.config.js` 扩展 `text-ui-*` 与语义颜色 Token。
- [ ] Settings Toggle 组件 a11y 修复（`role="switch"` + `aria-checked`）。
- [ ] 新组件优先采用 Token（通过 ESLint 规则或人工 review 约束）。

### 7.3 阶段 3（领域词汇 + 日志）

- [ ] `docs/GLOSSARY.md` 完成（覆盖 10 个核心术语：Office / Office Tool / Sandbox Tool / Agent Profile / Scheduler / Working Memory / Arena / MCP Server / Lockstep / Cherry-pick）。
- [ ] Python backend / Electron / Frontend 各有 `createLogger(scope)` 模式。
- [ ] `docs/technical/15-state-ownership.md` 完成（三条铁律 + 示例）。
- [ ] 存量 `print` / `console.log` 清理 80% 以上。

### 7.4 阶段 4（工程化工具）

- [ ] `scripts/dep-refs.mjs` 可运行，输出符号级依赖关系。
- [ ] `scripts/architecture-context.mjs` 可运行，生成模块上下文。
- [ ] `scripts/count-lines.sh` 集成到 CI，追踪文件行数分布。

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| **Cherry-pick 冲突**：`tailwind.config.js` / `package.json` 在 win7 分支可能有版本差异 | 阶段 2、4 | 每阶段 PR 后立即 cherry-pick，手动解决冲突并测试 |
| **存量违规过多**：`architecture-check` 首次运行可能报大量违规 | 阶段 1 | 使用 `architecture-baseline.json` 豁免存量，仅检查新增违规 |
| **设计 Token 迁移范围过大**：一次性迁移所有组件工作量巨大 | 阶段 2 | 首批只迁移 Settings Toggle + Card + Button，其他组件渐进迁移 |
| **日志清理遗漏**：`print` / `console.log` 散落在多处 | 阶段 3 | 使用 ruff T20 + ESLint `no-console` 自动检测，分批次清理 |
| **双分支同步延迟**：阶段间依赖可能导致 win7 分支落后 | 全阶段 | 每阶段 PR 合并后立即 cherry-pick，不等下一阶段 |

## 9. 附录

### 9.1 ZCode 参考文件

- `architecture-policy.yaml`：模块声明与全局规则
- `DESIGN.md`：设计系统规范（30KB）
- `CONTEXT.md`：领域词汇表（13KB）
- `AGENTS.md`：工作流与命令表
- `scripts/architecture/architecture-check.mjs`：静态检查脚本
- `scripts/dep-refs.mjs`：依赖反查工具

### 9.2 Sage 现状文件

- `eslint.config.js`：前端 FSD 层级规则（PG1.13）
- `backend/pyproject.toml`：后端 Python 配置
- `docs/technical/`：14 章节技术文档
- `PHILOSOPHY.md`：设计哲学（2026-06）
- `PARITY.md`：对齐标准（2026-06）

### 9.3 相关 Memory 条目

- [[sage-settings-toggle-a11y-gap]]：Toggle 组件 a11y 缺陷
- [[sage-working-memory-not-singleton]]：WorkingMemory 非单例教训
- [[sage-pr895-pr1031-sandbox-tools-cherry-pick]]：Sandbox Tool 白名单教训
- [[sage-scheduler-evolution-merged]]：Scheduler 演进历史
- [[sage-pr1030-arena-automation-merged]]：Arena 自动化子系统

---

**下一步**：用户审阅本设计文档 → 批准后调用 `writing-plans` skill 生成分阶段实施计划。
