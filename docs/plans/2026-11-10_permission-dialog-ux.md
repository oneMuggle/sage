# 权限对话框 UX 优化

> 分支: `feat/permission-dialog-ux`
> 日期: 2026-11-10
> 状态: 已实现（待合并后归档到技术手册/用户手册）

## 背景

多会话并行时，权限请求对话框存在两个 UX 问题：

1. **来源不可见**：对话框不显示请求来自哪个会话，用户只能依赖侧边栏的 amber dot 推断来源。多会话并发时尤其混乱。
2. **长命令截断**：后端 `summarize_tool_args()` 硬截断到 1000 字符，对话框宽度只有 448px（`max-w-md`），长 bash 命令难以阅读。

## 涉及文件

| 文件 | 改动类型 |
|------|----------|
| `src/widgets/permission/ApprovalDialog.tsx` | 新增会话来源标签；增大对话框宽度和 args 展示区高度 |
| `src/shared/lib/i18n/locales/zh/settingsAndModels.ts` | 新增 i18n key |
| `src/shared/lib/i18n/locales/en/settingsAndModels.ts` | 新增 i18n key |
| `backend/services/permission_gate.py` | 提升截断常量 |
| `src/widgets/permission/__tests__/ApprovalDialog.test.tsx` | 新增 4 条用例（会话标题/ id 兜底/ 无会话不渲染 / 长命令不截断） |
| `backend/tests/unit/test_permission_gate.py` | 文档字符串跟随常量名 |

## 技术方案

### M1：对话框显示来源会话

在对话框标题行（risk badge 上方或下方）显示来源会话名称：

```
[ShieldAlert] 工具执行审批          [安全]
             来自会话：重构认证模块
```

实现方式：
```typescript
// ApprovalDialog.tsx 顶部
import { useStore } from '../../shared/lib/store';

// 在组件内
const sessionTitle = useStore((s) =>
  currentRequest?.session_id
    ? s.sessions.find((sess) => sess.id === currentRequest.session_id)?.title
    : undefined
);
```

展示逻辑：
- 有 title → 显示 title（过长则 truncate 到 40 字符 + ellipsis）
- 无 title 但有 session_id → 显示 `会话 {id.slice(0,8)}`
- 无 session_id → 不显示（兼容 remote MCP 等无 session 场景）

### M2：长命令完整展示

**前端**：
- 对话框宽度 `max-w-md`（448px）→ `max-w-2xl`（672px）
- `args_summary` `<pre>` 块 `max-h-40`（160px）→ `max-h-72`（288px）

**后端**：
- `ARG_VALUE_MAX_CHARS`: 200 → 500
- `summarize_tool_args()` 整体截断: 1000 → 4000

这两个改动让用户能看见完整的中长命令（典型场景：带多个参数的 bash 命令、文件路径较长的 write_file 调用）。

## 实施步骤

- [x] M1：ApprovalDialog 新增来源会话标签
- [x] M2：提升后端截断常量
- [x] M2：增大前端对话框宽度和 args 展示区
- [x] 新增 i18n key（中/英）
- [x] 自动化验证：pytest（permission_gate 32 passed）、ruff、tsc --noEmit、
      eslint、vitest（permission 4 文件 38 passed）、i18n parity、
      architecture-check、production build + bundle-size 门禁全绿
- [ ] 人工验证：Electron 桌面端触发真实权限请求，目视确认会话标签与长命令展示
      （需桌面环境，未在本次自动化验证覆盖范围内）

## 风险评估

- **低风险**：纯前端 UI 改动 + 后端常量调整，不涉及审批逻辑和数据流
- **回归面**：仅影响审批对话框视觉，现有 `pendingBySession` 队列逻辑不变
- **向后兼容**：`session_id` 字段已存在于 store 中，无需后端改动
