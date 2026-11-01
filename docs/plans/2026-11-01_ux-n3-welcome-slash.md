# UX N3：欢迎页斜杠菜单（2026-11-01）

> 分支：`feat/ux-n3-welcome-slash`  
> 基线：`origin/main`（N2 合并后）

## 背景

默认新会话页 `/welcome` 的 `WelcomeInputCard` 不处理 `/`，且 `enableCommandItem={false}`，
用户在首屏输入 `/` 完全无反应；只有进入已有会话的 ChatInput 才有 slash 菜单。

## 实现

- `WelcomeInputCard`
  - 挂载时拉取 `skillsApi.list()`，仅保留 `dispatch.user_invocable === true` 的 SKILL.md 技能；
  - `handleChange` 检测 `/` 前缀，与静态命令 `mergeSlashCommands` 合并后过滤；
  - 复用 `InputCard` 既有 slash props（菜单渲染 + 上下键/Enter/Esc）；
  - 选择行为：
    - skill：`skillsApi.execute` → 发送返回内容，失败回退 prompt；
    - prompt/plan：`commandToPrompt` 后发送；
    - template：回填输入框；
    - navigate：跳转路由；
    - clear/help：清空或发送帮助列表；
    - compact/learn/worktree 在欢迎页无意义，忽略。
  - 开启 `+` 菜单的「命令与技能」入口（移除 `enableCommandItem={false}`）。
- 测试：
  - `/` 打开菜单并执行 `/help`；
  - 无匹配查询时关闭菜单；
  - mock `skillsApi.list` 避免测试期重试噪音。

## 验证

- `WelcomeInputCard` 11 tests passed；
- `npm run typecheck` 通过；`eslint` 0 error；
- `architecture-check` 通过。

## 不在本批

设置页标题层级/整体美化、桌宠安装包发布。
