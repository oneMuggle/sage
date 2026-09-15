# R32 批次 —— doctor Windows 语义定性（真产品 bug 修复）

> 背景：Windows 基线治理（W1-W5/#728）期间，doctor 运行时探测的 2 个用例
> 在 Windows 失败并被 skipif 标注"另行批次定性"。本批完成定性：**真产品 bug**。

## 根因
`_try_import_backend` 的探针环境只透传 `PATH` / `SYSTEMROOT` /
`PYTHONPATH`（+Win32 的 `PYTHONHOME`），**丢弃了 `USERPROFILE`**。

- Windows 上 `Path.home()` / `expanduser("~")` 读取 `USERPROFILE`，缺失时
  **无 pwd 兜底**（POSIX 有 getpwuid 兜底，所以 ubuntu CI 从未暴露）；
- 后端存在 import 期调用 `Path.home()` 的模块（如
  `tools/adapters/python_adapter.py:51`）→ 探针 `import backend.main`
  直接 `RuntimeError: Could not determine home directory.` → doctor 误报
  `import_backend=False`（用户在 Windows 上看到的诊断结论是错的）。

## 修复
探针环境补充透传 `USERPROFILE` / `HOMEDRIVE` / `HOMEPATH`（仅当宿主存在时
注入）——探针子进程获得与 supervisor 真实子进程一致的用户上下文。

## 移除的 skip
`TestRunDoctor` 类级与方法级共 2 处 skipif(nt) 移除：修复后 38/38 全绿
（含此前从未在 Windows 真实运行的 2 个运行时探测用例）。

## 验证
- 本机 Windows：手动复刻探针（stderr 捕获）确认根因为
  `RuntimeError: Could not determine home directory.`，修复后 exit 0；
- doctor 全量 38/38 绿；ruff 全过。
