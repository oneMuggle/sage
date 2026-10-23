# B2：backend/api 对齐到 main（含两个最小切片）

- 日期：2026-10-21
- 分支：`chore/win7-align-b2-20261021` → `release/win7`
- 属于 main ↔ win7 对齐方案（`docs/mcp-win7-main-alignment-plan.md`）的 P2 第二批

## 1. 范围

parity 口径下 `backend/api` 有 23 个需动作文件。实测后 **21 个文件**入批，其中
2 个是跨域最小切片：

| 类别 | 件数 | 说明 |
|---|---|---|
| `backend/api/*` 取 main 版本 | 19 | 原 23 个减去下面排除的 4 个 |
| `backend/office/read_cache.py` | 1 | 切片：被 `office_routes.py` / `office_lifecycle_routes.py` import，win7 无此模块 |
| `backend/services/attachment_rag.py` | 1 | 切片：被 `chat_attachment_routes.py` import，win7 无此模块 |

## 2. 排除的 4 个文件及原因

| 文件 | 原因 |
|---|---|
| `backend/api/chat_session_lifecycle.py` | main 把 `_compact_in_progress` 挪进了 `legacy_routes.py`（**intentional** 文件）；win7 方向相反。单搬会打断 import 链，实测炸出 43 个测试模块收集失败 |
| `backend/api/mcp_routes.py` | 依赖 `backend.mcp.oauth_store`（整个 MCP OAuth 子系统 win7 没有）。是否给 win7 上 MCP OAuth 属产品决策，见方案 P3 第 1 条 |
| `backend/api/legacy_memory_routes.py` | main **删掉了** `by-turn` / `summary` 等接口，win7 有 |
| `backend/api/legacy_memory_list_routes.py` | main 删掉了 `memory_events`（SSE），win7 有 |

后两个是**反向问题**：不是 win7 落后，而是 main 把功能拿掉了。
win7 的 `test_memory_endpoints.py` / `test_memory_sse.py` 在 main 上根本不存在，
照搬 main 会让 win7 失去这两个能力（实测 6 个用例从 pass 变 fail）。
LTS 分支不应因此丢功能，故保留 win7 版本。

## 3. 切片为什么是安全的

| 切片 | 行数 | 依赖 |
|---|---:|---|
| `backend/office/read_cache.py` | 101 | 仅 `logging/threading/OrderedDict/pathlib/typing/pydantic` |
| `backend/services/attachment_rag.py` | 160 | `backend.wiki.embeddings` / `backend.wiki.vectorstore`（win7 都有） |

拿掉这两个切片后，`pytest --collect-only` 立即出现
`No module named 'backend.services.attachment_rag'` 与
`cannot import name 'read_cache' from 'backend.office'`，
即它们是硬依赖，不是可选增强。

## 4. 验证

| 闸门 | 结果 |
|---|---|
| `pytest --collect-only tests/api tests/integration` | **0 errors**，1387 个用例可收集 |
| `pytest tests/api`（py3.8） | **256 passed** |
| `check_py38_compat.py` | 0 violations |
| `ruff check` | All checks passed |

`ruff check --fix` 期间对 7 个文件自动修了 I001/F811（py38 重写插入 typing import 的老副作用，
`docs/technical/31-win7-lts.md` 已记录过）。

## 5. 全量测试的失败分类（重要）

跑 `tests/api + tests/integration` 得到 39 个失败。逐个在**干净 win7（`9cac234a5`）**
上复跑同文件做基线对照：

| 失败文件 | B2 上 | 干净 win7 | 判定 |
|---|---:|---:|---|
| `test_doctor_cli.py` | 14 | 失败 | **既有**（Windows GBK 控制台解码） |
| `test_ingest_stream.py` | 11 | 12 失败 | **既有** |
| `test_llm_proxy_routes.py` | 3 | 3 失败 | **既有** |
| `test_agent_office_create_flow.py` | 2 | 2 失败 | **既有** |
| `test_memory_endpoints.py` + `test_memory_sse.py` | 6 | 13 passed | **本批引入** → 已按 §2 处理，处理后再跑 13 passed |

结论：B2 本身不引入新失败。

## 6. 经验

1. **用 `--collect-only` 当依赖探测器**：几十秒拿到整批 import 断链清单，
   比人工读 import 准得多。
2. **失败必须跑基线对照**：这批 39 个红里有 30 个是 win7 既有的（GBK 编码、流式快照），
   不对照就会把既有问题算到自己头上，或者反过来放过真问题。
3. **批次顺序由依赖方向决定**：B2 之所以要切片，是因为它 import 了 office 域的新模块。
   完整做 B3 当然也行，但 261 行的两个切片就能解锁 21 个文件，性价比更高。
