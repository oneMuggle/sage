# Win7 对齐：backend/tests `both-changed` 收敛

- 日期：2026-10-27
- 基线：`release/win7` = `92a526e4e`；`main` = `9940dc33d`（两轮验证期间未变）；merge-base = `476904b40`
- 范围：`backend/tests` 下 41 个历史 `both-changed` 路径

## 为什么需要方法而不是直接覆盖

`both-changed` 的旧账（"16 个待人工"）是过期结论：期间 `main` 前进，实际分歧扩到 34 个。
更关键的是，**这些分歧大部分不是"谁对谁错"，而是同一条 py3.8 兼容修复被两侧独立做成了不同措辞**：

| win7（py3.8 目标） | main（py3.10+ 目标） | 关系 |
|---|---|---|
| `from datetime import datetime, timezone` + `timezone.utc` | 同 | 语义相同，仅注释不同 |
| `Optional[str]` | `str \| None` | 语义相同，写法必须不同 |
| 嵌套 `with` / `contextlib.ExitStack` | 括号多上下文 `with (a, b):` | 后者是 Py3.9+ 语法 |
| `os.link(src, dst)` | `dst.hardlink_to(src)` | 后者是 3.10+ 方法 |
| `is_within(parent, child)` 助手 | `os.path.commonpath(...)` | 语义相同 |

因此"对齐"的正确判据不是文本相同，而是：**main 的版本放到 win7 源码上能不能过**。

## 四层筛法

1. **三路状态重算**（当前 tip，非旧基线）
   41 个路径：`converged` 7、`win7-ahead-keep` 0、`safe-take-main` 0、`win7-deleted` 0、**仍 `both-changed` 34**。

2. **3 路合并分拣**（merge-base 为 base，main/win7 为两侧）
   `win7-superset` 10（把 main 的改动并入 win7 后结果逐字节等于 win7 ⇒ main 无增量）、`conflict` 24。

3. **AST / 函数级比对**
   24 个冲突里 3 个仅注释差异；31 个 AST 有别。其中 **只有 3 个文件** win7 缺函数
   （`test_browser_tool` +2、`test_credential_vault` +6、`test_web_tool` +2），其余 28 个 win7 是函数级超集。

4. **决定性实验**（20 个文件逐个、两轮，win7 版 vs main 版）
   - 第一轮 py3.11：win7 版 **全部通过**；main 版 10 个文件出现失败。
   - 第二轮 py3.8（真实解释器，`sage-backend-py38`）：对"通过数相同"的 11 个候选再验一次，
     **全部通过** —— 排除了 `str | None` 这类在 3.8 上会 `TypeError` 的写法。

## 结论

### A. 整取 main（本 PR）

通过数在 py3.11 与 py3.8 双解释器下均与 win7 版一致，且函数集合完全相同（无 win7 独有函数）：

```
backend/tests/api/test_permission_routes.py            45 = 45
backend/tests/api/test_runtime_routes.py                7 =  7
backend/tests/integration/test_chat_stream_persist.py   5 =  5
backend/tests/unit/office/test_generators.py           14 = 14
backend/tests/unit/office/test_pdf.py                  15 = 15
backend/tests/unit/test_chat_dispatcher.py             43 = 43
backend/tests/unit/test_memory_storage_adapter.py      21 = 21
backend/tests/unit/test_skill_md_loader.py             42p+7s = 42p+7s
backend/tests/unit/test_wiki_path_security.py           7p+5s =  7p+5s
```

取法为 **blob 级替换**（直接用 main 的 blob sha 建树），零文本改写，因此不存在 EOL 漂移。
`unit/test_wiki_path_security.py` 顺带修掉了 win7 侧 `hardlink_to` + `AttributeError` 的静默降级，
改为 main 的 `os.link`（全版本可用、不吞异常）。

### B. 明确不取（有失败证据）

main 版在 win7 源码上失败，win7 版必须保留：

| 文件 | main 版结果 | 原因 |
|---|---|---|
| `contract/test_settings_schema_parity.py` | 1 failed | win7 的 `LEGAL_ORCH_KEYS` 比 main 多 5 个键 |
| `unit/test_browser_tool.py` | 2 failed | 2 个新用例依赖 win7 未实现的接口 |
| `unit/test_credential_vault.py` | 17 failed | `_MemRepo` 预置 `network_policy=online` 是 win7 适配 |
| `unit/test_inproc_tool_adapter.py` | 1 failed | win7 默认注册表 fail-closed（`web_search` 不可用） |
| `unit/test_legacy_routes_async_safety.py` | 2 failed | win7 legacy 路由有 10 个 async handler，main 是 7 个 |
| `unit/test_memory_adapter.py` | 1 failed | metadata 需透传 traceability 三字段 |
| `unit/test_shell_resolver.py` | 1 failed | win7 内置 bash 路径为 `resources\tools\git-bash\usr\bin\bash.exe` |
| `unit/test_web_cache.py` | 11 failed | 同 `_MemRepo` 网络策略 |
| `unit/test_web_tool.py` | 19 failed | 同网络策略 + 2 个未实现接口 |

### C. 不取，但不是因为失败

- `unit/test_safe_writer.py`、`unit/test_vision_ingest_security.py`：main 版用
  `hardlink_to(...)` + `except (..., AttributeError)`，在 py3.8 下会**静默跳过**测试。
  虽然本地两版本都因文件系统不支持硬链接而 skip，但该写法属于"在 win7 上关掉测试"，
  按既定判据不可取，保留 win7 的 `os.link`。
- `integration/test_evolution_scheduler_runs.py`：win7 有 8 个用例，main 有 6 个（win7 ⊃ main）。

## 后续

- `conftest.py` 未在本次范围内：它是双方都改过的公共夹具，win7 独有 `_online_network_settings`，
  改动面覆盖全套件，需单独评估。
- `test_browser_tool.py` / `test_credential_vault.py` / `test_web_tool.py` 的 10 个新用例需要
  等对应 win7 功能补齐后再移植，不是简单复制。
