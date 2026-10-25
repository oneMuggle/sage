# T1：py38 运行期地雷 AST 扫描进 CI（win7 LTS 门禁补强）

日期：2026-09-24
分支：feat/py38-hazard-scan-ci
状态：实施完成，待 PR

## 背景与动机

本轮循环（#1483）发现：`test_settings_keys_guard.py` 的
`isinstance(node, ast.Assign | ast.AnnAssign)`（3.10+ 运行期写法）在 main
上长期潜伏。现有 py38 collect 门禁只能拦两类问题：

1. py39+ **语法**——`ast.parse` 在 3.8 解释器下直接 SyntaxError；
2. 被 `import backend.main` / `pytest --collect-only` **导入链覆盖**的模块里的
   导入期错误（如 `from typing import Annotated`）。

函数体内的**运行期 API/写法**（isinstance 联合、asyncio.to_thread、
zip strict=、Path.hardlink_to 等）import 时毫发无损，collect 门禁全部放行。
本轮同批还发现三处该类地雷（见下）。

## 内容

### 1. 新增 `backend/tools/py38_hazard_scan.py`

AST 静态扫描，stdlib-only，脚本自身 py38 可运行（在 py38 job 里执行）。规则：

| 规则 | 地雷 | 最低版本 |
|---|---|---|
| R1 | `isinstance(x, A \| B)` | 3.10 |
| R2 | `asyncio.to_thread`（py_compat.py 垫片自身豁免） | 3.9 |
| R3 | `zip(..., strict=)` | 3.10 |
| R4 | `write_text/read_text/write_bytes/readlink(newline=)` | 3.10 |
| R5 | `Path.hardlink_to` | 3.10 |
| R6 | py38 解释器 `ast.parse` 失败（py39+ 语法兜底） | — |

- 行内 `# py38-ok <原因>` 单行豁免；`FILE_EXEMPTS` 整文件豁免。

### 2. 接线 CI

`.github/workflows/ci.yml` 的 `Backend collect (Python 3.8, win7 mine-sweeper)`
job，在 import smoke 之后、collect-only 之前加一步
`py38 runtime hazard AST scan`。

### 3. 本轮新发现并顺带修复的 3 处地雷

- `backend/tests/integration/test_chat_stream_persist.py:127`——**括号化
  with（3.9+ 语法）**，py38 直接 SyntaxError；改为单行 with。collect 门禁
  之所以漏掉：integration/ 目录不在 collect-only 范围。
- `backend/tests/unit/test_safe_writer.py:30` 与
  `backend/tests/unit/test_vision_ingest_security.py:132`——`Path.hardlink_to`
  （3.10+ 方法），原有 try/except 只捕 `OSError/NotImplementedError`，py38 下
  抛的是 `AttributeError`（方法不存在）不会 skip 反而 ERROR；补入
  AttributeError 并加 `# py38-ok` 行豁免。

## 验证

- 扫描器在 py38 环境运行：`py38 运行期地雷扫描：0（backend）`
- ruff check：改动 4 文件 All checks passed
- 修复文件双环境单测：py38 与 py3.11 均 `4 passed, 9 skipped`；
  `test_chat_stream_persist.py` `5 passed`
- 扫描器阴性/阳性自检：对含 isinstance 联合的历史版本扫描能准确报出行号

## 后续（backlog）

- T2：Architecture check 失败时自动评论精确的基线补账 JSON 行
  （本轮 #1488/#1489 连续两次带红 merge，补账遗忘是系统性问题）
- T3：husky hooks 在无 node_modules 的 worktree 中降级为 no-op
