# R91 批次计划 —— 后端测试事件循环守卫（conftest 兜底 + 污染源修复）

日期：2026-09-20 ｜ worktree：`.worktrees/feat-r91-eventloop-guard`（基于 origin/main 758dcc5d）

## 背景（R89 win7 cherry #1305 实证）

PR #1305（R89 来源去重 cherry 到 release/win7）的 **Backend (Python 3.8, Win7 LTS)**
job 连爆 27 例：`test_replan_tool.py` 全部用例报
`RuntimeError: There is no current event loop in thread 'MainThread'`。

根因链：
1. `test_subagent_events.py` 在 finally 里 `asyncio.set_event_loop(None)`（主线程），
   把 loop policy 置为"已调用 set 且无 loop"状态；
2. py3.8-3.11 同语义：此后 `asyncio.get_event_loop()` 直接 RuntimeError，
   `asyncio.Queue()` / `asyncio.Event()` 构造期隐式 get_event_loop() 连带炸；
3. pytest-xdist `-n auto --dist loadfile` 按文件名轮询分桶，cherry 新增
   `tests/unit/chat/test_sources_extractor.py` 使分桶位移，污染源与受害者
   首次同桶 → 全文件连爆。main 的 Backend job 此前通过纯属分桶运气，
   任何新增测试文件都可能引爆。

win7 侧已在 #1305 以文件级 autouse fixture 兜底（仅护 test_replan_tool.py）。
本批在 main 上做系统性修复。

## 批次内容

1. **污染源修复**（`backend/tests/unit/test_subagent_events.py:463`）：
   `asyncio.set_event_loop(None)` → `asyncio.set_event_loop(asyncio.new_event_loop())`，
   注释说明原因。loop policy 保持可用态。
2. **conftest 兜底防线**（`backend/tests/conftest.py`）：新增 autouse fixture
   `_ensure_usable_event_loop` —— 测试开始时 `get_event_loop()` 若 RuntimeError
   则新建并安装 loop；已有 loop（含 pytest-asyncio 管理的）零操作；自建 loop
   留在 policy 里复用不关闭。对既有测试零行为变化。

## 验证矩阵

- 本机 anaconda py3.9（与 py3.8/py3.11 同 get_event_loop 语义）：
  - 机制复现：`set_event_loop(None)` 后 `asyncio.Queue()` → RuntimeError；
    守卫逻辑介入后恢复正常。
  - 受影响面：`pytest backend/tests/unit/test_replan_tool.py
    backend/tests/unit/test_subagent_events.py -q`（本地依赖可用时）。
- CI：Backend (Python) / Backend (Python 3.8, Win7 LTS)（cherry PR 时）。

## 后续

- win7 分支目前只有文件级 fixture；下次 win7 对齐时把 conftest 守卫一并
  cherry 过去（属 bug fix 类，允许回移），之后可撤销文件级 fixture。

## 不做

- 不改生产代码（纯测试基建）。
- 不动 pytest-asyncio 的 loop 管理策略。
