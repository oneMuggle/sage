# 对标批次：L1 审批拒绝附反馈（Deny with feedback）+ 差距清单勘误

日期：2026-09-26 ｜ 关联：`docs/plans/2026-09-24_zcode-parity-gap-analysis.md`（L1 行）
参照：ZCode `PermissionDialog` 的 `ZCodePermissionOption`（`freeText` 拒绝反馈）

## 0. 结论速览

**L1（审批作用域分级）经逐项核实后大部分已存在**：sage 审批对话框已有「允许一次 /
项目级允许（allowed_paths 规则）/ 拒绝 + remember 持久化规则 / diff 预览」，
与 ZCode 的分级选项实质对齐。**唯一缺口是「拒绝附文字反馈」**（ZCode 的
`freeText`）——拒绝理由目前只有机械的 `（未获批准: gui）`，用户无法告诉模型
为什么拒绝、它该改用什么方案。

**F1（任务查找器）勘误为 ✅**：gap-analysis 文档此前标 ❌ 系核实失误——
CommandPalette 全局搜索（≥2 字符）已渲染「会话」分组并支持跳转
（`CommandPalette.tsx:444`），与 ZCode `TaskFindDialog` 实质对齐。本文同步修正
gap-analysis 状态行。

## 1. L1 现状链路（已核实）

```
ApprovalDialog(拒绝按钮) → invoke permissions_answer {requestId, approved, remember}
  → POST /api/v1/permissions/{id}/answer (ApprovalAnswerBody: approved/remember, extra=forbid)
    → PermissionGate.answer(request_id, approved, remember)
      → future.set_result(ApprovalAnswer(approved, remember, answered_by="gui"))
        → agent.py 拒绝分支: reason=f"{decision.reason}（未获批准: {answer.answered_by}）"
```

## 2. 实现（拒绝反馈字段全链路贯通）

### 2.1 后端（3 文件）

1. **`backend/services/permission_gate.py`**：`ApprovalAnswer` 增加字段
   `reason: str = ""`（frozen dataclass 默认值向后兼容所有既有构造点：
   timeout/default-deny 均空）；`answer()` 签名加 `reason: str = ""` 透传。
2. **`backend/api/permission_routes.py`**：`ApprovalAnswerBody` 加
   `reason: str = ""`（≤500 字符约束；v1/v2 双兼容写法保持）；`answer_approval`
   传递给 gate。
3. **`backend/core/legacy/agent.py`**：拒绝分支 reason 改为——有用户反馈时
   `（未获批准: gui，用户反馈: <reason>）`，否则维持原文。模型拿到拒绝理由后
   可调整方案重试，而不是盲目重放。

### 2.2 前端（1 文件 + i18n）

`ApprovalDialog.tsx`：点击「拒绝」→ 展开 textarea（可留空、Esc 收起、Enter 提交）
→ `permissions_answer` 带 `reason`。留空行为与现状完全一致。

### 2.3 测试

- 后端：gate 层 reason 透传 / API body 解析（含 forbid 越界字段拒绝）/ agent
  拒绝 reason 拼接三处单测。
- 前端：拒绝展开输入框、留空提交、带反馈提交三用例。

### 2.4 兼容性

- `ApprovalAnswer` 默认值保证 timeout/default-deny 构造点零改动。
- API body 加默认值字段 → 旧前端不带 reason 仍可调用（extra=forbid 只禁未知字段）。
- py38：dataclass 默认值、str 约束（pydantic v1 兼容写法 `max_length` 用 Field）。

## 3. 验收

- `npx tsc --noEmit` 0；触碰点 vitest 全绿；后端 pytest 触碰点全绿；ruff 0。
- gap-analysis 文档 L1 行改 ✅（附 PR 号），F1 行改 ✅（勘误）。
