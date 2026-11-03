# 项目工作台 UX 优化方案

**日期**: 2026-11-03  
**状态**: 进行中  
**分支**: `feat/project-workbench-ux-redesign` (main)  
**同步计划**: main 落地后 cherry-pick 到 `release/win7`

## 背景与目标

### 现状问题

项目工作台（`ProjectGovernance` 概览页）存在 6 类问题：

1. **扫描进度不可见**: `ProjectBootstrapPanel` 和 `PlaybookCard` 在页面加载时自动触发长时间扫描（10-60s），但只显示一个 spinner，用户不知道当前在做什么、还剩多久。

2. **技术术语外露**: 设计文档的 L1-L5 命名直接漏到 UI 字符串（"5 层受控上下文注入预算水位"、"L3 项目画像"、"context_pillar"、"stage_gate"），普通用户无法理解。

3. **AI 初始化建议固定 + 应用不可验证**:
   - LLM 失败时静默降级到固定模板（`_heuristic_custom_rules`）
   - 里程碑永远追加 `blueprint.default_milestones`
   - `apply_bootstrap` 只返回 "applied/skipped/errors" 数组长度，UI 显示"已应用 x 项"但无法验证每条是否真的落地
   - `bootstrap_state` 后端存了但前端 `ProjectSummary` 未透出

4. **规程控件难懂**: `PlaybookToolbar` 14 个按钮平铺（刷新审计/AI 审计/导出 3 种格式/Wiki 导出/保存库/打开库/编辑/版本/活动/播种里程碑/清理规则/解绑/导入）；`PlaybookClassificationPanel` 显示"from → to · suggestion (xx%)"用内部审计术语。

5. **代码工程专属工作台不明**: `PolymorphicArchetypeCards` coding 卡有"工程标志文件与模块分布"、"快捷命令入口"、"架构决策记录 (ADR · 注入 L3 项目画像)"，缺说明和上下文。

6. **整体信息过载**: Overview 堆叠 `ProjectBootstrapPanel` + `PlaybookCard` + `PolymorphicArchetypeCards` + `ProjectOverviewWidgets`（含 6 个子 Widget + 30+ 按钮），缺"主任务流"和渐进披露。

### 目标

- 让普通用户能读懂 90% 的页面文字（术语净化）
- 让用户能看到 AI 扫描进度（分阶段状态）
- 让用户能验证 AI 建议是否真的落地（应用结果清单 + 重新扫描）
- 让用户能快速找到"现在该做什么"（主操作流）
- 让信息架构清晰（渐进披露，隐藏高级/调试操作）

## 涉及的文件与模块

### 前端

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `src/pages/ProjectGovernance.tsx` | 重构 | 概览页信息架构重组（M6） |
| `src/features/project-type/ProjectBootstrapPanel.tsx` | 重构 | 分阶段扫描 + 应用结果验证（M2, M3） |
| `src/features/project-type/PolymorphicArchetypeCards.tsx` | 重构 | 术语净化 + 代码工程卡片重构（M1, M5） |
| `src/features/project-type/ProjectOverviewWidgets.tsx` | 重构 | 术语净化 + 高级按钮折叠（M1, M6） |
| `src/features/playbook/PlaybookToolbar.tsx` | 重构 | 按钮收束到 3 个主操作 + "更多"菜单（M4） |
| `src/features/playbook/PlaybookClassificationPanel.tsx` | 重构 | 归类建议文案翻译（M1, M4） |
| `src/features/playbook/PlaybookCard.tsx` | 调整 | audit 按需触发而非同步（M2） |
| `src/shared/api/projectApiTypes.ts` | 调整 | `ProjectSummary` 增加 `bootstrapState`（M3） |
| `src/shared/lib/i18n/locales/zh/*.ts` | 调整 | 新增文案键（M1） |

### 后端

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `backend/services/project_bootstrap.py` | 调整 | 拆分 `build_bootstrap_preview` 为 `scan` + `suggest` 两步（M2）；`apply_bootstrap` 返回结构化结果 + verification（M3） |
| `backend/api/project_routes.py` | 调整 | 新增 `/projects/{id}/bootstrap/scan` 和 `/projects/{id}/bootstrap/suggest` 端点（M2）；`ProjectWire` 暴露 `bootstrap_state`（M3） |
| `backend/data/project_repo.py` | 调整 | `to_dict` 序列化 `bootstrap_state`（M3） |
| `backend/api/playbook_routes.py` | 调整 | `getCurrent` 不触发 audit，由前端按需调用 `/audit`（M2） |

## 技术方案

### 方案选型

| 方案 | 范围 | 工作量 | 风险 | 决策 |
|---|---|---|---|---|
| **A. 信息架构重组 + 渐进披露 + 术语净化** | 概览页重组为 4 个主区；隐藏高级/调试操作；翻译术语；分阶段扫描 + 进度；应用结果验证清单 | 中（6 个里程碑） | 中 | ✅ 采用 |
| B. 完全向导化（wizard 强制） | 新项目强制走 wizard；完成前隐藏其他内容 | 高 | 高 | ❌ 不适合双分支长期共存用户 |
| C. 仅翻译术语 + 隐藏按钮 | 只改文案、把高级按钮折叠进 details | 小 | 低 | ❌ 不治本 |

### 里程碑分解

#### M1 · 术语净化与文案翻译（最低风险、最高可见度）✅ 已完成

**目标**: 让普通用户能读懂 90% 的页面文字。

**改动点**:
- `PolymorphicArchetypeCards.tsx:186` 标题 → "项目上下文健康度"；副标题 → "AI 了解你项目的完整程度"
- `L1 隐式规约 (SAGE.md)` → "项目总纲"
- `L2 元数据与强约束` → "项目规则"
- `L3 演化画像 (Profile)` → "项目记忆"
- `L4 受控资料池 (Pinned)` → "项目资料"
- `L5 跨目录只读源` → "外部白名单"
- `五层受控上下文注入预算水位 (5-Layer Context Budget Watermark)` → 去掉英文；改为"项目上下文完整度"
- `架构决策记录 (ADR · 注入 L3 项目画像)` → "技术决策记录（会随每轮会话自动告知 AI）"
- `快捷命令入口` → "常用命令（右键可复制）"
- `代码工程专属工作台` → "工程概览"
- `ProjectOverviewWidgets` 中所有 `沉淀阶段至 L3` / `存概览至 L4` / `支柱转 L2 约束` / `阶段管线存L3` / `当前阶段设 L2 约束` 等十余个按钮文案，全部改为"沉淀到项目记忆"/"存为参考资料"/"升级为项目规则"
- `context_pillar` / `stage_gate` / `stage_pipeline` 这些 category 标签在 UI 上统一显示为中文分类（规则类别标签表）
- `PlaybookClassificationPanel` 的 `from → to · suggestion (xx%)` → "建议移动到 · 置信度 xx%"；面板标题"归类建议" → "文件整理建议"

**测试**: 文案回归测试（`playwright snapshot`）+ 不破坏现有 i18n 键（新文案直接改中文字面量，i18n 键复用）。

#### M2 · 扫描与初始化分阶段进度

**目标**: 用户能看到"AI 正在做什么、还剩多久"。

**后端改动**:
- 拆分 `build_bootstrap_preview` 为两步端点：
  - `POST /projects/{id}/bootstrap/scan`（确定性扫描，~200ms）：返回类型/技术栈/git/文件分布
  - `POST /projects/{id}/bootstrap/suggest`（LLM 路径，10-60s）：返回 rules + milestones + sage_md draft + first_prompt
- 两步都返回 `stage` 字段，前端可显示进度

**前端改动**（`ProjectBootstrapPanel.tsx`）:
- 把 `load(true)` 拆为 `scan()` 和 `suggest()` 两步
- 扫描完成立即显示"扫描结果"卡片（项目类型 / 技术栈 / 文件分布 / Git 状态），UI 不再整体被 spinner 占位
- LLM 建议阶段显示"正在分析项目特征..."、"正在生成规则..."、"正在规划里程碑..."三个子步骤（基于请求阶段，不是 fake）
- LLM 失败时，明确提示"AI 建议生成失败，已切换到推荐模板"，而不是静默降级
- PlaybookCard 的 audit 拆出独立请求（`POST /projects/{id}/playbook/audit` 已有，但 `getCurrent` 里也同步跑了一遍），`getCurrent` 只拉当前绑定状态，不触发 audit；audit 由用户点击"检查进度"或首次展开清单时按需触发

**测试**: 单测 mock 两步接口；集成测试 `bootstrapPreview` 拆开后前端行为一致；playwright E2E 覆盖 LLM 可用 / 不可用两条路径。

#### M3 · AI 初始化"应用结果"验证

**目标**: 用户能看清楚每条建议是否真的落地，能重跑验证。

**后端改动**:
- `apply_bootstrap` 改为返回结构化结果：
  ```python
  {
    applied: [
      {item: 'sage_md', id: None, location: 'SAGE.md', content_preview: '...'},
      {item: 'rule', id: 'uuid', category: 'coding_style', content_preview: '...'},
    ],
    skipped: [{item: 'rule', reason: 'duplicate', content_preview: '...'}],
    errors: [{item: 'git_init', message: '...'}],
    verification: {sage_md_exists: True, rules_count_after: N, milestones_count_after: M}
  }
  ```
- `GET /projects/{id}` 响应中 `ProjectWire` 暴露 `bootstrap_state`（已存在字段，只是未序列化）

**前端改动**（`ProjectBootstrapPanel.tsx` + `projectApiTypes.ts`）:
- `ProjectSummary` 增加 `bootstrapState?: {applied: string[], appliedAt: number} | null`
- `mapProject` 透传 `bootstrap_state`
- apply 结果从"已应用 x 项"改为**可展开的清单**：每条显示 图标(✓/○/✗) + 名称 + 落地位置 + "查看" 链接（跳转到规则页/里程碑页/SAGE.md 预览）
- apply 后自动调用 `load(false)` 重新扫描，更新 preview.scan.existing 状态（已有 N 条规则 / 已有 N 个里程碑）
- 页面顶部常驻"项目初始化进度"迷你状态条（"初始化 4/5 项已完成"），持久存在直到关闭或全部完成

**测试**: apply 单测验证 verification 字段；E2E 覆盖"已应用 → 展开清单 → 点击跳转"。

#### M4 · PlaybookToolbar 收束 + 主操作流

**目标**: 用户一眼看到"现在该做什么"。

**改动**（`PlaybookToolbar.tsx`）:
- 主操作区保留 3 个按钮：`刷新审计` / `AI 检查` / `导出`（导出按钮下拉 JSON/MD/agents/Wiki 四选一）
- 次操作收入 "更多 ▾" 菜单：编辑规格 / 版本历史 / 活动日志 / 保存到库 / 库 / 播种里程碑 / 清理规则 / 导入 / 解绑
- 阶段条保留，但点击某阶段后不再直接切换，而是弹出"确认切换到 X 阶段？会重新审计"的确认
- `PlaybookClassificationPanel` 重构：
  - 顶部显示 "发现 N 个整理建议，一键应用" 的单一主按钮
  - 详情默认折叠，展开后显示具体移动列表
  - 撤销按钮移到 "已应用 N 次 · 撤销最近一次" 的次级位置

**测试**: playwright 覆盖 "主按钮/更多菜单/确认切换" 三个交互。

#### M5 · 代码工程卡片重构 + 说明

**目标**: 普通用户能立刻明白"这是什么、我能做什么"。

**改动**（`PolymorphicArchetypeCards.tsx` 的 `projectType === 'coding'` 分支）:
- 拆成三个独立子卡，每张卡带"一句话说明 + 主操作"：
  1. **项目结构**: 显示 `directorySummary` 前 8 项 + 顶部文件（`codingIndicators`）；主按钮 "补齐标准目录"（如有空）或 "刷新"
  2. **常用命令**: `testCommands` 每个命令带一键复制按钮 + "在终端打开" 按钮
  3. **技术决策**: 原 "ADR" 输入框保留，placeholder 改为 "记录一个技术选型或约定（如：数据库用 SQLite 而不是 MySQL，因为…）"；示例 chips："采用 SQLite WAL + FTS5 索引" / "所有 API 走 REST 不走 GraphQL" / "禁止使用 any"
- 顶部 status 徽章：`SAGE.md 已配置` / `hooks 已启用(N 个)` / `运行环境就绪` — 文案不变，但位置从右上角改到卡片标题行内

**测试**: snapshot 覆盖三种 projectType 卡片。

#### M6 · 概览页信息架构重组

**目标**: 把堆叠的 4 个大组件重组为"项目主页 / 项目知识 / 规程与阶段 / 设置"渐进披露结构。

**改动**（`ProjectGovernance.tsx` Overview 区）:
- 保留 3 个顶层 Tab（概览 / 项目知识 / 设置），但内部重组：
  - **概览 Tab** 分三块：
    1. *项目主页*（新组件）：顶部状态条（项目类型 / 当前阶段 / 初始化进度 X/Y）+ "继续初始化" 主按钮（如未完成）或 "开始会话" 主按钮（如已完成）
    2. *当前阶段*：阶段条 + 下一阶段 + 该阶段需要的关键产物（playbook audit 结果）+ "AI 拆解当前阶段" 按钮
    3. *工程/领域快览*：根据 `projectType` 渲染对应 PolymorphicArchetypeCards 子卡（不是整个组件）
  - 原 ProjectBootstrapPanel 整体移入 "设置" Tab（作为"初始化向导"子区），只在首次进入或 bootstrap_state 为空时，在"项目主页"区出现迷你入口
  - 原 PlaybookCard 拆分：阶段条 + 主按钮留在"概览 > 当前阶段"；完整规程管理移入"设置" Tab 的"规程与阶段"子区
  - 原 ProjectOverviewWidgets 中的"高级转换操作"（L2/L3/L4 十几个按钮）整体移入"设置 > 高级"的 details 折叠区，默认隐藏
  - MilestoneProgressWidget 留在"概览 > 当前阶段"
  - WikiGenerationPanel、GitStatusWidget 移入"项目知识 > 项目资料"子 Tab

**数据流**:
- `project.bootstrap_state` 驱动"初始化进度 X/Y"和"继续初始化"按钮的显隐
- 每次 apply_bootstrap 后更新 bootstrap_state 并回传到前端，刷新进度条

**测试**:
- E2E 覆盖"新项目首次进入 → 看到初始化进度 → 点击继续 → 完成 → 切换到'开始会话'"
- snapshot 对比确保信息层次清晰

## 风险评估与依赖

| 风险 | 缓解 |
|---|---|
| M1 文案改动触发大量 snapshot 测试失败 | 用 `playwright --update-snapshots` 批量更新；i18n 键复用不改结构 |
| M2 拆接口破坏老客户端 | 保留 `/projects/{id}/bootstrap/preview` 兼容端点 1 个版本 |
| M3 `bootstrap_state` 暴露到 `ProjectWire` 需 migration | 已有字段，只需 `to_dict` 改序列化；无 schema 变更 |
| M6 信息架构改动影响面大 | 保留旧路径的"兼容视图"开关（`?legacy=1` URL 参数）灰度 1 周后删除 |
| 双分支同步（main / release/win7） | M1-M5 是文案/交互层改动，可 cherry-pick；M6 涉及组件拆分，需单独评估 win7 是否跟进（Python 3.8 / pydantic v1 不影响前端，但 Playbook 后端有 v1/v2 差异需确认） |

## 依赖

- M1: 无
- M2: 无
- M3: 依赖 M2（两步接口）
- M4: 无
- M5: 无
- M6: 依赖 M2 + M3（bootstrap_state 驱动进度条）

## 实施顺序

1. M1 · 术语净化与文案翻译
2. M2 · 扫描与初始化分阶段进度
3. M3 · AI 初始化"应用结果"验证
4. M4 · PlaybookToolbar 收束 + 主操作流
5. M5 · 代码工程卡片重构 + 说明
6. M6 · 概览页信息架构重组

每个里程碑独立 PR，合入 main 后 cherry-pick 到 `release/win7`。

## 验收标准

- [ ] 普通用户能读懂 90% 的页面文字（无 L1/L2/L3/L4/L5 术语）
- [ ] 用户能看到 AI 扫描分阶段进度（非单 spinner）
- [ ] 用户能验证每条 AI 建议是否落地（可展开清单 + 跳转查看）
- [ ] 用户能快速找到"现在该做什么"（主操作区 ≤ 3 个按钮）
- [ ] 高级/调试操作默认隐藏（需展开 details）
- [ ] 双分支同步（main + release/win7）
- [ ] E2E 测试覆盖主流程
- [ ] snapshot 测试更新
