# asyncio.get_event_loop 弃用清理（Round 25）

日期：2026-09-19 ｜ 分支：`feat/get-running-loop` ｜ 基线：3b454c9e3

## 背景

系统性扫描发现 4 处 deprecated 的 `asyncio.get_event_loop()`——均处于
**有运行循环保证的 async 上下文**内。py3.10+ 该调用触发 DeprecationWarning
（3.12 起无运行循环时直接 RuntimeError），`get_running_loop()`（3.7+ 起）
语义等价且全版本可用，直接替换。

## 改动

- `file_mutation_queue.py:97`：`get_event_loop().create_future()` → `get_running_loop()`
- `oauth_loopback.py:84/86`：`get_event_loop().time()` ×2 → `get_running_loop().time()`

## 范围外

- `browser_cdp.py:606`：sync `__exit__` 内的 get_event_loop 是 sync/async
  双路径设计的一部分（sync 测试路径依赖），非弃用语义问题，不动。

## 验证

- py38（3.8.20）：test_file_mutation_queue 6 passed、test_mcp_oauth_loopback 6 passed
- modern：同批 12 passed
- ruff 干净
