# 项目规程 Playbook：阶段、交付物与完整性核验

> 日期：2026-10-31
> 状态：已实施（P0/P1）
> 相关：`docs/plans/2026-10-31_project-playbook.md`

## 1. 目标

为不同性质的项目提供可配置的管理方法论：

- 阶段流水线（如科研：开题 → 实施 → 结题）；
- 每个阶段的目录与文档要求（如开题报告、原始数据、结题报告）；
- 离线完整性核验与阶段识别（识别只给建议，需用户确认）；
- 规程的导出、导入与用户间分享。

## 2. 架构

```
前端 PlaybookCard
   │ IPC
Electron commandRoutes/playbooks.ts
   │ HTTP /api/v1
FastAPI playbook_routes.py
   ├── playbook_library.py     内置规程 / 导出信封 / Markdown 手册
   ├── playbook_spec.py        校验 / 规范化 / hash
   ├── playbook_auditor.py     文件扫描 / 完整性 / 阶段识别
   ├── playbook_actions.py     目录 / 骨架 / 规则 / 里程碑 / 阶段
   └── playbook_repo.py        项目级规程快照 + 状态
             │
SQLite project_playbooks / projects.playbook_state
```

**核心原则**

- 规程是版本化 JSON；项目绑定的是**完整快照**，内置规程升级不会改变旧项目行为。
- 审计与阶段识别完全确定性、无需 LLM；所有写操作先由用户确认。
- 永不移动/重命名用户文件；创建前自动生成项目检查点。

## 3. 数据模型

```sql
CREATE TABLE project_playbooks (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  source TEXT NOT NULL,            -- builtin:<id> / imported:<hash> / custom
  parent_id TEXT,
  spec_json TEXT NOT NULL,         -- 完整规程快照
  spec_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,     -- epoch ms
  active INTEGER NOT NULL DEFAULT 1
);

ALTER TABLE projects ADD COLUMN playbook_state TEXT;  -- JSON
```

`playbook_state` 结构：

```json
{
  "current_stage": "proposal",
  "stage_history": [{"from": null, "to": "proposal", "at": 1793400000000, "source": "user"}],
  "waivers": ["closure.budget_statement"],
  "manual_done": ["proposal.literature_matrix_ready"],
  "conditions": {"contains_human_subjects": false}
}
```

`required_when` 支持 `project.<field>`、`state.<key>` 以及 `==` 比较；未知条件按"不适用"处理。`conditions` 由 `PATCH /playbook/state` 更新。

## 4. 规程规格

内置规程位于 `backend/services/playbook_builtin/`，启动时加载并校验：

- `cn-research-grant`：开题 / 实施 / 结题；
- `coding-project`：规划 / 研发 / 测试 / 发布 / 维护；
- `business-dossier`：立卷 / 编制 / 签发封卷；
- `personal-knowledge`：活跃整理 / 归档封存。

阶段产物支持：

| 字段 | 说明 |
|---|---|
| `match.globs` | 支持 `*`、`?`、`**`（含零层目录）、`{a,b}` |
| `match.min_bytes` / `min_count` | 存在性阈值 |
| `match.max_age_days` | 时效性阈值 |
| `required` | 非必需缺失时状态为 `optional`，不扣完成度 |
| `content_checks` | `keyword` / `keyword_or_llm` / `llm` / `manual`；P0 关键词，P2 可触发 LLM |
| `missing_action` | `create_folder` / `create_doc_stub` / `apply_rules` / `seed_milestones` / `add_todo` / `move_file` / `open_doc` |
| `target_dir` | 可选目标目录；文件匹配到产物但不在目标目录时生成归类建议 |

路径校验拒绝绝对路径、`~` 开头与 `..` 段；导入信封的 scaffold 路径同样校验。

## 5. 审计与阶段识别

- 扫描时跳过 `.git`、`node_modules`、虚拟环境、缓存目录与敏感文件名。
- 每个必需产物的状态：`present` / `missing` / `stale` / `optional` / `waived`。
- 阶段完成度 = 必需产物完成率；整体完成度按所有阶段的必需项汇总。
- 阶段识别：取完成度 ≥ 70% 的最晚阶段作为候选，返回 `confidence` 与 `evidence`；**从不自动切换**，必须调用 `stage/confirm`。
- 项目顾问（`ProjectAdvisor`）的上下文包含规程审计摘要（当前阶段、完成度、待补项），建议会引用具体待补项；归类建议由审计结果生成，移动需逐项确认。
- 审计使用一次性项目文件索引复用所有 glob；AI 内容检查支持文本、Word/Excel/PPT 与 PDF（前 10 页）文本提取，单次最多 2 个文件、约 6000 字符。
- 未知文件归类：审计额外返回 `unclassified_files`——未被任何产物 glob 匹配、也不在任何声明目录下的文档型文件（`.md/.docx/.pdf/.xlsx` 等）。建议目标目录由目录 `purpose`、产物 `label` 关键词与扩展名打分（阈值 ≥ 3，最多 30 条），仅用于展示，不自动移动。
- 批量移动：`batch_move` 动作一次最多 30 个文件，执行前全量预校验（源存在、目标不冲突、拒绝重复与链式移动），成功后把反向映射写入 `playbook_state.last_move_batch`；`undo_last_batch_move` 全量校验后逆序还原，仅保留最近一批。审计返回 `undo_available: {at, count}` 供前端展示撤销入口。

### 规则投影

绑定规程、导入规程或确认阶段时，会把全局规则与当前阶段规则幂等写入 `project_constraints`（`template_key` 会展开为模板内的多条规则）；因此规程规则会随约束注入 system prompt，真正约束 AI 行为。同一内容不会重复写入；旧阶段规则保留，不会自动删除。写入的约束 `source` 标记为 `playbook:<stage>`，可用 `POST /playbook/rules/cleanup` 清理；绑定前会创建项目检查点。旧版阶段下拉框通过 `PATCH /projects/{id}` 修改阶段时，也会同步 `playbook_state` 与规则投影。

## 6. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/playbooks/builtin` | 内置规程摘要 |
| GET | `/api/v1/playbooks/builtin/{id}` | 完整规格 |
| GET | `/api/v1/playbooks/library` | 规程库列表（导入/分享的规程） |
| POST | `/api/v1/playbooks/library` | 保存规程到规程库（按 spec hash 去重） |
| DELETE | `/api/v1/playbooks/library/{id}` | 删除规程库条目 |
| GET | `/api/v1/projects/{id}/playbook` | 当前绑定 + 状态 + 审计 |
| PUT | `/api/v1/projects/{id}/playbook` | 绑定内置或自定义规程（生成快照） |
| GET | `/api/v1/projects/{id}/playbook/audit` | 重新审计 |
| PATCH | `/api/v1/projects/{id}/playbook/state` | 更新豁免 / 手动完成 / 条件标记 |
| DELETE | `/api/v1/projects/{id}/playbook` | 解绑规程（保留历史快照） |
| GET | `/api/v1/projects/{id}/playbook/versions` | 版本历史 |
| POST | `/api/v1/projects/{id}/playbook/rules/cleanup` | 删除规程投影到项目规则的约束 |
| POST | `/api/v1/projects/{id}/playbook/audit/ai` | 审计 + LLM 内容检查 / 阶段裁决（失败降级） |
| POST | `/api/v1/projects/{id}/playbook/author/preview` | AI 定制规程草案（schema 校验 + 确定性降级） |
| POST | `/api/v1/projects/{id}/playbook/stage/confirm` | 确认阶段（写历史） |
| POST | `/api/v1/projects/{id}/playbook/actions/apply` | 执行用户勾选动作 |
| GET | `/api/v1/projects/{id}/playbook/export?format=json\|md\|agents` | 导出 |
| POST | `/api/v1/projects/{id}/playbook/wiki/export` | 将规程手册写入项目 Wiki（仅覆盖 Sage 生成页） |
| POST | `/api/v1/playbooks/import/preview` | 校验 + diff |
| POST | `/api/v1/playbooks/import` | 导入并绑定（replace/merge/save_as_new） |

### 规程库

导入或分享的规程可保存到全局规程库（`playbook_library`，最多 100 条，按 spec hash 去重）；绑定项目时可直接选择 `library_id`，导入时也可勾选 `save_to_library` 一并入库。库中的规程与项目解耦，不包含任何项目文件内容。

## 7. 导出与分享

`.sageplaybook.json` 信封：

```json
{
  "format": "sage.playbook",
  "schema_version": "1.0",
  "exported_at": "2026-10-31T12:00:00Z",
  "exporter": {"app": "Sage", "version": "unknown"},
  "playbook": {"...": "完整规格"},
  "scaffold": {"include": true, "directories": ["01_开题"], "documents": []},
  "integrity": {"sha256": "..."}
}
```

- 默认只导出规程与空目录/文档骨架，不包含用户项目文件内容；
- 另有 Markdown 手册（人读）与 `AGENTS.md` / `CLAUDE.md` 兼容片段（供其他 AI 工具读取）；
- 导入时做 schema 校验、路径安全检查与结构 diff；同名规程默认另存为新 id。

## 8. 前端

- `src/features/playbook/PlaybookCard.tsx` 挂载在项目概览 Tab（完整模式）与设置 Tab（紧凑模式）；
- 展示阶段条、整体完成度、当前阶段待补项、阶段推进确认、导出/导入；
- 所有动作按钮均需用户点击；错误与结果就地显示。

## 9. 安全与隐私

- 渲染进程只传项目 id；路径由后端注册表与 `_safe_target` 二次校验；
- 导入拒绝 `../`、绝对路径；不会在项目外创建任何文件；
- 应用动作前创建 `.sage/checkpoints` 快照；
- 导出不包含项目实际内容；用户需自行决定分享范围。

## 10. 双分支注意

- 后端仅用标准库；避免 Python 3.9+ 语法；
- `datetime.now(timezone.utc)` 保留 `# noqa: UP017`，不可改为 3.11 的 `UTC`；
- Pydantic 模型沿用 main 的 `ConfigDict`，cherry-pick 到 win7 时按 v1 写法适配；
- 前端未引入新依赖。

## 11. 测试

- 单元：`test_playbook_spec.py`、`test_playbook_repo.py`、`test_playbook_auditor.py`、`test_playbook_actions.py`；
- 集成：`test_playbook_routes.py`（绑定 → 审计 → 动作 → 阶段确认 → 导出/导入 → 路径拒绝）；
- 前端：`PlaybookCard.test.tsx`、`playbookApi.test.ts`。

## 12. 已知限制（后续 P3）

- LLM 定制、内容检查与阶段裁决已实现（同步执行，失败自动降级）；尚无后台任务/取消/缓存。
- 规程编辑表单已覆盖名称/描述/阶段/产物/阶段规则/推荐里程碑/退出条件；内容检查等字段仍需 JSON 视图。
- 归类建议为启发式打分，可能误判；移动需勾选确认，批量移动支持撤销最近一批（不保留更早批次）。
- 暂无云端规程市场。
- `release/win7` cherry-pick 仍需按 pydantic v1 适配。
