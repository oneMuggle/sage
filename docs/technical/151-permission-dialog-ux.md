# 151. 权限对话框 UX 优化（来源会话 + 长命令展示）

**最后更新**: 2026-11-10
**适用分支**: release/win7
**关联文档**: [75 Allowed Paths](./75-allowed-paths.md)、[用户手册 §47](../user-manual/47-permission-dialog-ux.md)

---

## 151.1 背景

多会话并行时，权限审批对话框存在两个 UX 问题：

1. **来源不可见**：对话框不显示请求来自哪个会话，用户只能依赖侧边栏的 amber dot 推断来源。多会话并发时尤其混乱。
2. **长命令截断**：后端 `summarize_tool_args()` 硬截断到 1000 字符，对话框宽度只有 448px（`max-w-md`），长 bash 命令难以阅读。

## 151.2 设计决策

| 问题 | 方案 | 理由 |
| --- | --- | --- |
| 来源不可见 | 标题行下方显示来源会话标签 | 用户不必靠侧边栏 amber dot 反推 |
| 长命令截断 | 提升后端截断常量 + 增大前端展示区 | 让典型的中长命令（带多参数 bash / 长路径 write_file）完整可见 |

### 来源会话展示逻辑

- 有 `session_id` 且能匹配到 session title → 显示 title（过长 truncate + title tooltip）
- 有 `session_id` 但无 title → 显示 `session_id.slice(0, 8)`
- 无 `session_id` → 不渲染（兼容 remote MCP 等无 session 场景）

## 151.3 改动清单

### 后端

| 文件 | 改动 |
| --- | --- |
| `backend/services/permission_gate.py` | `ARG_VALUE_MAX_CHARS` 200→500；`ARG_SUMMARY_MAX_CHARS` 1000→4000 |

### 前端

| 文件 | 改动 |
| --- | --- |
| `src/widgets/permission/ApprovalDialog.tsx` | 对话框宽度 `max-w-md`→`max-w-2xl`；args `<pre>` 高度 `max-h-40`→`max-h-72`；新增来源会话标签（`useStore` 读 sessions） |
| `src/shared/lib/i18n/locales/zh/settingsAndModels.ts` | 新增 `permission.from_session` |
| `src/shared/lib/i18n/locales/en/settingsAndModels.ts` | 新增 `permission.from_session` |

### 测试

| 文件 | 改动 |
| --- | --- |
| `src/widgets/permission/__tests__/ApprovalDialog.test.tsx` | 新增 4 条用例：会话标题 / id 兜底 / 无会话不渲染 / 长命令不截断 |
| `backend/tests/unit/test_permission_gate.py` | 文档字符串跟随常量名 |

## 151.4 验证

**自动化**（全绿）：pytest（permission_gate 32 passed）、ruff、tsc --noEmit、eslint、vitest（permission 4 文件 38 passed）、i18n parity、architecture-check、production build + bundle-size 门禁。

**人工**：Electron 桌面端触发真实权限请求，目视确认会话标签与长命令展示（需桌面环境，未在自动化验证覆盖范围内）。

## 151.5 风险评估

- **低风险**：纯前端 UI 改动 + 后端常量调整，不涉及审批逻辑和数据流
- **回归面**：仅影响审批对话框视觉，现有 `pendingBySession` 队列逻辑不变
- **向后兼容**：`session_id` 字段已存在于 `PermissionRequest` 中，无需后端 schema 迁移
