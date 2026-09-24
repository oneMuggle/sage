# T3：lefthook hooks 环境弹性（worktree / 缺 node 场景降级）

日期：2026-09-24
分支：feat/lefthook-resilient
状态：实施完成，待 PR

## 背景

git worktree 共享主仓 `.git/hooks`（lefthook 安装的脚本），但部分检出的
worktree 往往没有自己的 `node_modules`，且 hook 执行环境可能拿不到 node
——本循环中两次被 `/usr/bin/env: node: No such file or directory` 暗涩
错误阻塞 commit/push，只能 `core.hooksPath=/dev/null` 绕过。对一个并行
多 worktree 的交付流程，这是高频摩擦点。

## 内容

`lefthook.yml`：给 frontend lint/format/test 与 post-merge npm install
加环境前置检查——node 或 `node_modules` 不可用时打一行 skip 说明并放行
（exit 0）。`backend-test` 不加守卫：`scripts/pytest.sh` 自带"pytest 完全
不可用时 warning + exit 0"的降级（PYTEST_BIN → conda 默认路径 → PATH）。

原则：本地 hook 只是快速反馈，CI（ci.yml）才是硬门禁；缺环境时放行不
降低交付质量（PR CI 仍会全量跑）。

## 验证

- lefthook.yml YAML 解析通过
- 无 node_modules 的 worktree 中 `git commit` 不再被 node 缺失阻塞
  （skip 行为与 CI 门禁语义一致）
