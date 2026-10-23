# R93：修复 `run_sync` 在 Python 3.8 下的超时异常合同

## 背景

`backend/design/async_bridge.run_sync` 的公开合同承诺：调用方传入
`timeout` 且协程未在期限内完成时，抛
`concurrent.futures.TimeoutError`。实现用 `asyncio.wait_for` 保证超时后
取消协程，防止调用方已放弃后仍产生“幽灵写入”。

Python 3.8（Win7 LTS）中，`asyncio.wait_for` 抛出的
`asyncio.TimeoutError` 与 `concurrent.futures.TimeoutError` 不是同一异常
类；Python 3.11 起两者才统一为内建 `TimeoutError` 的别名。与此同时，
`future.result(timeout=...)` 自身也可能抛
`concurrent.futures.TimeoutError`，所以 Win7 上同一超时路径会随竞态暴露
两种异常类型。`release/win7` 的 py38 CI 已由
`test_async_bridge.py::TestRunSyncTimeout::test_timeout_raises_concurrent_future_timeout_error`
实证该漂移。

## 修复合同

1. 仅处理调用方显式传入 `timeout` 的 `asyncio.wait_for` 路径。
2. `wait_for` 冒泡的 `asyncio.TimeoutError` 在桥接边界归一为
   `concurrent.futures.TimeoutError`，保留原异常参数与异常链。
3. `timeout=None` 时不改协程结果或异常。
4. 继续由 `asyncio.wait_for` 取消超时协程，不改变共享事件循环、超时时长
   或 `future.result(timeout=...)` 的同步等待语义。
5. main 与 `release/win7` 使用同一实现，避免现代 Python 上“测试偶然同类”
   掩盖 Win7 合同漂移。

## 非目标

- 不改 Design Studio 的生成/迭代流程或 `DEFAULT_TIMEOUT`。
- 不把其他 `asyncio.wait_for` 调用点的异常类型一并改名；它们各自已有
  捕获或转换合同。
- 不调整发布版本号；本修复只是双线发布前的 CI/合同前置条件。

## 验证

- 定向运行 `backend/tests/unit/test_async_bridge.py`。
- 对改动文件运行 Ruff 与仓库 py38 静态兼容门。
- 分别以 main 和 `release/win7` 为基线开 PR，以 GitHub CI 为权威门禁；
  Win7 PR 必须实证 Backend (Python 3.8, Win7 LTS) 转绿。
