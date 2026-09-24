# R111 批次计划 —— RuntimeEnvTab UI 测试

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r111-scan`（基于 origin/main 612579e7）

## 背景

`src/pages/settings/RuntimeEnvTab.tsx`（498 行，开发环境 Tab）无测试。组件
含探测/诊断/试跑三段状态机、运行时自动选中、权限拒绝与超时文案等丰富分支。

## 批次内容

新增 `src/pages/settings/__tests__/RuntimeEnvTab.test.tsx`（11 用例）：

- 探测面板：loading '正在探测…'；成功列出运行时（version/path/推荐徽标）
  且自动选中推荐项（select value）；空运行时提示 + 错误详情；异常显示
  '探测失败: …' 与重试按钮；
- 诊断面板：'✓ 全部满足' + 诊断项 code 渲染 + 推荐运行时；失败显示
  '诊断失败: …'；
- 试跑：未选运行时 '执行' 禁用；成功展示 '退出码 0' 与 stdout；running 态
  '等待用户批准…'；权限拒绝 '权限被拒绝: …'；exec 收到
  {language, runtime_path} 透传。

实现要点：runtimeApi vi.mock 替身；组件挂载自动探测 + 自动选中会触发
effect 重跑（面板在 loading/ok 间闪断一次），动态断言一律 findBy* + 显式
timeout，避免与瞬态竞争。

## 验证矩阵

- 本机 vitest：11/11 通过（junction + 即摘协议）。
- CI：Frontend (TypeScript) lint + typecheck + vitest（覆盖率棘轮只增不减）。

## 不做

- 不改生产代码。
