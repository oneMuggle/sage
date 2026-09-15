# R32 批次 E —— script_runner 执行链 Windows 等价（技能脚本执行解锁）

> 承接 #766（绑定读取）：SKILL.md 脚本执行的确认→快照→沙箱→清理全链路
> 此前在 Windows 因两处 POSIX-only 依赖而不可用。本批定性并打通。

## 定性结论
- 沙箱适配器（SubprocessSandboxAdapter）**本就支持 Windows**（taskkill 树清理分支）；
- 真正的断点只有一处：快照创建使用 POSIX-only 的 `os.fchmod`，Windows 上
  `AttributeError` → 确认后快照失败 → 脚本永远无法执行。

## 改动
- `_create_snapshot`：`fchmod`/目录 chmod 位调整改为 POSIX-only；
  Windows 依赖 mkdtemp 的每用户 %TEMP% 私有隔离（安全语义等价，docstring 注明）。
- `test_skill_md_script_runner.py`：
  - 解除模块级 skipif(nt)——25 例中 23 例在 Windows 真实执行全绿；
  - 快照权限断言改 POSIX-only（Windows 由每用户隔离替代）；
  - O_NOFOLLOW 缺失 fail-closed 用例标注 POSIX-only 前提（Windows 原生
    分支不依赖 O_NOFOLLOW）；
  - symlink 组件拒绝用例加能力探测 skip（本地无特权；CI windows runner
    有特权真实执行）。

## 验证
- 本机 Windows：23 passed + 2 skipped + **0 failed**（端到端：确认→快照→
  沙箱执行→清理在真实 Windows 跑通）。
- ubuntu CI 验证 POSIX 行为不变。
