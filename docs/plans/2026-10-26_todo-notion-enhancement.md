# 待办模块 Notion 化增强 (Phase 1)

> 日期: 2026-10-26
> 分支: feat/todo-notion-enhancement
> Worktree: .worktrees/feat-todo-notion-enhancement (前端 1440 / 后端 8785)

## 背景与目标

Sage 的 Persistent Todo 模块后端能力完整（15 字段 + 过滤/排序 API），但前端 UI
停留在"只能输入标题"的 MVP 状态，与 Notion 等现代任务管理工具差距明显。

**Phase 1 目标**：将前端从 MVP 提升到"可用"——补齐核心交互，不新增后端字段。

## 现状分析

| 能力 | 后端 | 前端 |
|------|------|------|
| 创建（仅标题） | ✅ | ✅ 唯一功能 |
| 创建（全字段：desc/priority/due_at/project_tag） | ✅ API 支持 | ❌ 未暴露 |
| 行内编辑 | ✅ PUT API | ❌ 无 UI |
| 过滤（status/priority） | ✅ | ❌ 无控件 |
| 排序（due_at/priority/created_at） | ✅ | ❌ 无控件 |
| 子任务（parent_id） | ✅ DB + FK | ❌ 无 UI 渲染 |

## 实施步骤

### Phase 1（本次 PR，前端纯增量，无后端改动）

- [x] **步骤 1：增强创建表单** ✅ tsc + eslint 通过
  - 新建: `src/pages/todo/TodoCreateForm.tsx`
  - 新建: `src/pages/todo/todoDateUtils.ts`（日期工具提取）
  - 新增字段: description, priority, due_at, project_tag
  - 默认折叠详细字段，点击"更多选项"展开

- [x] **步骤 2：行内编辑** ✅ tsc + eslint 通过
  - 新建: `src/pages/todo/TodoRowEditor.tsx`
  - 点击标题 → 原地 input，Enter/blur 保存
  - 点击 priority badge → 循环切换 high/medium/low
  - 点击截止日期 → 日期选择器弹出
  - 调用 `todoStore.update(id, changes)`

- [x] **步骤 3：Filter / Sort 工具栏** ✅ tsc + eslint 通过
  - 新建: `src/pages/todo/TodoToolbar.tsx`
  - 状态过滤: 下拉（全部/待办/进行中/已完成/已取消）
  - 优先级过滤: 下拉（全部/高/中/低）
  - 排序: 下拉（截止日期/优先级/创建时间）+ 升降序切换
  - 文本搜索框

- [x] **步骤 4：批量操作** ✅ 集成在 TodoPage.tsx
  - TodoRowEditor 左侧 checkbox
  - 顶部全选 checkbox + 批量完成/删除操作栏

- [x] **步骤 5：子任务渲染（只读展开）** ✅ tsc + eslint 通过
  - 新建: `src/pages/todo/TodoSubtaskTree.tsx`
  - 按 parent_id 构建父子关系，最多 2 层递归
  - 子任务父节点显示进度条

### Phase 2（后续 PR，需后端改动）

- [ ] 看板视图（需 sort_order 字段）
- [ ] 日历视图
- [ ] 全文搜索（后端 FTS5）

## 涉及的文件

| 文件 | 操作 |
|------|------|
| `src/pages/TodoPage.tsx` | 修改 |
| `src/pages/todo/TodoCreateForm.tsx` | 新建 |
| `src/pages/todo/TodoRowEditor.tsx` | 新建 |
| `src/pages/todo/TodoToolbar.tsx` | 新建 |
| `src/pages/todo/TodoSubtaskTree.tsx` | 新建 |
| `src/entities/todo/todoStore.ts` | 修改（load 接受 params） |

## 风险评估

- 无新增 npm 依赖，复用 lucide-react + Tailwind
- todoStore.load() 签名变更：grep 确认只有 TodoPage 调用，影响低
