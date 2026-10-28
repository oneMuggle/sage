# Win7 第五批：both-changed 残余归因（发现 main 自身的 py3.8 语法缺陷）

- 日期：2026-10-28
- 基线：`release/win7` @ `be6a529ec`
- 对照：`main` @ `99ed15b98`
- 范围：`backend/tests` 中 `both-changed` 类目中尚未归因的 11 个文件

## 方法

延续逐文件双版本实测 + test id 集合比对。每个文件：跑 win7 版 → 写入 main 版再跑 →
`git checkout --` 还原 → `--collect-only` 比对两边 test id 集合。

## 结果

| 文件 | win7 | main | 结论 |
|---|---|---|---|
| `integration/test_chat_orchestration_stream.py` | 13P | 13P | **取 main** |
| `unit/office/test_session_workspace.py` | 18P/1S | 18P/1S | **取 main** |
| `unit/test_agent_tool.py` | 0P/18S | 0P/18S | **取 main** |
| `unit/test_chat_dispatcher_topology.py` | 6P | 6P | **取 main** |
| `unit/test_skill_auto_activation.py` | 57P | 57P | **取 main** |
| `integration/test_chat_stream.py` | 11P | 11P | **保 win7**（见下） |
| `integration/test_settings_route_legacy.py` | 33P | 32P/1F | 保 win7 |
| `unit/test_hooks.py` | 40P | 0P/40S | 保 win7 |
| `unit/test_memory_manager.py` | 37P | 30P | 保 win7 |
| `unit/test_orch_settings.py` | 11P | 6P/5F | 保 win7 |
| `unit/test_risk.py` | 30P | 29P/1F | 保 win7 |

5 个待合的 test id 集合在两边完全一致（无「仅 win7」「仅 main」条目）。

## 关键发现：main 的测试文件里有 py3.8 语法错误

`integration/test_chat_stream.py` 两边跑出来都是 11P、「等价」，按常规应当取 main。
但 py3.8 兼容闸门拦住了：

```
integration/test_chat_stream.py:492: py38 runtime:
  parenthesized `with (a as x, b as y):` is Py3.9+ grammar (SyntaxError on 3.8)
```

main 版把嵌套 `with` 合写成了括号形式，这在 Python 3.8 上是 `SyntaxError`。
**main 的 CI 不跑 py3.8，所以这个缺陷在 main 侧一直没暴露。** 而 win7 的
CI 有 `Backend (Python 3.8, Win7 LTS)` 通道，取过来会直接把这条通道打红。

⇒ 该文件由「取 main」改为**保 win7**（win7 版是等价的嵌套 `with` 写法）。

这条也说明：**「通过数相同」不足以判定可收敛，py3.8 闸门是独立的必要关卡**。
前几批的经验（main 因 `from __future__ import annotations` 反而兼容）不能推广成
「main 的写法都安全」。

## 关于 `test_agent_tool.py` 的 18 个 skip

两边都是 0 passed / 18 skipped，原因是：

```
SKIPPED: subagent 安全测试需要 symlink 权限（WinError 1314）
```

Windows 上未开启开发者模式时，普通进程没有创建 symlink 的权限。属环境限制，
两边一致，不是 parity 差异，也不需要在 CI 上处理（CI runner 同样受限）。

## 验证

```
py3.11  5 文件逐个    13P / 18P+1S / 0P+18S / 6P / 57P
py3.8   3 文件合并    75 passed, 19 skipped
py3.8   orchestration 13 passed
py3.8   dispatcher    6 passed
py3.8 兼容闸门        Scanned 1890 files; 0 with violations
ruff check 5 文件     All checks passed
```

## 一个操作教训

pytest 在 Windows 上通过管道接 `tail` 时会报 `ValueError: I/O operation on closed file`，
或者看起来「卡死」——实际是慢（`test_chat_dispatcher_topology` 单个文件要 52s）。
**改为 `> 文件 2>&1; tail 文件` 后就正常。** 本轮有三次「疑似挂起」都是这个原因造成的误判。
