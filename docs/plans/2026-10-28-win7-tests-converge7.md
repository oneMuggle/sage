# Win7 第七批：剩余未归因文件实测（含一个 Windows 上的真失败）

- 日期：2026-10-28
- 基线：`release/win7` @ `52e4aee08`
- 对照：`main` @ `5cd4d5871`
- 范围：`backend/tests` 中 38 个「真实代码差异」里尚未实测过的 13 个

## 结果

| 文件 | win7 | main | 结论 |
|---|---|---|---|
| `unit/test_mcp_oauth_store.py` | **18P/1F** | 19P/0F | **取 main**（修 Windows 失败） |
| `integration/test_hooks_feedback_injection.py` | 3P | 3P | 取 main |
| `integration/test_legacy_routes_step_persistence.py` | 4P | 4P | 取 main |
| `unit/test_browser_temp_lifecycle.py` | 11P | 11P | 取 main |
| `unit/test_event_projection.py` | 12P | 12P | 取 main |
| `unit/test_llm_json.py` | 8P | 8P | 取 main |
| `unit/test_replan_tool.py` | 31P | 31P | 取 main |
| `unit/test_hooks_feedback.py` | **14P** | 0P/14S | 保 win7 |
| `unit/test_hooks_lifecycle.py` | **18P** | 0P/18S | 保 win7 |
| `unit/test_mcp_oauth.py` | **56P** | 46P | 保 win7 |
| `unit/test_py38_compat_gate.py` | **19P** | 5P | 保 win7 |
| `unit/test_remote_mcp_server.py` | **27P** | 24P | 保 win7 |
| `unit/tools/test_python_adapter.py` | **14P** | 10P | 保 win7 |

7 个取 main 的文件 test id 集合与 main 完全一致（无遗漏）。

## 一个真 bug：win7 的权限断言在 Windows 上必失败

`test_mcp_oauth_store.py::TestTokenStore::test_roundtrip` 在 win7 上：

```
AssertionError: assert (33206 & 511) == 384
  backend/tests/unit/test_mcp_oauth_store.py:36
```

`33206` = `0o100666`，`& 0o777` 得 `0o666` = 438，而断言期望 `384` = `0o600`。
win7 的用例要求 token 文件权限是 `0600`，但 **Windows 上 `stat` 恒返回 `0666`**
（没有 POSIX 权限位概念）。

这不是「main 更好」的风格差异，而是 win7 分支上一条**恒红的测试**。main 侧的写法
在 Windows 上不会误判，取过来即是修复。

这条也再次印证：`release/win7` 是 Windows 交付分支，凡涉及 `stat().st_mode`、
symlink、路径分隔符的断言，都必须按 Windows 实际行为来写。

## 保 win7 的 6 个：共同点是「main 把用例关了」

| 文件 | 差异形态 |
|---|---|
| `test_hooks_feedback.py` | main 14 个全 skip（模块级 skipif） |
| `test_hooks_lifecycle.py` | main 18 个全 skip |
| `test_mcp_oauth.py` | main 少 10 个用例 |
| `test_py38_compat_gate.py` | main 只有 5 个（win7 19 个，含 14 条闸门规则回归） |
| `test_remote_mcp_server.py` | main 少 3 个 |
| `test_python_adapter.py` | main 少 4 个 |

`test_py38_compat_gate.py` 尤其不能取 main —— 它测的是 py38 兼容闸门本身的规则，
win7 的 19 条用例里包含了本分支新增的 pydantic v1 字段规则回归；取 main 会让闸门
自身的回归保护从 19 条掉到 5 条。

## 验证

```
py3.11   7 文件分组    34 + 54 = 88 passed
py3.8    7 文件分组    34 + 54 = 88 passed
py3.8 闸门             Scanned 1890 files; 0 with violations
ruff 7 文件            All checks passed
```

本批闸门一次通过（0 违规），没有出现前两批的括号 `with` 问题。

## 收敛进度

| 项 | 本批前 | 本批后 |
|---|---|---|
| actionable | 42 | 35 |
| 已实测并定论 | — | 13 / 38 |
| 剩余待实测 | 38 | 25 |

剩余 25 个中，多数在更早批次已判「保 win7」（浏览器/凭据/内存/安全类），
但尚未逐个复测。下一步按同样方法补齐。
