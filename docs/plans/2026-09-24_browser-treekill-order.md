# 浏览器进程树回收时序修复（R26，2026-09-24）

- **现象**：每轮全量单测（含 `test_real_browser_smoke` 的真实浏览器路径）
  后泄漏一棵 chrome 进程树；crashpad/gpu 等子进程以孤儿态存活并锁住
  `data/browser-ephemeral/sage_browser_*` profile 目录，导致 worktree 清理
  与目录删除失败（Windows `rm -rf` Device or resource busy）。
- **根因**：`_terminate_session` 先 `terminate()/wait()` 杀父进程，**之后**
  才 `_kill_process_tree`（taskkill /T /F）。父进程退出后子进程已被系统
  重派生（reparent），`/T` 按父 PID 遍历不到任何树 —— taskkill 静默无操作，
  子进程全部孤儿化。
- **修复**：把 `_kill_process_tree` 提前到 terminate **之前** —— 父进程
  存活时 `/T` 能遍历整棵树（含 crashpad），一次性清光；非 Windows 该函数
  本就是 no-op，POSIX 仍走优雅 terminate 路径，行为不变。
- **测试**：`test_browser_persistence.py` 新增时序断言 —— tree-kill 必须是
  第一个终止动作，且优雅终止路径仍随后执行。
