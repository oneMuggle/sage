# O1+O2：移植 MCP OAuth 纯函数库、token 存储与 http_client 注入

- 日期：2026-10-22
- 分支：`feat/win7-mcp-oauth-o1-20261022` → `release/win7`
- 基：`697e79210`（= `fix/win7-py38-drift-gate` + B3）
- 规划文档：`docs/mcp-win7-mcp-oauth-plan.md`
- 用户决策：win7 LTS **需要** MCP OAuth；O3（loopback）暂缓；token 明文落盘与 main 一致

## 1. 为什么 O1 和 O2 必须合并

原规划把 OAuth 拆成 O1（纯函数库 + 存储）和 O2（http_client 注入 + 401 自愈）两批。
实测 **O1 单独跑不绿**：

```
backend/tests/unit/test_mcp_oauth_store.py
  TestHttpClientInjection      ×5   ← 测 http_client 的 token 注入（O2 范围）
  TestUnauthorizedSelfHeal     ×2   ← 测 401 自愈（O2 / r70 范围）
7 failed, 58 passed
```

main 的 `test_mcp_oauth_store.py` 一个文件里混了 r61（存储）与 r70（自愈）两个切片的测试，
而 r70 同时改了 `http_client.py`。**测试文件的归属决定了批次边界，不是源码模块的归属。**

合并后 143 passed / 0 failed。

> 这与 B5 的教训同构：前端的最小单元是「类型定义 + 全部消费者」，
> 后端移植的最小单元是「模块 + 它的全部测试文件」。

## 2. 取 main 的最终态，不逐提交 cherry-pick

main 侧这条线有 10 个提交（r60 r61 r62×2 r63 r64 r65 r70 r102 r153），
其中 r62 有两个提交（`58df53ebb` 与 `6f4a169dc` 同名，后者补了 database/dispatcher）。
逐个 pick 会重复踩 main 自己已经修过的坑（r70 就是修 r61 的 fail-open 行为）。

改为 `git checkout origin/main -- <file>` 取**最终态**。

## 3. 本批范围（7 文件）

| 文件 | 来源切片 | 行数 |
|---|---|---:|
| `backend/mcp/oauth.py` | r60 + r62 | 478 |
| `backend/mcp/oauth_store.py` | r61 + r64 + r65 | 155 |
| `backend/mcp/http_client.py` | r61 + r70 | 修改 |
| `backend/tests/unit/test_mcp_oauth.py` | r60 + r62 | 411 |
| `backend/tests/unit/test_mcp_oauth_store.py` | r61 + r70 | 227 |
| `backend/tests/unit/mcp/__init__.py` | r153 | 0 |
| `backend/tests/unit/mcp/test_http_client_oauth.py` | r102 | — |

## 4. 可行性核验（实施前完成）

### 4.1 py38 语法 ✅

三个新模块 + 三个接线文件用 `sage-backend-py38` 环境 `py_compile` 全部通过。
危险构造扫描（`match` / `:=` / `X | None` / `list[...]` / `functools.cache` /
`removeprefix` / `zoneinfo` / `graphlib`）**零命中**。

### 4.2 零新增依赖 ✅

```
oauth.py          base64 hashlib secrets time typing urllib.parse
oauth_loopback.py threading http.server typing
oauth_store.py    json logging os threading dataclasses pathlib typing
```

接线所需 `httpx==0.26.0` **win7 的 `requirements-py38.txt` 里已 pin**。
`environment.yml` / `requirements.txt` 无需改动 —— 这对钉死依赖的 win7 LTS 很关键。

### 4.3 `http_client.py` 无 win7 独有修复 ✅

用 harness 那套判据核查：

- win7 侧 `alpha.36` 标记数 **0**（main 也是 0）
- win7 比 main 多的只有 1 行 `Python 3.8` 字样 —— 查明是文件头的
  `# ruff: noqa: UP006, UP007, UP035, UP045`，**main 版同样有这一行**
- `git diff` 里 win7 侧被删的 2 行是旧构造函数签名
  `def __init__(self, config, http_client=None)`，main 版是它的扩展
  （多一个 `oauth_store` 参数）

→ 可以安全整体对齐 main 版，无需外科嫁接。

## 5. 基底修正：必须先有 drift-gate 修复

第一次建分支基于 `chore/win7-align-b3-20261021`，py38 闸门报：

```
backend\office\path_safety.py:67: py38 runtime: Path.is_relative_to is Py3.9+
Scanned 1612 files; 1 with violations
```

归因：**B3 的既存误报，不是本批引入**。

- 干净 win7（`003a2053b`）：1606 files / **0 violations**
- B3（`443f5868e`）：1608 files / **1 violation**
- `fix/win7-py38-drift-gate-20261021`（`83db67245`）：1608 files / **0 violations**

第 67 行的 `Path.is_relative_to()` **只出现在 docstring 里**，实际代码用的是
`candidate.relative_to(base)`（py38 安全）。这正是 drift-gate 分支修掉的
docstring 假阳性。

→ 已 `rebase fix/win7-py38-drift-gate-20261021`，新基底 `697e79210`。
**这再次确认 drift-gate 是所有 backend 批次的前置依赖。**

## 6. 验证

| 闸门 | 结果 |
|---|---|
| py38 `py_compile`（6 文件） | OK |
| `pytest test_mcp_oauth + test_mcp_oauth_store + tests/unit/mcp/` | **143 passed / 9 skipped** |
| `pytest backend/tests -k mcp`（全量 mcp） | **233 passed / 16 skipped** |
| `pytest backend/tests --collect-only` | **11494 collected**（B3 是 10932，+562），无收集错误 |
| `ruff check backend/mcp/ + 4 个测试文件` | All checks passed |
| `scripts/check_py38_compat.py` | 1616 files / **0 violations** |

9 + 16 个 skip 是既有的 POSIX symlink / no-follow 用例（Windows 上跳过），非本批引入。

## 7. 未纳入（按用户决策）

**O3（loopback 回听 + 浏览器拉起）暂缓** —— 需要本机开端口，Win7 上会触发
防火墙弹窗，属 host-local 人工确认项。因此：

- `backend/mcp/oauth_loopback.py` 未移植
- `backend/tests/unit/mcp/test_oauth_loopback.py`（r153）未移植
- `backend/tests/unit/test_mcp_oauth_loopback.py` 未移植
- B4 批次中依赖 `oauth_loopback` 的 **2 个测试文件需暂时排除**

O3 完成后这 3 个文件补齐，B4 的排除项即可解除。

## 8. 后续

| 批次 | 内容 | 状态 |
|---|---|---|
| **O1+O2** | 纯函数库 + 存储 + http_client 注入 + 401 自愈 | ✅ 本批 |
| **O3** | loopback 回听 + 浏览器拉起 | ⏸ 待真机确认 |
| **O4** | API 路由 + IPC + `McpTab.tsx` | ⬜ 需先做 McpTab 差异归因（1944 行） |
| **B4** | `backend/tests` 233 件 | ⬜ 排除 2 个 loopback 测试后可开工 |
