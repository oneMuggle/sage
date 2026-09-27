# R164：safe_run 安全子进程封装单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；runtime_probe/exec 共用的安全子进程
  封装（argv 数组禁 shell / 输出上限 / 进程组超时回收 / 环境白名单）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/runtime_safe_run.py`（181 行，safe_run——适配器与 runtime_exec
共用的安全子进程入口：非零退出码/stderr/stdin/超时回收/输出上限/
环境白名单）此前零测试。真实 subprocess 测试（sys.executable），跨
平台（Windows/Linux CI 均可跑）。

## 覆盖矩阵（约 14 例）

1. 空 argv → error"argv 不能为空"、exit_code None；
2. 成功：stdout 捕获 + exit_code 0；3. 非零退出 → exit_code 3；
4. stderr 捕获；5. input_text 经 stdin 传入；6. 超时 → timed_out
True + error"safe_run 超时"；7. 输出超上限 → output_truncated True；
8. 不存在的可执行文件 → "找不到可执行文件"；9. cwd 生效（读 cwd 下
文件）；10. `_sanitized_env`：白名单过滤（父进程非白名单变量不进子
环境）、overrides 叠加生效；11. SAFE_ENV_ALLOWLIST 非空；12. output_cap
超 MAX_OUTPUT_CAP 封顶。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
