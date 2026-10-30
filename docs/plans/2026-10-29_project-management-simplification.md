# 项目管理体验优化：从「治理工作台」到「AI 项目助手」

> 日期：2026-10-29
> 状态：实施中（P0 完成；P1 后端 bootstrap + 前端面板完成；P2 治理页 6→3 Tab / 高级操作折叠 / 侧边栏文案去术语完成；P3 顾问上下文与证据输出完成，动作执行与 Wiki 后台任务/无 LLM 骨架待续）
> 分支：`feat/project-management-ux`
> 参考：Cursor Projects / Windsurf Cascade / GitHub Copilot Workspace / Claude Code `/init` / DeepWiki

---

## 1. 背景与目标

### 1.1 用户反馈

1. 项目列表没有类似 VSCode 的右键菜单，无法直接打开项目文件夹；
2. 项目管理太复杂：里程碑、约束、生命周期、L2/L3/L4 等概念让用户不知从何下手；
3. 新项目没有自动初始化建议，也不会建议启用 Git 追踪；
4. AI 生成 Wiki 文档功能无法使用；
5. AI 顾问的建议与当前项目无关、不可执行。

### 1.2 根因判断

这不是「功能缺失」，而是**功能过载 + 内部架构外泄 + 关键链路断裂**三件事叠加：

- 治理概念（L1–L5 五层上下文、14 个「转 L2/L3/L4」动作、6 个治理 Tab）完整暴露给普通用户；
- 新项目路径有 4 条，只有向导会做分析，而分析结果大部分被丢弃；
- Wiki 生成代码层面只支持 Python，且在 Sage 这类 TypeScript 项目上直接扫不到文件；
- 顾问只看「里程碑数量 + 画像条数」，自然只能给出泛泛建议。

**目标**：普通用户登记项目后，**30 秒内开始第一次有效会话**；所有治理能力保留，但默认隐藏、按需出现、由 AI 主动建议。

### 1.3 成功指标

| 指标 | 现状 | 目标 |
|------|------|------|
| 登记 → 首次会话耗时 | 多步、易迷路 | ≤ 30 秒（3 次点击内） |
| 新项目 AI 初始化完成率 | 不可观测 | ≥ 60% |
| Wiki 生成成功率（TS/Python 项目） | TS 项目基本为 0 | ≥ 90%（含无 LLM 骨架降级） |
| 顾问建议被采纳率 | 无埋点 | ≥ 30% |
| 默认界面中的 L1–L5 术语 | 大量 | 0 处（仅高级模式） |

---

## 2. 现状诊断（代码证据）

### 2.1 信息架构：同一件事有三个入口

- `/projects` 工作台、侧边栏展开面板、`/projects/governance/:projectId` 三处都渲染项目概览/资料/规则；
- 治理页有 6 个 Tab（`src/pages/ProjectGovernance.tsx:504-522`），注释与审计函数却分别写 7 个和 5 个；
- 概览状态卡内塞了约 14 个 L2/L3/L4 转换按钮（`src/features/project-type/ProjectOverviewWidgets.tsx:206-523`），同样的「+L2/+L3/+L4/+里程碑」动作在 6 个组件里重复出现；
- 「L2 元数据」在「基本信息」Tab，「L2 约束」在「规则与约束」Tab，用户无法建立稳定的心智模型。

### 2.2 新项目创建：分析很贵，结果被丢

- 4 条入口（向导 / 列表 `+` / 拖拽 / 命令面板）中只有面向导会调 `POST /projects/analyze`；其余三条只做 `register → open`；
- 向导第 2 步拿到的 `sageMdDraft`、`stageRecommendation`、`suggestedRules[].content`、`gitStats` 全部没有落库（`src/features/project-type/ProjectCreationWizard.tsx:193-295`）；
- 后端只检测 `.git` 是否存在，**全库没有任何 `git init` 能力**（`backend/data/project_repo.py:154-158`）；
- 向导提供 `vcsMode = 'none'`，但后端只接受 `git|builtin`，选择会在静默 422 后失效（`project_schemas.py:51-54`）；
- 「一键初始化」是全有全无开关；且脚手架先导入类型级默认规则包，再叠加用户勾选的规则包，**不去重**（`project_archetype_scaffold.py:207-270`）。

### 2.3 AI Wiki：三个硬伤导致「不能用」

1. `scan_files` 默认语言是 `{"python"}`（`backend/services/project_wiki_generator.py:161-162`），
   前端 `wikiScanFiles` 也硬编码 `languages ?? 'python'`（`src/shared/api/projectApi.ts:1037`）；
2. `extract_symbols` 只支持 Python AST，其他语言直接跳过（`project_wiki_generator.py:245-273`）；
3. `generate()` 调用 `scan_files` 时不传语言，同样落到 Python-only；
   因此 TypeScript/React 项目预览为 0 文件、生成报「未找到源文件」。

附加问题：LLM 未配置时端点直接 503；增量更新是 TODO（`pages_updated` 恒为 0）；面板埋在概览页很靠后的位置；失败原因只以一行小字出现。

### 2.4 AI 顾问：输入太贫瘠，输出不可执行

`ProjectAdvisor._collect_data` 只收集项目名/类型/阶段/描述、里程碑计数、画像条数（`backend/services/project_advisor.py:179-234`）。没有 Git 状态、技术栈、最近会话、约束/资料数量、文件结构。建议 schema 只有 `{action: 文本, reason, priority}`，前端无法一键执行；30 分钟缓存也没有基于仓库变化的失效机制。

### 2.5 右键菜单：没有基础设施

`src/` 全库没有 `onContextMenu`；工作台的「···」菜单是自定义下拉，动作是占位实现（「添加里程碑」创建固定标题的假里程碑，「添加项目规则」创建固定内容）。Electron 侧也没有任何「打开项目文件夹」IPC，只有 Office 文件专用的 `shell.openPath`。

### 2.6 分类法漂移（复杂度放大器）

- 阶段枚举：前端 business 3 个，后端 5 个；`MilestoneEditor` 模板又用另一套 stage id；
- 约束类别：摘要组件 16 个中文标签、编辑器预设 7 个 key、一键生成器又造出 7 个未映射英文类别；
- 未分类项目在治理页显示 business、在工作室默认 coding、徽标显示「未分类」。

这些漂移让同一份数据在不同界面「隐身」，进一步放大了「不知道怎么办」。

---

## 3. 设计原则

1. **项目 = 文件夹 + 会话 + AI 上下文**。除文件夹外没有任何必填治理项。
2. **AI 先建议，用户一键采纳**。参考 Claude Code `/init`、Cursor Generate Rules：扫描 → 生成建议 → 预览 → 应用。
3. **内部架构不外泄**。L1–L5 是注入实现，不是用户概念；默认界面只说「项目说明 / 项目规则 / 项目资料 / AI 记忆」。
4. **每条 AI 建议都必须可执行**。建议 = 证据 + 理由 + 动作按钮，而不是一段文案。
5. **渐进披露**。默认一屏只回答「我现在该做什么」；高级能力收进「高级设置」。
6. **单一事实源**。阶段、类别、蓝图目录等分类法只保留一份注册表。

---

## 4. 目标体验

### 4.1 项目主页（默认简单模式）

```
┌ 项目 sage   [代码工程] [进行中]                         …  ┐
│ /home/fz/project/sage                                      │
│                                                            │
│ [▶ 继续会话]   [✨ AI 初始化检查]   [📚 生成项目文档]       │
│                                                            │
│ ┌ AI 建议（基于最近变化）────────────────────────────────┐ │
│ │ ⚠ 12 个文件未提交          [创建快照]  [忽略 7 天]     │ │
│ │ ✨ 检测到 FastAPI + React   [补充项目规则]             │ │
│ │ 📚 Wiki 已 18 天未更新      [更新文档]                 │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                            │
│ 会话 (12)                                                  │
│  · 修复 401 授权 ...                                       │
│  · 项目管理体验优化 ...                                     │
│                                                            │
│ ▸ 项目知识   规则 5 · 资料 3 · AI 记忆 8                   │
│ ▸ 里程碑     2 / 5 完成                                    │
│ ▸ 高级设置                                                 │
└────────────────────────────────────────────────────────────┘
```

- 状态徽标由系统推导：`新项目`（无会话）/ `进行中`（7 天内有活动）/ `停滞`（14 天无活动）/ `已归档`；
- 「项目知识」「里程碑」默认折叠，且里程碑为空时显示「让 AI 根据项目生成里程碑」而不是空列表；
- 「高级设置」抽屉包含：项目类型、SAGE.md 编辑、五层上下文预算、允许路径、导出、VCS 模式。

### 4.2 项目列表右键菜单（VSCode 对齐）

| 菜单项 | 行为 | 说明 |
|---|---|---|
| 打开项目 | 复用最近会话/新建会话 | 默认双击行为 |
| 新建会话 | 在项目内新建并进入 | |
| 在文件管理器中显示 | `shell.showItemInFolder` / `openPath` | 核心诉求 1 |
| 在终端中打开 | 以项目路径为 cwd 打开终端 | 可选 P0.5 |
| AI 初始化 / 重新分析 | 打开初始化建议面板 | |
| 项目设置… | 打开高级设置 | 替代当前「项目设置」直达治理页 |
| 复制路径 | 现有能力 | |
| 移除项目 | 两步确认 | 不动磁盘 |

同时支持 `Shift+F10` / 菜单键，保证键盘可达。工作台与侧边栏共用同一菜单组件。

### 4.3 新项目 AI 初始化（任何入口都收敛到同一流程）

1. **登记即分析**：任何入口 `register` 成功后，后台立即跑确定性扫描（不调 LLM），项目页展示分析中骨架；
2. **建议清单**：确定性扫描 +（可用时）LLM 生成：
   - 项目类型 / 子类型 / 技术栈（附检测依据）；
   - `SAGE.md` 草稿（写入前可预览 diff）；
   - 推荐规则 3–8 条（每条带「为什么推荐」与命中的文件证据）；
   - 推荐里程碑（可全部不选）；
   - Git 追踪建议：无 `.git` 时建议 `git init`（需显式勾选），有 `.git` 时展示分支/未提交数并建议首次快照；
   - 项目文档（Wiki）生成入口与预估页数；
   - 首次会话预填 prompt（如「先帮我了解这个项目」）。
3. **一键应用**：默认全选可安全项，点击后逐项应用并显示结果；失败项保留重试；
4. 用户可以整体跳过，项目主页持续保留「完成 AI 初始化」入口。

### 4.4 AI Wiki 生成（可观测、可降级）

```
[生成项目文档]
  → 预检：LLM 已配置 / 扫描到 143 个源文件（TS 88、Python 55）/ 预计 12 页
  → [开始生成] → 后台任务 + 进度（规划文档结构 30% → 生成页面 …）
  → 完成：生成 12 页 · 更新 3 页 · 跳过 97 页 · [打开 Wiki] [纳入项目资料]
```

- 无 LLM 时不报错，降级生成确定性骨架（目录总览、符号索引、构建与测试指南）；
- 生成页面带 `generator: sage` frontmatter，增量更新只覆盖自己生成过的页面；
- 覆盖已有页面之前自动创建项目快照。

### 4.5 AI 顾问 2.0（有证据、可执行）

每张建议卡包含：标题、证据芯片（文件路径/Git 状态/里程碑/会话）、理由、主按钮（执行）、忽略（7 天）。最多 3 条，全部动作类型化：

`create_milestone` / `add_rule` / `generate_wiki` / `init_git` / `create_checkpoint` / `start_session` / `add_material` / `open_settings`。

---

## 5. 分模块技术方案

### A. 右键菜单与「打开项目文件夹」

**前端**
- 新增 `src/widgets/project/ProjectContextMenu.tsx`，基于 `@radix-ui/react-context-menu`（与现有 Radix DropdownMenu 同族，新增一个依赖）；
- 工作台 `WorkbenchProjectList` 与侧边栏 `SidebarProjectList` 复用同一菜单；「···」按钮与右键共用一份菜单内容；
- 删除现有占位动作（固定里程碑/固定规则）；「初始化目录」改为打开 AI 初始化面板。

**后端**
- 新增 `GET /api/v1/projects/{project_id}/location`：
  - 项目不存在 → 404；目录缺失 → 410 `project_path_missing`；
  - 用 `validate_workspace` 校验并返回规范化绝对路径；
  - 无副作用（不刷新 `last_opened_at`、不建会话）。
- 新增 `POST /api/v1/projects/{project_id}/git/init`（见 B）。

**Electron**
- 新增 raw IPC（参考 Office 的信任模型，不接收渲染进程原始路径）：
  - `project:open-folder` → 用 `projectId` 请求后端 `/location` → 校验 `isDirectory()` → `shell.openPath(path)`；
  - `project:reveal-folder` → `shell.showItemInFolder(path)`；
  - `project:open-terminal` → 优先复用 `pty.create({cwd: path})`，返回 `{id}` 并通知前端打开终端面板；若前端未就绪则 P1 再实现；
- 每个 handler 前置 `isTrustedRenderer(event)`；不新增 JSON manifest 路由（与 `office:*` 同级）；
- 顺手修复 `file:open-in-editor` 缺少 containment 校验的问题（`electron/main.ts:2093-2127`）。

**安全**
- 渲染进程只传项目 id；路径由后端注册表 + `validate_workspace` 给出；
- 不开放任意目录打开，避免把 IPC 变成文件系统浏览器。

### B. 新项目 AI 初始化（bootstrap）

**API**

```
POST /api/v1/projects/{id}/bootstrap/preview
  body: { use_llm?: bool = true }
  resp: {
    project: ProjectModel,
    scan: {
      level1_type, sub_type, tech_stack: string[],
      source_files: { language, count }[],
      git: { is_repo, branch?, dirty_count?, commit_count?, git_available },
      existing: { sage_md, rules_count, milestones_count, materials_count, profile_count }
    },
    suggestions: {
      sage_md: { content, rationale, exists, would_overwrite },
      rules: [{ key, label, content, reason, category, priority, evidence: string[] }],
      milestones: [{ title, description, stage?, estimated_days? }],
      allowed_paths: [{ pattern, label, reason }],
      git_init: { recommended, reason, blockers?: string[] },
      wiki: { recommended, estimated_pages },
      first_prompt: string
    },
    llm_available: boolean
  }

POST /api/v1/projects/{id}/bootstrap/apply
  body: {
    accept: {
      metadata?: { description?, instructions?, project_type?, project_sub_type? },
      sage_md?: boolean,
      rule_keys?: string[],
      custom_rules?: [{ content, category, priority, trigger_pattern? }],
      milestones?: [{ title, description, stage?, estimated_days? }],
      allowed_paths?: string[],
      git_init?: boolean,
      initial_checkpoint?: boolean
    }
  }
  resp: { applied: string[], skipped: string[], errors: [{ item, message }] }
```

**实现**
- `preview` 复用 `ProjectProfiler` / `ProjectAnalysisAgent` / `ProjectRuleGenerator`（均已存在），把当前被丢弃的字段补进建议；
- `scan` 永远返回（LLM 不可用也返回确定性结果）；`suggestions` 在 LLM 不可用时用技术栈→模板映射 + 蓝图默认值填充；
- `apply` 逐项幂等：
  - `SAGE.md` 只在不存在或用户显式覆盖时写入，写入前创建快照；
  - 规则按 content 归一化去重（修复脚手架重复导入）；
  - 里程碑仅在用户勾选时创建，不自动 seed；
  - `git_init` 仅在 `.git` 不存在、`git --version` 成功时执行 `git init`；不自动 commit；成功后 `vcs_mode='git'`；
  - 初期快照仅在 builtin 模式或用户勾选时创建；
- 新增 `projects.bootstrap_state TEXT` 与 `projects.project_sub_type TEXT`（均为可空、幂等 ALTER）：前者记录最近一次应用时间、已应用项、被忽略建议，用于主页「下一步」与顾问去重；后者持久化两级分类的子类型（当前项目模块只存 `detected_type`，子类型没有落库位置）；
- 直接登记/拖拽/命令面板：`register` 成功后前端自动打开 bootstrap 抽屉（确定性扫描），不再直接跳转；「+」按钮保留「快速登记并开始会话」，但首页仍显示初始化卡。

**向导改造**
- 现有 3 步 → 2 步：选文件夹 → 初始化建议清单（复用 bootstrap preview/apply）；
- 移除 Step 3 的 L2/L5/规则包/阶段/VCS 大表单，全部收进「更多设置」折叠区；
- 分析失败不阻断登记；向导可跳过。

### C. 信息架构精简（6 Tab → 3 Tab）

**路由**
- 新增 `/projects/:projectId` 作为「项目主页」；
- `/projects/governance/:projectId` 保留重定向（兼容旧链接/测试），内部渲染新页面。

**Tab**
| 新 Tab | 合并内容 |
|---|---|
| 概览 | 状态、下一步、AI 顾问、里程碑摘要、最近会话 |
| 项目知识 | 规则与约束、项目资料、AI 记忆（子分栏，默认只显示计数与最近项） |
| 设置 | 基本信息、项目类型、SAGE.md（高级）、允许路径、VCS、五层上下文预算、导出 |

**术语替换（默认界面）**

| 旧 | 新 |
|---|---|
| L1 隐式规约 / SAGE.md 总纲 | 项目说明（高级：SAGE.md） |
| L2 元数据与强约束 | 项目规则 |
| L3 演化画像 / AI 认知 | AI 记忆 |
| L4 受控资料池 | 项目资料 |
| L5 跨目录只读源 | 外部只读目录 |
| +L2 / +L3 / +L4 / 升格 / 沉淀 | 保存到「规则 / AI 记忆 / 资料」 |
| 生命周期阶段 / 推进至 | 设置中的「项目阶段」（默认不展示） |

**动作收敛**
- 删除散落在 6 个组件里的转换按钮；只保留一个共享 `SaveToKnowledgeMenu`，出现在资料/规则条目的「⋯」中；
- 概览状态卡只保留：阶段徽标（可点开设置）、SAGE.md 就绪、快照数、AI 拆分任务、生成文档；
- 「复制治理快照 / 导出治理 JSON」移入设置 Tab 的导出区。

**去重**
- 工作台展开行不再内嵌概览/资料编辑，只保留会话子列表 + 「打开项目主页」链接；
- 侧边栏展开面板同样收敛，避免三处编辑同一数据；
- 删除未被路由引用的 `ProjectArchetypeStudio` / `ProjectTypeSelector`（或明确标注为内部调试组件）。

**分类法统一**
- 以 `GET /projects/config/types` 为唯一阶段/状态注册表；前端 `useProjectTaxonomy()` 拉取并缓存；
- 约束类别建立单一中文标签映射，未命中回退原文而非空白；
- 统一未分类表现：未设置类型 = `未分类`，不再在治理页默认 business。

### D. AI Wiki 修复与升级

**修复（P0）**
1. `scan_files(languages=None)` 默认改为全部支持扩展名（`ALL_SOURCE_EXTENSIONS`）；
2. `wikiScanFiles` 去掉 `languages ?? 'python'` 默认；
3. `generate()` 扫描全部语言；
4. 前端区分「0 个源文件」与「LLM 未配置」两种失败，并给出修复动作（去设置配置 LLM / 检查项目路径）。

**升级（P1）**
- 预检端点 `GET /projects/{id}/ai/wiki/status`：
  `{ llm_available, scan: {language, count}[], existing_generated_pages, last_generated_at, estimated_pages, blockers: [{code, message, fix_action}] }`；
- 生成改为后台任务：
  - `POST /projects/{id}/ai/wiki/jobs` → `{job_id}`；
  - `GET /projects/{id}/ai/wiki/jobs/{job_id}` → `{status, progress, phase, pages_generated, errors}`；
  - 并发上限 1/项目，可取消；
- 无 LLM 降级：生成确定性骨架页（`wiki/architecture/overview.md`、`wiki/api-docs/symbol-index.md`、`wiki/guides/build-and-test.md`），由 `ProjectProfiler` + 扫描器填充；
- 增量：维护 `.sage/wiki-manifest.json`（源文件 hash → 生成页面），只重新生成变化文件；生成页 frontmatter 标记 `generator: sage`，只覆盖自己生成过的页面；覆盖前创建快照；
- 生成成功后自动登记 Wiki 项目（复用 `recent_projects` 桥接），并在项目主页显示「打开 Wiki」。

### E. AI 顾问 2.0

**上下文采集（确定性）**
- `ProjectProfiler` 全量画像：技术栈、框架、构建/测试命令、lint/CI、目录结构、源码采样（沿用敏感路径黑名单与 8×120 行上限）；
- Git：分支、脏文件数、最近 5 条 commit（仅标题）、是否领先/落后远端；
- 会话：总数、最近活跃时间、最近 5 个会话标题；
- 知识：规则/资料/AI 记忆数量，Wiki 最近生成时间与源文件变化数；
- 里程碑：状态计数、逾期项。

**输出 schema**

```json
{
  "health_score": 72,
  "summary": "认证模块已逾期 3 天，但整体技术栈健康",
  "suggestions": [
    {
      "id": "sugg_1",
      "title": "为认证里程碑拆分任务",
      "reason": "里程碑已逾期 3 天，且关联 5 个未提交文件",
      "evidence": ["milestone: JWT 认证 (due 2026-10-26)", "git: 5 uncommitted"],
      "action": { "type": "create_milestone", "payload": { "title": "...", "due_date": "..." } },
      "priority": "high",
      "confidence": 0.8
    }
  ]
}
```

- 未配置 LLM 时由确定性规则引擎输出（无 git → 初始化 Git；脏文件多 → 快照；无规则但识别到技术栈 → 补规则；Wiki 过期 → 生成；无会话 → 开始会话；里程碑逾期 → 调整）；
- prompt 明确要求「引用输入中的事实，禁止通用建议；不要建议已经完成的事项」；
- 缓存 key = `sha256(project_id + git_head + dirty_count + milestones_version + last_session_at)`，仓库变化自动失效；
- 忽略的建议记录在 `bootstrap_state` 中，7 天内不再出现。

**应用动作**
- 前端对安全动作直接调用既有 API（`createMilestone` / `createConstraint` / `createCheckpoint` / `wikiJob` / `openProject`）；
- 复合动作（如初始化 Git）走后端 `POST /projects/{id}/ai/advice/apply`，复用 bootstrap 的 `git_init` 逻辑；
- 每个动作先预览（里程碑标题、规则内容），用户确认后执行。

### F. 一致性与清理

| 问题 | 处理 |
|---|---|
| `vcs_mode='none'` 后端 422 | 从 UI 移除该选项；后端契约保持不变 |
| 脚手架规则重复导入 | 按内容 hash 去重；类型级默认包仅在用户未选细分包时导入 |
| 阶段枚举漂移 | 统一到 `/projects/config/types`；`MilestoneEditor` 模板改用注册表 id |
| 约束类别漂移 | 单一标签注册表 + 兜底原文 |
| 检查点 UI 仅 business/personal 可见 | 在设置 Tab 提供通用「版本历史」入口，所有 builtin 项目可用 |
| L4 上限文案错误 | 改为「总上下文上限」 |
| 审计函数/注释过期 | 随页面重构删除或更新 |
| 多处重复拉取项目/里程碑/画像 | 项目主页统一加载一次，子组件接收 props |

---

## 6. 涉及文件与模块（主要）

**前端新增**
- `src/widgets/project/ProjectContextMenu.tsx`
- `src/features/project-type/ProjectBootstrapPanel.tsx`（初始化建议清单）
- `src/features/project-type/ProjectNextActions.tsx`（下一步卡片）
- `src/pages/ProjectHome.tsx`（由 `ProjectGovernance.tsx` 重构）
- `src/shared/api/projectBootstrapApi.ts`（或并入 `projectApi`）

**前端修改**
- `src/pages/Projects.tsx`、`src/pages/ProjectGovernance.tsx`
- `src/widgets/sidebar/sections/WorkbenchProjectList.tsx`、`SidebarProjectList.tsx`、`ProjectExpandedPanels.tsx`
- `src/features/project-type/ProjectCreationWizard.tsx`、`ProjectOverviewWidgets.tsx`、`PolymorphicArchetypeCards.tsx`、`ConstraintManager.tsx`、`MilestoneManager.tsx`、`StudioProfileTabPanel.tsx`、`StudioMaterialsAndProfilePanels.tsx`、`WikiGenerationPanel.tsx`、`ProjectAdvisorCard.tsx`
- `src/shared/api/projectApi.ts`、`projectApiTypes.ts`
- `package.json`（新增 `@radix-ui/react-context-menu`）

**后端新增**
- `backend/services/project_bootstrap.py`（preview/apply 编排）
- `backend/services/project_advisor_rules.py`（确定性建议规则引擎）
- `backend/services/project_wiki_jobs.py`（后台任务注册表，内存态）

**后端修改**
- `backend/api/project_routes.py`（location / bootstrap / git init）
- `backend/api/project_ai_routes.py`（advisor 上下文与 action schema、wiki status/jobs）
- `backend/api/project_schemas.py`
- `backend/data/database.py`、`backend/data/project_repo.py`（`bootstrap_state` 列）
- `backend/services/project_wiki_generator.py`（语言支持、增量、manifest）
- `backend/services/project_advisor.py`（上下文采集、schema、缓存指纹）
- `backend/services/project_archetype_scaffold.py`（去重、可选 seed）

**Electron**
- `electron/main.ts`、`electron/preload.ts`、`src/shared/types/electron-api.d.ts`（`project:open-folder` / `project:reveal-folder` / 可选 `project:open-terminal`）

---

## 7. 实施步骤（按可独立验证的里程碑）

### P0 — 快速见效（1–2 天）

- [ ] 新增 `GET /projects/{id}/location` + Electron `project:open-folder` / `project:reveal-folder` + 信任校验
- [ ] 新增共享右键菜单，接入工作台与侧边栏；删除占位菜单动作
- [ ] 修复 Wiki 扫描语言默认值（后端 + 前端），TS 项目可预览源文件
- [ ] Wiki 生成失败原因在面板顶部显式展示（0 文件 / LLM 未配置 / 权限）
- [ ] 默认界面去术语：工作台/侧边栏/治理页 Tab 与按钮文案替换（先改标签，不动结构）
- [ ] 移除 `vcsMode='none'` 选项
- [ ] 单元/组件测试 + CI 绿

**验收**：右键任意项目 →「在文件管理器中显示」打开对应目录；TS 项目 Wiki 预览不再为 0；界面无 L1–L5 字样。

### P1 — 新项目 AI 初始化（3–5 天）

- [ ] `bootstrap_state` 列 + 幂等迁移
- [ ] `POST /projects/{id}/bootstrap/preview` + `/apply`（含 git init、去重、快照）
- [ ] 新 `ProjectBootstrapPanel` 接入向导第 2 步与项目主页
- [ ] 四条登记入口统一走 bootstrap（快速登记保留，但显示初始化卡）
- [ ] 写入被丢弃的分析产物：SAGE.md 草稿、子类型、推荐里程碑、自定义规则
- [ ] 应用后导航到项目主页并预填首次会话
- [ ] 后端集成测试（幂等、无 LLM 降级、git init 仅注册路径）+ 前端测试

**验收**：在无任何治理数据的新目录登记后，一次确认内完成 SAGE.md/规则/（可选）Git 初始化，并进入首次会话。

### P2 — 信息架构精简（3–5 天）

- [ ] `/projects/:id` 项目主页 + 旧路由重定向
- [ ] 6 Tab → 3 Tab；概览合并顾问/里程碑/会话
- [ ] `ProjectNextActions` 确定性状态机（无 SAGE.md → 生成；无规则 → 建议；无 Git → 初始化；Wiki 过期 → 更新；否则 → 开始会话）
- [ ] 收敛转换动作为 `SaveToKnowledgeMenu`；移除重复面板
- [ ] 分类法注册表统一（阶段、类别、未分类表现）
- [ ] 高级设置抽屉
- [ ] 快照/导出控件下移
- [ ] 组件测试 + 视觉回归（关键页截图）

**验收**：默认页面一屏内只有「开始会话 + 下一步 + 会话列表 + 折叠的知识/里程碑」；grep 默认 UI 无 L1–L5。

### P3 — AI 顾问 2.0 + Wiki 升级（4–6 天）

- [ ] 顾问上下文采集（profiler + git + 会话 + 知识 + 里程碑）
- [ ] 顾问输出 schema 扩展为可执行 action + evidence
- [ ] 确定性建议规则引擎（无 LLM 可用）
- [ ] 缓存指纹 / 忽略 7 天 / 一键执行与预览
- [ ] Wiki 预检端点 + 后台任务 + 进度/取消
- [ ] Wiki 无 LLM 确定性骨架降级
- [ ] Wiki 增量（manifest + frontmatter 所有权）
- [ ] JS/TS 轻量符号提取
- [ ] 测试：advisor schema、规则引擎、wiki 语言/增量/降级

**验收**：在真实 TS 项目上生成 ≥ 5 页文档（LLM 或骨架）；顾问建议每条带证据且至少一项可一键执行。

### P4 — 收尾（1–2 天）

- [ ] 删除/归档未使用组件与过期审计函数
- [ ] 文档：用户手册新增「项目快速开始」「AI 初始化」「右键菜单」；技术文档更新 61/58
- [ ] 性能与回归：项目主页加载 ≤ 1 次项目/里程碑/画像请求
- [ ] 双分支同步：cherry-pick 到 main，按 py3.8 / pydantic 1.x 适配

---

## 8. 测试与验收

- **后端单测**：bootstrap preview/apply 幂等与降级；location 404/410；git init 仅注册路径；advisor 规则引擎；wiki 语言扫描、增量、无 LLM 骨架；
- **后端集成**：项目登记 → bootstrap → 首次会话全链路；非法路径拒绝；wiki 任务状态流转；
- **前端组件**：右键菜单（点击/键盘/禁用态）、bootstrap 勾选与应用、下一步状态机、术语不泄漏；
- **E2E（Playwright）**：右键「在文件管理器中显示」调用 mock shell；新项目 3 次点击进入首次会话；Wiki 生成进度到完成；
- **质量门**：沿用 80% 覆盖率；新增文件纳入 architecture baseline；双分支 CI 全绿。

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 范围大，一次改不完 | 半成品体验 | P0 独立可发；每阶段可单独 PR/回滚 |
| LLM 未配置 | 初始化/顾问/Wiki 失效 | 全链路确定性降级，端点不 5xx |
| `git init` 写入用户目录 | 用户数据/信任风险 | 显式勾选 + 仅注册路径 + 不自动 commit；失败静默降级为内置快照 |
| 路径安全 | 任意目录打开 | 渲染进程只传 projectId；后端 `validate_workspace`；主进程二次校验 |
| 破坏既有测试/深链 | 回归 | 旧路由重定向；保留 API；分阶段合并 |
| 分类法统一引发大规模改动 | 冲突 | 先加注册表与读侧兼容，再逐步迁移 |
| win7 环境无 `git` | Git 建议不可用 | 检测 `git --version`；不可用时隐藏该项，默认 builtin 快照 |
| 生成文档覆盖用户内容 | 数据丢失 | 仅覆盖 `generator: sage` 页面；覆盖前快照；预览 diff |

---

## 10. release/win7 对齐注意

- 后端新代码保持 Python 3.8 语法（无海象/match、`typing.List/Dict`）；
- Pydantic 1.x：新 schema 使用 `class Config: extra = "forbid"`，不用 v2-only API（参考 `sage-pydantic-compat-shim` 经验）；
- 前端零 Electron 版本依赖：`shell.openPath` / `showItemInFolder` 在 Electron 21 可用；`pty.create` 已存在；
- 若 win7 无系统 Git，`git init` 建议自动隐藏并回退 `builtin`；
- 新增依赖 `@radix-ui/react-context-menu` 与现有 Radix 同版本线，前端构建无平台差异；
- 双分支同步按 cherry-pick，分类法/文档编号冲突按 win7 现状解决。

---

## 11. 明确不做（YAGNI）

- 不引入云端协作文档/多人项目；
- 不做事件订阅（Slack/PR）驱动的自动化；
- 不在本期做代码符号的完整 tree-sitter 解析（TS 先用轻量正则，后续独立迭代）；
- 不把治理能力删除——只做隐藏与语言转译，高级用户仍可访问全部能力；
- 不改 `projects` 与会话归属的核心数据模型（仅新增 `bootstrap_state`、`project_sub_type` 两个可空列）。
