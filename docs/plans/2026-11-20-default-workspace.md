# 默认工作区语义重构

**日期**：2026-11-20  
**分支**：`feat/default-workspace`（基于 `main`）  
**PR 目标**：`main`（完成后 cherry-pick 到 `release/win7`）

---

## 背景与目标

当前"新会话页"有一个选项"不绑定项目"，语义上等价于 `skip_workspace_binding=True`，后端完全跳过解析链 → `workspace_binding=None`。结果：

- 所有依赖 `ToolPolicy.workspace_root` 的工具（wiki / office / file / edit / patch / codebase_search / git / checkpoint / browser_screenshot / browser_interact upload / browser_open downloads 等 12+ 个）都报错"需要绑定工作区"或失去沙盒保护。
- 用户选了"不绑定"后，实际上丧失了大部分能力，这与主流 AI 应用（Cursor 用 `$HOME`，Cline 用 `~/Desktop`）的语义相悖。

**目标**：重新定义"不绑定项目"为"使用默认工作区 `~/Sage/`"，让所有工具在任何情况下都有合法的 `workspace_root`。

---

## 设计决策

### 1. 默认工作区位置

`~/Sage/`（Linux/macOS），`%USERPROFILE%\Sage\`（Windows）

- 跨安装持久化（独立于应用数据目录）
- 用户可见可管理（不在隐藏目录里）
- 首次使用时懒创建
- 失败时回落 `<tmpdir>/sage-workspaces/default`

### 2. 语义模型

| 用户选择 | 旧行为 | 新行为 |
|----------|--------|--------|
| "默认工作区"（原"不绑定项目"） | `workspace_binding=None`，工具全失效 | `workspace_binding={path: ~/Sage/, source: "default"}`，工具全正常 |
| 选择具体项目 | 绑定到项目目录 | 不变 |
| 不选择（自动检测） | 走解析链，失败则 `None` | 走解析链，失败则 `~/Sage/`（原来失败则 `None`） |

### 3. 受影响工具清单（全部自动生效，无需单独修改）

所有通过 `ToolPolicy.workspace_root` 获取路径的工具：
- `wiki_tool`、office 系列工具
- `file_tool`、`edit_tool`、`patch_tool`
- `codebase_search`、`symbol_search`
- `git_tool`、`checkpoint_tool`
- `browser_screenshot`、`browser_interact upload`、`browser_open`（downloads）、`browser_downloads`

### 4. UX 文案变更

| 位置 | 旧文案 | 新文案 |
|------|--------|--------|
| `ProjectPicker` | "不绑定项目" | "默认工作区（~/Sage/）" |
| `WorkspaceBindModal`（null 态） | "尚未绑定工作区目录" | "当前为默认工作区 ~/Sage/（可切换到具体项目）" |
| `SessionWorkspaceProvider`（source="default"） | 无区分 | 显示"默认工作区"标识 |

---

## 文件变更清单

### 后端

| 文件 | 变更 |
|------|------|
| `backend/services/default_workspace.py` | 新增 `DEFAULT_WORKSPACE_DIRNAME = "Sage"`；新增 `WorkspaceSource.DEFAULT`；新增 `default_workspace_path()` → `~/Sage`；新增 `resolve_to_default()` → `WorkspaceResolution` |
| `backend/api/legacy_session_routes.py` | `skip_workspace_binding=True` 分支改为调 `resolve_to_default()` 并绑定到 `~/Sage/` |
| `backend/api/workspace_default_routes.py` | 响应 DTO 加 `source: "default"` 支持（已有，无需改动） |

### 前端

| 文件 | 变更 |
|------|------|
| `src/widgets/welcome/ProjectPicker.tsx` | `value="none"` → `value="default"`；label "不绑定项目" → "默认工作区（~/Sage/）"；onValueChange 映射不变 |
| `src/pages/Welcome.tsx` | 注释更新；逻辑不变（`effectiveProjectId === null` 仍触发 skip） |
| `src/shared/lib/store.ts` | 注释更新；逻辑不变 |
| `src/features/workspace/WorkspaceBindModal.tsx` | null 态文案改为"当前为默认工作区" |
| `src/app/providers/SessionWorkspaceProvider.tsx` | 识别 `source="default"` 显示标识 |

### 测试

| 文件 | 变更 |
|------|------|
| `backend/tests/integration/test_skip_workspace_binding.py` | 更新期望：skip=true 时 binding 非 null，path=`~/Sage/` |
| `backend/tests/unit/services/test_default_workspace.py` | 新增 `test_resolve_to_default`；scratch 测试路径改为 `~/Sage` |

---

## 实施步骤

- [x] 步骤 1：`default_workspace.py` —— 新增 `DEFAULT_WORKSPACE_DIRNAME`、`WorkspaceSource.DEFAULT`、`default_workspace_path()`、`resolve_to_default()`、`_ensure_default_workspace()`
- [x] 步骤 2：`legacy_session_routes.py` —— `skip_workspace_binding=True` 改为调 `resolve_to_default()` 并绑定
- [x] 步骤 3：`ProjectPicker.tsx` —— 改 value、label
- [x] 步骤 4：`Welcome.tsx`、`store.ts` —— 更新注释（注释已在 skip 测试文件中同步更新）
- [x] 步骤 5：`WorkspaceBindModal.tsx`、`SessionWorkspaceProvider.tsx` —— 更新文案（Provider 无需改动）
- [x] 步骤 6：测试更新
  - `test_skip_workspace_binding.py` — skip=true → binding 非 null, path=`~/Sage/`, source="default"
  - `test_default_workspace.py` — SCRATCH→DEFAULT 断言；新增 `resolve_to_default`、`default_workspace_path` 测试
  - `ProjectPicker.test.tsx` — 文案 `"不绑定项目"` → `"默认工作区（~/Sage/）"`
  - `Welcome.skipWorkspaceBinding.test.tsx` — describe 标题和注释更新
- [ ] 步骤 7：本地验证（启动桌面端，在默认工作区下测试工具）

---

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| `~/Sage/` 创建失败（权限/磁盘满） | 工具仍失效 | 回落 `<tmpdir>/sage-workspaces/default`，与现有 scratch 回落机制一致 |
| 现有 scratch `<userData>/workspaces/default` 中有用户文件 | 用户数据分散 | 不迁移（保持原位），新旧并存；文档说明 |
| `value="default"` 与已有 `value="none"` 前端状态冲突 | 类型错误 | `value="default"` 仍映射为 `null`，下游逻辑完全不变 |
| 测试失败 | CI 红 | 先更新测试再提交 |

---

## 主流应用对齐

| 应用 | 无项目兜底 | 位置 |
|------|-----------|------|
| Cursor | `$HOME` | 用户主目录 |
| Cline | `~/Desktop` | 桌面 |
| Sage | `~/Sage/` | 独立目录（更整洁） |
