# M4「分发与质量」实施计划

> 日期：2026-11-05
> 分支：feat/specialist-persona（切自 release/win7 `c8dbaae31`）
> 设计依据：`docs/superpowers/specs/2026-11-03-specialist-persona-design.md` §M4（606–617）、§8、§11
> 前置里程碑：M0–M3 已完成（提交 `8b3f5347f`）

---

## 1. 背景与目标

M1–M3 已交付专家画廊、技能作用域、知识绑定与记忆隔离。M4 解决「分发与质量」：

1. **专家包可跨机器搬运**：当前 `.sage` 包（`specialist_exporter.py` / `specialist_importer.py`）只往返
   `name / system_prompt / source / version`，人设标语、技能允许集、记忆策略、权限模式、UI 配置、
   知识绑定全部丢失，导入后专家行为与源机器不一致。
2. **从模板快速起步**：内置 profiles 有 writer/researcher/coder 等种子，但 `role != 'specialist'`，
   不会出现在 `/specialists` 画廊；用户必须从零填写六段人设。
3. **人设迭代可追溯**：`agents.version` 会在人设字段变更时自动 +1，但没有历史快照、diff 与回滚。
4. **质量可度量**：spec §11 定义了黄金任务集指标，但无任何评测 harness。
5. **文档与双分支收尾**：M2/M3 计划文档尚未并入手册，M4 是最后里程碑，需归档并删除计划文档。

**验收线（spec 原文）**：用户可从模板库一键创建写作专家；专家包可导出并导入到另一台机器。

---

## 2. 涉及的文件与模块

### 后端（新增）

| 文件 | 用途 |
|---|---|
| `backend/services/specialist_templates/` | 5 套内置模板目录，每套一个 v2 格式 `persona.md` |
| `backend/services/specialist_templates.py` | 模板注册表：列出、读取、一键实例化 |
| `backend/services/specialist_golden_eval.py` | 黄金任务集加载 + 确定性评分 + 可注入 runner |
| `backend/services/golden_tasks.json` | 黄金任务定义（写作/研究/编码/演示/Office） |
| `backend/data/agent_version_repo.py` | `agent_versions` 快照仓储（写入/列表/读取/裁剪） |
| `backend/tests/unit/test_specialist_package_v2.py` | 格式 v2 全字段往返测试 |
| `backend/tests/unit/test_specialist_templates.py` | 模板注册表 + 一键实例化测试 |
| `backend/tests/unit/test_agent_versions.py` | 快照/列表/diff/回滚/级联删除测试 |
| `backend/tests/unit/test_specialist_golden_eval.py` | 评分逻辑 + 路由（注入假 runner）测试 |
| `backend/tests/e2e/test_m4_distribution_acceptance.py` | 验收：模板建专家 + 导出导入另一目录 |

### 后端（修改）

| 文件 | 变更 |
|---|---|
| `backend/services/specialist_exporter.py` | `persona.md` frontmatter 升级到 `format_version: 2`，导出完整 profile |
| `backend/services/specialist_importer.py` | 兼容 v1/v2；恢复完整 profile；导入侧安全钳制；支持显式 id / 信任来源 |
| `backend/api/specialist_routes.py` | 新增模板、评测路由；导入响应补充 `dropped_bindings` |
| `backend/api/legacy_agent_routes.py` | 创建/更新/回滚时写快照；新增 versions/diff/rollback 路由 |
| `backend/data/agent_repo.py` | `delete()` 级联删除版本快照 |
| `backend/data/migrations/runner.py` | v12：`agent_versions` + `agent_eval_runs` 表与索引 |
| `backend/data/database.py` | 新表幂等 DDL（与 v12 对齐） |
| `scripts/backend.spec` | PyInstaller `datas` 打包模板与黄金任务 JSON |

### 前端（新增）

| 文件 | 用途 |
|---|---|
| `src/widgets/specialists/TemplateGalleryDialog.tsx` | 模板画廊，一键创建 |
| `src/widgets/specialists/VersionHistoryDialog.tsx` | 版本列表 + 字段 diff + 回滚 |
| `src/widgets/specialists/SpecialistEvalDialog.tsx` | 黄金任务集运行与结果展示 |
| 对应 `__tests__` | 三组组件测试 |

### 前端（修改）

| 文件 | 变更 |
|---|---|
| `src/pages/Specialists.tsx` | 顶部「从模板创建」；空态直接展示模板；接入三个 Dialog |
| `src/widgets/specialists/SpecialistCard.tsx` | 新增「版本」「评测」动作 |
| `src/shared/api/specialistApi.ts` | 模板列表/实例化、版本列表/diff/回滚、评测调用 |
| `electron/commandRoutes/*` + preload 类型 | 新路由桥接（沿用现有 agent 命令模式） |

### 文档（M4 收尾）

- `docs/technical/` 新增专家/数字员工章节（M0–M4 全量架构、包格式、API、双分支说明）
- `docs/user-manual/` 新增专家使用章节（模板创建、导入导出、版本回滚、评测）
- 两个 `README.md` 更新目录
- 删除 `docs/plans/2026-11-03_m2-knowledge-binding.md`、`2026-11-04_m3-memory-isolation.md`、本文件

---

## 3. 技术方案

### 3.1 专家包格式 v2（稳定化）

`persona.md` frontmatter 扩展为完整 profile（body 仍是 `system_prompt`）：

```yaml
format_version: 2
name: 写作专家
tagline: 专业写作助手
description: 专注润色、改写与结构化写作
version: 3
source: user
avatar: "📝"
skills: ["writing", "polish-*"]
knowledge_bindings: [...]     # 导出全部；导入仅保留可移植项
memory_policy: {write_scope: specialist, read_scopes: [specialist, project, user]}
persona_ui: {avatar: "📝", tagline: ..., greeting: ..., suggested_prompts: [...]}
permission_mode: workspace_write
model_config: {model: "", temperature: 0.7, max_tokens: 0}
max_iterations: 20
memory_access: ["user"]
tools: []
enabled: true
```

兼容与安全：

- **v1 包**（只有 `name/version/source`）继续可导入，缺失字段按旧行为补默认值。
- **导入安全钳制**：`role` 强制 `specialist`；`permission_mode == full_access` 降级为
  `workspace_write`；`skills`/`tools`/`memory_access` 只接受字符串数组并去重限量；
  `knowledge_bindings` 仅保留 `specialist_private` 并重绑到新 `agent_id`，其余计入
  `dropped_bindings` 返回（跨机器不存在对应项目/集合）。
- **来源标记**：外部导入默认 `source=imported`；模板实例化显式 `source=builtin`。
- 导出对单个文件失败仍 fail-safe；zip 结构保持 `persona.md + avatar.png + skills/ + knowledge/`。

### 3.2 内置模板库

- 5 套模板：写作（writing）、研究（research）、编码（coding）、演示（presentation）、
  Office（office）。每套即一个 v2 `persona.md`（目录名 = `template_id`），与用户包同格式，
  单一真相源，避免模板另立 DSL。
- `list_templates()` 返回元数据（id/name/tagline/avatar/描述/技能数），不返回完整提示词。
- 实例化复用导入管线的「物化」函数：显式 `agent_id = specialist-<template_id>-<6hex>`，
  `source=builtin`，无知识目录时跳过复制；失败整体回滚（不写半成品 agents 行）。
- API：`GET /api/v1/specialists/templates`、`POST /api/v1/specialists/templates/{id}/instantiate`。
- 前端：画廊顶部「从模板创建」打开 `TemplateGalleryDialog`；空态直接内嵌模板网格；
  点击卡片 → 调接口 → toast + 刷新列表。

### 3.3 版本 diff / 回滚

- 新表（migration v12，幂等 DDL 同步进 `database.py`）：

```sql
CREATE TABLE IF NOT EXISTS agent_versions (
    agent_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    profile TEXT NOT NULL,          -- 完整 AgentProfile JSON
    reason TEXT NOT NULL DEFAULT 'update',  -- create/update/rollback
    created_at INTEGER NOT NULL,
    PRIMARY KEY (agent_id, version)
);
CREATE INDEX IF NOT EXISTS idx_agent_versions_agent ON agent_versions(agent_id, version DESC);

CREATE TABLE IF NOT EXISTS agent_eval_runs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    template_id TEXT,
    created_at INTEGER NOT NULL,
    report TEXT NOT NULL            -- 评测报告 JSON
);
```

- **快照时机**：创建时存 v1；每次 PATCH 前先幂等存「当前版本」快照（保证 v1 也在），
  更新后若版本号变化再存新版本；回滚后存新版本（`reason=rollback`）。
- **保留策略**：每专家仅保留最近 50 个版本（超出按 version 升序删除）。
- **API**：
  - `GET /agents/{id}/versions` → `[{version, reason, created_at}]`（倒序）
  - `GET /agents/{id}/versions/{version}` → 完整快照
  - `GET /agents/{id}/versions/diff?from=1&to=2` → 字段级 `{field, before, after}`（白名单字段）
  - `POST /agents/{id}/rollback` body `{version}` → 恢复快照并 `version+1`，返回新 profile
- `delete_agent` 级联删除该专家的版本与评测记录（与记忆级联同一路由内）。
- py38：不使用 `list[...]`/`X | Y`；pydantic v1/v2 共用 `model_dump_compat` / `class Config`。

### 3.4 黄金任务集评测

- 任务定义 `backend/services/golden_tasks.json`，按模板分组，每条含：
  `id、template_id、topic、prompt、checks`。检查器全部确定性：
  `keywords_all / keywords_any / forbidden / refusal / regex / max_chars`。
- 指标对齐 spec §11：任务完成率（checks 全过）、一次通过率、无命中拒答率；
  token/耗时由 runner 报告可选注入。
- `run_golden_eval(profile, task_ids=None, runner=None)`：runner 签名
  `(profile, task) -> {"output": str, "tool_calls": list, "tokens": int}`；
  默认 runner 用 `compose_system_prompt()` + 现有 LLM 客户端单轮调用；
  测试注入假 runner，**CI 不发起真实网络请求**。
- 路由：`GET /specialists/golden-tasks`（目录）、`POST /specialists/{id}/eval`
  （可选 `task_ids`）；结果写 `agent_eval_runs` 并返回报告。
- 前端：卡片「评测」打开 `SpecialistEvalDialog`，展示通过率、逐任务检查明细与最近一次运行时间。

### 3.5 Win7 双侧同步与文档归档

- 本分支切自 release/win7：代码须同时通过
  - `sage-backend`（Python 3.10 / pydantic 2）
  - `sage-backend-py38`（Python 3.8 / pydantic 1）
  - `scripts/check_py38_compat.py` 静态门禁
- 前端：`vitest`（新增组件测试）+ `tsc` + `npm run build`。
- 整条 M0–M4 特性需整体合入（不能单挑 M4 cherry-pick）；最终合并目标由用户决定，
  本轮不 push / 不开 PR。
- 归档技术/用户手册章节，删除已完成计划文档（M2/M3/M4）。

---

## 4. 实施步骤

### Task 1：专家包格式稳定

- [x] 导出器写 v2 frontmatter（完整 profile，`avatar.png`/`skills/`/`knowledge/` 不变）
- [x] 导入器兼容 v1/v2，恢复完整 profile + 安全钳制 + `dropped_bindings`
- [x] 往返等值测试（全字段 + v1 向后兼容 + 钳制行为）
- [x] 现有 `test_specialist_package.py` 全绿

### Task 2：内置模板库

- [x] 5 套模板 `persona.md`（写作/研究/编码/演示/Office）
- [x] 模板注册表 + 实例化（显式 id、builtin 来源、失败回滚）
- [x] `GET /specialists/templates` + `POST .../instantiate` 路由与测试
- [x] 前端模板画廊 + `/specialists` 接入 + 组件测试

### Task 3：版本 diff / 回滚

- [x] migration v12 + `database.py` DDL + `agent_version_repo`
- [x] 创建/更新/回滚快照钩子 + 50 版保留 + 删除级联
- [x] versions/diff/rollback 路由与单测
- [x] 前端版本历史 Dialog（列表/diff/回滚）+ 组件测试

### Task 4：黄金任务集评测

- [ ] `golden_tasks.json`（5 模板 ≥ 2 任务/模板）
- [ ] 确定性评分器 + 可注入 runner + 默认 LLM runner
- [ ] eval 路由 + 结果持久化 + 假 runner 路由测试
- [ ] 前端评测 Dialog + 组件测试

### Task 5：验收、双分支兼容与文档

- [ ] 验收 E2E：模板一键建写作专家；导出→另一目录导入后行为配置一致
- [ ] Python 3.10 + 3.8 双环境全量相关测试；ruff；py38 兼容门禁；tsc/vitest/build
- [ ] PyInstaller `datas` 补模板与黄金任务 JSON
- [ ] 归档技术/用户手册章节 + README 目录；删除 M2/M3/M4 计划文档；勾选 spec §M4

---

## 5. 风险与依赖

| 风险 | 缓解 |
|---|---|
| 包内 `tools` / `permission_mode` 被恶意放大 | 导入强制 `role=specialist`、`full_access` 降级、数组白名单化；保持注入/密钥扫描 |
| 跨机器知识绑定悬空 | 仅保留并重绑 `specialist_private`，其余丢弃且在响应中计数 |
| 版本快照膨胀 | 每专家保留最近 50 版；快照为单行 JSON，无外键表连接开销 |
| 评测依赖真实 LLM 导致 CI 不稳定 | runner 可注入；测试全部使用确定性假输出；生产 runner 失败按任务计错不中断整体 |
| 模板以数据文件分发在打包环境不可见 | PyInstaller `datas` 显式加入；Windows 发行包整目录复制天然包含 |
| 双分支 pydantic/语法差异 | 全程 typing 注解 + `class Config`；双环境测试 + py38 静态门禁 |
| 前端新增三个 Dialog 拉高体积 | 复用现有 Dialog/Primitives；不引新依赖；仅按需渲染 |

**依赖**：无新增第三方依赖；复用现有 `yaml`、`pydantic`、`zipfile`、`compose_system_prompt()` 与 LLM 客户端。
