# Win7 第四批：no-base 残余逐文件归因

- 日期：2026-10-27
- 基线：`release/win7` @ `76f8091f4`
- 对照：`main` @ `df23587ee`
- 范围：前几批遗留的「no-base」文件中带**模块级差异**的 7 个 + **装饰器差异**的 1 个

## 方法

每个文件都是双版本实测，而不是看 diff 猜：

1. 跑 win7 版（pytest，py3.11）；
2. 写入 main 版，再跑一次；
3. `git checkout --` 还原；
4. 再用 `--collect-only` 比对两边的 **test id 集合** —— 通过数相同不等于用例相同，
   必须确认 main 没有悄悄少掉 win7 的用例。

## 结果

| 文件 | win7 版 | main 版 | test id 集合 | 结论 |
|---|---|---|---|---|
| `api/test_permission_session_remember.py` | 6P | 6P | 6 = 6，无差异 | **取 main** |
| `unit/test_agent_step_done.py` | 7P | 7P | 7 = 7，无差异 | **取 main** |
| `unit/test_chat_request_cmid.py` | 8P | 8P | 8 = 8，无差异 | **取 main** |
| `unit/test_project_metadata_context.py` | 15P | 15P | 15 = 15，无差异 | **取 main** |
| `unit/test_schema_migrations.py` | 7P | 7P | 7 = 7，无差异 | **取 main** |
| `unit/test_todo_service.py` | 40P | 40P | 40 = 40，无差异 | **取 main** |
| `unit/test_hooks_builtin.py` | **61P** | **0P / 61 skipped** | 61 = 61 | **保 win7** |
| `unit/tools/test_runtime_tool_contract.py` | **7P** | **6P / 1 skipped** | 7 = 7 | **保 win7** |

### 取 main 的 6 个

两边在 py3.11 与 py3.8 下全绿、test id 完全一致，差异只是写法（`Optional[List[X]]`
↔ `X | None`、docstring 措辞、辅助函数的参数形式）。取 main 收敛，减少后续 triage 噪声。

> 曾怀疑这 6 个的差异是「py3.8 兼容改写，取 main 会打挂 py3.8」。实测推翻了这个假设：
> 把 `test_agent_step_done.py` 换成 main 版，py3.8 下仍是 **7 passed** ——
> main 版带 `from __future__ import annotations`，`X | None` 不会在 def 时求值。
> 另两个不带 future 导入的文件（`test_chat_request_cmid`、`test_todo_service`）
> 差异本身不含新语法。**结论以实测为准，不以 diff 观感为准。**

### 保 win7 的 2 个

- `test_hooks_builtin.py`：main 版在 Windows 上 **61 个全部 skip**（模块级 skipif），
  win7 版 61 个全过。取 main 等于把这 61 个覆盖整个关掉。
- `test_runtime_tool_contract.py`：main 版把
  `test_doctor_runtime_env_does_not_false_alarm` 标成了 skip，win7 版 7 个全过。
  该用例正是早年 windows 落地问题的回归保护，不能关。

## 结论

8 个文件里 **6 个取 main、2 个保 win7**。改动仅限测试文件，不触碰产品代码。

## 验证

```
py3.11  6 文件合并   83 passed
py3.8   21 + 62      83 passed
py3.8 兼容闸门       Scanned 1855 files; 0 with violations
ruff check 6 文件     All checks passed
```
