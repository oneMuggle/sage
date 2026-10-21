# 修复 `py38_compat_rewrite.py --fail-on-drift` 空转

- 日期：2026-10-21
- 分支：`fix/win7-py38-drift-gate-20261021` → `release/win7`
- 影响：`scripts/py38_compat_rewrite.py`、新增 `backend/tests/unit/test_py38_rewrite_drift_gate.py`

## 1. 问题

`--fail-on-drift` 的语义写在 help 里：「exit with code 1 when `--check` finds files that would be rewritten」。
但实测：

```
$ python scripts/py38_compat_rewrite.py --check --fail-on-drift drift.py
would rewrite: drift.py
Summary: 1 changed, 0 unchanged
EXIT=0                      # ← 应该是 1
```

根因在 `main()` 结尾：

```python
    print(f"\nSummary: {changed} changed, {unchanged} unchanged")
    return 0                # ← 无条件
```

`args.fail_on_drift` 被 `argparse` 收下了，之后**从未被读取**。

## 2. 影响面

好消息是当前没有 CI 真的踩到它：`scripts/win7/auto_sync.py` 调用重写脚本时是原地重写
（`py("scripts/py38_compat_rewrite.py", *PY38_TARGETS)`），没有传 `--check/--fail-on-drift`，
所以修掉不会改变夜间同步的现有行为。

坏消息是它是个**哑雷**：文档
（`docs/mcp-sage-ui-feature-logic-roadmap-20261008.md` §247）明确写着
「同时为 `scripts/py38_compat_rewrite.py` 增加 `--fail-on-drift` 退出码支持」，
README 也把它列在 py38 门禁里。任何人按文档接入 CI，得到的都是一道永远绿的闸门。
P2 的 B1 试点就是照文档用了它，才发现这个问题。

现有测试 `backend/tests/unit/test_py38_compat_gate.py` 只覆盖 `check_py38_compat.py`，
没有任何一条测这个 flag —— 这是它能潜伏这么久的原因，所以本次一并补上。

## 3. 改动

```python
    print(f"\nSummary: {changed} changed, {unchanged} unchanged")
    if args.check and args.fail_on_drift and changed:
        print(f"::error::py38 注解漂移：{changed} 个文件需要 py38_compat_rewrite 重写")
        return 1
    return 0
```

语义严格按 help 文本：只在 `--check` + `--fail-on-drift` + 有漂移三者同时成立时返回 1。
不带 `--check` 时是原地重写模式，不存在「漂移」这个概念，保持 0。

新增 `backend/tests/unit/test_py38_rewrite_drift_gate.py`，三条契约：

| 用例 | 期望 |
|---|---|
| 有漂移 + `--check --fail-on-drift` | exit 1，且 stdout 含 `would rewrite` |
| 有漂移 + 仅 `--check` | exit 0（保持原行为，只是报告） |
| 无漂移 + 两个 flag | exit 0 |

测试用 `pytest.importorskip("libcst")` + `sys.version_info >= (3, 10)` 跳过，
所以 win7 的 Python 3.8 CI 上不会因为脚本自身语法而误挂。

## 4. 验证

修前/修后的负向→正向次序：

1. 负向：`drift.py` + `--check --fail-on-drift` → 修前 `EXIT=0`（错误），修后 `EXIT=1`
2. 正向：`clean.py` + `--check --fail-on-drift` → 修前后均 `EXIT=0`
3. 正向：`drift.py` + 仅 `--check` → 修前后均 `EXIT=0`
4. 新增测试文件三条用例全绿

## 5. 风险

| 风险 | 评价 |
|---|---|
| 影响夜间同步 | 无：`auto_sync.py` 不传该 flag |
| Python 3.8 CI 误挂 | 已用 skipif + importorskip 规避 |
| 误报漂移 | `changed` 只统计确实会被重写的文件；重写是幂等的，跑过一次后即为 0 |
