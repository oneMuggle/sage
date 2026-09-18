# py39+ 标准库 API py38 兜底（Round 21）

日期：2026-09-17 ｜ 分支：`feat/py39api-compat` ｜ 基线：#1056（30a800936）

## 背景

#972 的审计扫的是**语法**（union/PEP585/括号 with），本批扫的是**标准库 API**
的 py39+ 使用——py38 下语法合法但运行期 AttributeError/TypeError。触发点：
py38 全量重测（审计后）把运行期失败从 131 收敛到 6，归因出三类根因：

| 根因 | API | 影响面 |
|---|---|---|
| `asyncio.to_thread` | 3.9+ | 7 文件 27 处（storage adapters / legacy_routes / inproc_adapter / database / agent_repo） |
| `Path.hardlink_to` | 3.10+ | 3 个测试 helper |
| `Path.write_text(newline=)` | 3.10+ | test_wiki_insights |

## 改动

1. 新增 `backend/utils/py_compat.py::to_thread`：3.9+ 直通 `asyncio.to_thread`；
   3.8 退化为 `loop.run_in_executor`（默认线程池；与 to_thread 同样不取消已入池任务，语义等价）。
   7 文件 27 处调用点机械替换 + import（legacy_routes 的括号 import 块手工修复插入位）。
2. `test_wiki_path_security._make_hardlink_or_skip`：`Path.hardlink_to` → `os.link`
   （全版本可用；硬链接用例在 py38 真实执行而非 AttributeError）。
3. `test_wiki_insights._write_page`：`Path.write_text(newline=)` → `open()`（同 #953 win7 侧修法）。

## 验证

- py38（3.8.20）：受影响 5 个测试文件 34 passed（此前 3 failed）；
  unit 全量收集 0 错误；mcp/cli/chat 323 passed
- modern：同批文件 34 + 323 passed
- ruff（改动文件）干净

## 范围外

`backend/data/` 下 8 个 SIM105/SIM118/UP038/PLR1714 为本地新版 ruff 报的存量债
（CI 钉 ruff 0.4.4 不报），不属本批。
