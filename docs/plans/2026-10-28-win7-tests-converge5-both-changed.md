# Win7 第五批：both-changed 残余归因

- 日期：2026-10-28
- 基线：`release/win7` @ `be6a529ec`
- 对照：`main` @ `99ed15b98`
- 范围：`backend/tests` 中 `both-changed` 类目里尚未归因的 11 个文件

## 结果

| 文件 | win7 | main | 结论 |
|---|---|---|---|
| `integration/test_chat_orchestration_stream.py` | 13P | 13P | **取 main** |
| `unit/office/test_session_workspace.py` | 18P/1S | 18P/1S | **取 main** |
| `unit/test_chat_dispatcher_topology.py` | 6P | 6P | **取 main** |
| `unit/test_skill_auto_activation.py` | 57P | 57P | **取 main** |
| `unit/test_agent_tool.py` | 0P/18S | 0P/18S | **保 win7**（见 §2） |
| `integration/test_chat_stream.py` | 11P | 11P | **保 win7**（见 §1） |
| `integration/test_settings_route_legacy.py` | 33P | 32P/1F | 保 win7 |
| `unit/test_hooks.py` | 40P | 0P/40S | 保 win7 |
| `unit/test_memory_manager.py` | 37P | 30P | 保 win7 |
| `unit/test_orch_settings.py` | 11P | 6P/5F | 保 win7 |
| `unit/test_risk.py` | 30P | 29P/1F | 保 win7 |

## §1 main 的测试文件里有 py3.8 语法错误

`integration/test_chat_stream.py` 两边都是 11P、test id 一致，按常规该取 main，
但 py3.8 兼容闸门拦住：

```
integration/test_chat_stream.py:492: py38 runtime:
  parenthesized `with (a as x, b as y):` is Py3.9+ grammar (SyntaxError on 3.8)
```

main 版把嵌套 `with` 合写成括号形式，Python 3.8 上是 `SyntaxError`。
**main 的 CI 不跑 py3.8，所以这个缺陷在 main 侧一直没暴露。** win7 有
`Backend (Python 3.8, Win7 LTS)` 通道，取过来会当场打红 ⇒ 改为保 win7。

上一批实测发现 main 因 `from __future__ import annotations` 反而兼容 py3.8，
若把那次的结论推广成「main 的写法都安全」，这次就会漏掉。
**「通过数相同」不等于可收敛，py3.8 闸门是独立且必要的关卡。**

## §2 本地 skip 掩盖了真实差异（CI 抓到的）

`unit/test_agent_tool.py` 本地两边都是 0 passed / 18 skipped：

```
SKIPPED: subagent 安全测试需要 symlink 权限（WinError 1314）
```

Windows 未开开发者模式时普通进程无 symlink 权限。因此我在归因时判定它「等价、可收敛」。

**提交后 CI 的 py3.8 通道（Linux runner）真的跑了这 18 个用例，直接失败：**

```
FAILED test_whitelist_is_read_only
  AssertionError: assert {'browser_clo...ist_dir', ...} == {'browser_clo...snapshot', ...}
FAILED test_falls_back_to_constant_when_settings_unreadable
  assert 10 == 6
```

原因是 main 的断言照着 **main 的产品行为**写：只读工具白名单里多了 `snapshot`，
subagent 迭代预算的兜底常数是 6 而不是 win7 的 10。这些断言是产品行为的镜像，
**不能单方面取 main 的测试**（否则测试与产品对不上，等于用测试去要求产品行为）。
⇒ 该文件退回 win7 版。

**教训**：本地全 skip 的文件不能判等价 —— skip 数是 0 个通过、0 个失败，
但它对「哪边的断言更符合本分支产品」提供零信息。这类文件必须以 CI 为准，
或者用 `-W ignore` 之外的平台（Linux runner）验证。

## 验证

```
py3.11  4 文件逐个    13P / 18P+1S / 6P / 57P
py3.8   3 文件合并    75 passed, 19 skipped
py3.8   orchestration 13 passed
py3.8   dispatcher    6 passed
py3.8 闸门            Scanned 1890 files; 0 with violations
ruff check 5 文件     All checks passed
CI     py3.8 通道在 test_agent_tool 上失败 → 已退回 win7 版重跑
```

## 操作教训

pytest 在 Windows 上通过管道接 `tail` 会报 `ValueError: I/O operation on closed file`，
或看起来「卡死」——实际只是慢（`test_chat_dispatcher_topology` 单文件 52s）。
改成 `> 文件 2>&1; tail 文件` 就正常。本轮三次「疑似挂起」全是这个假象。
