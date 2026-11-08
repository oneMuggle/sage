# §138 项目工作台 · 规则中心

**日期**: 2026-11-07
**作者**: sage team
**关联**: spec `docs/plans/2026-11-07_project-workbench-rules-center.md`（已归档）

## 1. 信息架构

- 应用侧栏（`src/widgets/sidebar/sections/WorkbenchProjectList.tsx`）：每行单一菜单入口，整行点击进入详情。
- `/projects` 总览页（`src/pages/ProjectsOverview.tsx`）：搜索 + 类型筛选 + 状态筛选 + 排序 + 批量导出规则包。
- 治理页（`src/pages/governance/GovernanceShell.tsx`）：5 章 Tab —— 概览 / 规则 / 资料 / 文件 / 设置。深链 `?tab=...`，旧 `knowledge=wiki` → `knowledge`，旧 `playbook` → `rules`。

## 2. 规则中心四层适配器

`backend/services/rules_registry.py:33-63` 统一 DTO（snake_case）：

```python
@dataclass
class RuleEntry:
    id: str
    layer: str           # 'constraint' | 'playbook' | 'doc' | 'global'
    source_label: str
    scope: str
    category: str
    content: str
    enabled: bool = True
    editable: str = "full"  # full | partial | readonly
    priority: int = 5
    trigger: Optional[str] = None
    updated_at: Optional[int] = None
    origin: Optional[str] = None
```

| 适配器               | 写入 editable                                         | 存储                                     |
| -------------------- | ----------------------------------------------------- | ---------------------------------------- |
| `ConstraintAdapter`  | source='user' → full；source='playbook:\*' → readonly | `project_constraints`                    |
| `PlaybookAdapter`    | partial（只能跳规程编辑器生成新版本）                 | `project_playbooks.spec_json`            |
| `GlobalRulesAdapter` | full                                                  | `~/.sage/SAGE.md`                        |
| `ProjectDocAdapter`  | SAGE.md full，其余 readonly                           | 项目根 `SAGE.md`/`CLAUDE.md`/`AGENTS.md` |

`effective(project)`（`rules_registry.py:427-433`）返回 `{entries, conflicts}`：只含已启用条目。注入顺序是「全局 → 项目总纲 → 项目规则 → 当前阶段规程 → 内容检查」。同 category + 不同内容 → 标冲突（只提示不合并）。

## 3. 规则包信封格式

`backend/services/rules_transfer.py:131-150` 定义 `.sagerules.json` 信封：

```json
{
  "format": "sage.rules",
  "version": 1,
  "exported_at": "2026-11-07T12:34:56Z",
  "project": { "name": "...", "type": "..." },
  "layers": {
    "constraints": [...],
    "project_docs": { "SAGE.md": "# ..." },
    "global_rules": "# ...",
    "playbook": { "format": "sage.playbook", "..." : {} }
  }
}
```

- 字段命名：snake_case（`exported_at`、`project_docs`、`global_rules`）
- `exported_at` 为 ISO-8601 UTC 字符串，非 epoch 毫秒
- 导出：`GET /projects/{id}/rules/export?format=json|md|agents&include_constraints=true&include_playbook=false&include_global=false&include_docs=true`
- 导入：两步 —— `POST /rules/import/preview`（返回 `candidates` 含 `status=new|duplicate|conflict`）→ `POST /rules/import/apply`（只提交 `selected` 候选 id）
- 去重键：约束 = `(category, _normalize(content))`；doc = `filename`；global = `"SAGE.md"`；playbook 永远 `status=new`
- 文件大小上限 `MAX_EXPORT_FILE_BYTES = 1_048_576`（`rules_transfer.py:30`）

## 4. 后端 API 速查

| 方法       | 路径                                   | 说明                               |
| ---------- | -------------------------------------- | ---------------------------------- |
| GET        | `/projects/{id}/rules`                 | 四层聚合                           |
| POST/PATCH | `/projects/{id}/rules`                 | body `{layer, rule_id, ...}`       |
| DELETE     | `/projects/{id}/rules?layer=&rule_id=` | 查询参数（无 body）                |
| GET        | `/projects/{id}/rules/effective`       | 生效顺序（`{entries, conflicts}`） |
| GET        | `/projects/{id}/rules/raw?layer=`      | 整文件预览（doc/global）           |
| POST       | `/projects/{id}/rules/patches/preview` | AI diff 预览                       |
| POST       | `/projects/{id}/rules/patches/apply`   | 应用 AI patch                      |
| GET        | `/projects/{id}/rules/export`          | 导出（格式：json/md/agents）       |
| POST       | `/rules/import/preview`                | 导入预览                           |
| POST       | `/rules/import/apply`                  | 导入应用                           |
| PATCH      | `/playbooks/library/{id}`              | 重命名/描述/标签                   |
| GET        | `/playbooks/library?q=`                | 搜索                               |

导出参数（`rules_routes.py:755-765`）：

- `format`（json|md|agents），响应 `format` 字段映射：json→`"sage.rules"`，md→`"markdown"`，agents→`"agents"`（`:687-694`）
- 文件名（`:704-710`）：`rules-<name>.sagerules.json` / `.sagerules.md` / `AGENTS.md`

## 5. 前端模块拓扑

```
src/features/rules/
├── AiRulePatchDrawer.tsx     # AI diff 抽屉
├── EffectiveRulesDrawer.tsx  # 生效预览
├── PatchCard.tsx             # 单条 diff 卡
├── RuleEditorBody.tsx        # 编辑器主体
├── RuleEditorDialog.tsx      # 新建/编辑对话框
├── RuleEditorFields.tsx      # 表单字段
├── RuleRow.tsx               # 行渲染
├── RulesExportDialog.tsx     # 导出对话框
├── RulesImportDialog.tsx     # 导入对话框
├── RulesPanel.tsx            # 容器（搜索/筛选/分组）
├── RulesPanelSections.tsx    # 分组渲染
├── rulesDownload.ts          # 下载工具
├── rulesView.ts              # 视图状态
├── useRuleEditorForm.ts      # 表单 hook
└── __tests__/...

src/pages/governance/
├── GovernanceShell.tsx       # 规则 Tab 直接调用 RulesPanel（:166）
├── sections/
│   ├── OverviewSection.tsx
│   ├── KnowledgeSection.tsx
│   ├── FilesSection.tsx
│   └── SettingsSection.tsx
└── __tests__/GovernanceShell.test.tsx
```

注意：无 `RulesSection.tsx`。`GovernanceShell.tsx:166` 在 `activeTab === 'rules'` 时直接渲染 `<RulesPanel>`。

## 6. 规程库增强

- 搜索：按名称/描述/标签（`playbook_library_repo.py:59-64`）
- 编辑：重命名、改描述、打标签
- 元数据位置（`playbook_library_repo.py:34-56`）：
  - `spec["description"]`（规程描述）
  - `spec["meta"]["tags"]`（标签数组）

## 7. 测试

- 后端单测：`test_rules_registry.py`、`test_rule_patch.py`、`test_rules_transfer.py`、`test_markdown_rules.py`、`test_playbook_library_repo.py`
- 后端集成：`test_rules_api.py`、`test_rules_write_api.py`、`test_rules_patch_api.py`、`test_rules_import_export.py`、`test_playbook_library_search_and_update.py`
- 前端：`src/features/rules/__tests__/{RulesPanel, AiRulePatchDrawer, RulesImportDialog, RulesExportDialog, PatchCard, RuleEditorDialog, RuleEditorFields}.test.tsx`、`src/pages/governance/__tests__/GovernanceShell.test.tsx`
