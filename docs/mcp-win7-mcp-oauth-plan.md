# win7 移植 MCP OAuth 授权流 —— 可行性勘察与批次规划

- 日期：2026-10-22
- 决策前提：用户确认 **win7 LTS 需要 MCP OAuth**
- 状态：勘察完成，待实施
- 关联：B4（`backend/tests` 233 件）中有 2 个测试文件依赖本特性

## 1. 现状：win7 完全缺失这条特性线

不是"缺一个文件"，而是整条线不存在：

```
win7 的 backend/mcp/：
  __init__.py  client.py  config.py  discovery.py  http_client.py
  pool.py  servers/  tool.py  workspace_scope.py

缺失：oauth.py  oauth_loopback.py  oauth_store.py
```

`backend/mcp/http_client.py` 里 `401|oauth|Unauthorized` 的匹配数是 **0** ——
win7 的 MCP HTTP 客户端完全没有 OAuth 处理。

main 侧这条线由 **10 个提交**构成：

| 切片 | 提交 | 内容 |
|---|---|---|
| r60 | `379ae3f32` | PKCE / 发现 / 解析**纯函数库** `oauth.py` |
| r61 | `55e787c0f` | token 存储 `oauth_store.py` + 过期刷新 + `http_client` 注入 |
| r62 | `58df53ebb` `6f4a169dc` | 授权编排层（发现→注册→授权→交换） |
| r63 | `a513d0a88` | loopback 回听 + 浏览器拉起 `oauth_loopback.py` |
| r64 | `30a800936` | 授权 API 路由 + IPC + McpTab 授权按钮 |
| r65 | `fffdef441` | 状态可见化 `has_oauth_token` + 授权角标 |
| r70 | `37a7bd89a` | 401 自愈——失效 token 清理 + 错误面点名重授权 |
| r102 | `6e2718c06` | `HttpClientMcpClient` OAuth 注入/刷新/自愈测试 |
| r153 | `aee452c5a` | loopback 回调服务单测补齐 |

## 2. 可行性：三项硬指标全部通过

### 2.1 py38 语法兼容 ✅

三个新模块 + 三个接线文件，用 `sage-backend-py38` 环境 `py_compile` **全部通过**：

```
backend/mcp/oauth.py            OK
backend/mcp/oauth_loopback.py   OK
backend/mcp/oauth_store.py      OK
backend/api/mcp_routes.py       OK
backend/mcp/http_client.py      OK
backend/mcp/config.py           OK
```

危险构造扫描（`match` / `:=` / `X | None` / `list[...]` / `functools.cache` /
`removeprefix` / `zoneinfo` / `graphlib`）**零命中**。

### 2.2 零新增依赖 ✅

三个模块只用标准库：

```
oauth.py          base64 hashlib secrets time typing urllib.parse
oauth_loopback.py threading http.server typing
oauth_store.py    json logging os threading dataclasses pathlib typing
```

接线所需的 `httpx==0.26.0` **win7 的 `requirements-py38.txt` 里已经 pin 了**。
`backend/environment.yml` / `requirements.txt` 无需改动。

> 这一条很关键：win7 LTS 的依赖是钉死的，任何新依赖都要走高风险确认。
> OAuth 这条线不需要。

### 2.3 规模可控 ✅

| 部分 | 行数 |
|---|---:|
| `oauth.py` | 478 |
| `oauth_store.py` | 155 |
| `oauth_loopback.py` | 135 |
| **新增小计** | **768** |
| 测试（5 个文件） | ~1200 |

## 3. 接线面：只有 3 个文件，但差异很大

| 文件 | win7 行数 | main 行数 | parity 分级 |
|---|---:|---:|---|
| `backend/api/mcp_routes.py` | 210 | 322 | `real` |
| `backend/mcp/http_client.py` | — | — | `real` |
| `src/pages/settings/McpTab.tsx` | 459 | 649 | `real` |

`McpTab.tsx` 的 win7↔main 差异达 **1944 行**（含行尾），说明它不只缺 OAuth，
还缺 main 的其他演进。**不能只嫁接 OAuth 部分**——需要判断是整体对齐还是外科式嫁接，
判据同 harness：先看 win7 侧有没有 main 缺失的独有修复。

r64/r65 还牵动：

- `electron/commands.ts` + `electron/__tests__/commands.test.ts`（IPC 命令）
- `src/shared/api/mcpClient.ts`
- `src/shared/lib/i18n/{zh,en}.ts`
- `backend/mcp/config.py`、`backend/data/database.py`

## 4. 批次规划

**不能一次做完**（跨后端/前端/electron/i18n，且 `McpTab.tsx` 差异需单独判断）。
按 main 的切片顺序拆 4 批，每批独立可验证：

### O1 —— 纯函数库 + 存储（后端，无接线）

```
backend/mcp/oauth.py            (r60 + r62 最终态)
backend/mcp/oauth_store.py      (r61 + r64 + r65 最终态)
backend/tests/unit/test_mcp_oauth.py
backend/tests/unit/test_mcp_oauth_store.py
```

- 零接线 → 不可能破坏现有行为
- 验证：py38 `py_compile`、`check_py38_compat.py`、`ruff`、两个测试文件全绿
- **取 main 的最终态而非逐提交 cherry-pick**（10 个提交里有多次自我修正，
  逐个 pick 会重复踩 main 已经修过的坑）

### O2 —— http_client 注入 + 401 自愈

```
backend/mcp/http_client.py      (r61 + r70 最终态)
backend/tests/unit/mcp/test_http_client_oauth.py   (r102)
backend/tests/unit/mcp/__init__.py
```

- 风险点：`http_client.py` 是 `real` 分级，win7 侧可能有独有改动 → **先做差异归因**
- 验证：新增测试 + 既有 `backend/tests/unit/mcp/*` 不回归

### O3 —— loopback + 授权编排

```
backend/mcp/oauth_loopback.py   (r63)
backend/tests/unit/mcp/test_oauth_loopback.py      (r153)
backend/tests/unit/test_mcp_oauth_loopback.py
backend/mcp/config.py
```

- 风险点：`http.server` + `threading` 在 Win7 上的端口占用/防火墙行为
  → **需要真机确认**，属高风险项，实施前要问
- 这是 B4 那 2 个测试文件解锁的点

### O4 —— API 路由 + IPC + UI

```
backend/api/mcp_routes.py       (r64 + r65)
backend/tests/unit/test_mcp_authorize_route.py
backend/tests/api/test_mcp_routes.py
electron/commands.ts + __tests__/commands.test.ts
src/shared/api/mcpClient.ts
src/shared/lib/i18n/{zh,en}.ts
src/pages/settings/McpTab.tsx + __tests__/McpTab.test.tsx
```

- 最大的一批，且 `McpTab.tsx` 需先做「整体对齐 vs 外科嫁接」判断
- 依赖 B5 已完成（`src/shared/api/mcpClient.ts` 已对齐）
- 与 B6（`electron/*`）有重叠 → 可能需要调整批次顺序

## 5. 与既有批次的关系

| 批次 | 关系 |
|---|---|
| **B4**（`backend/tests` 233 件） | 有 2 个测试依赖 O3。可选：B4 先排除这 2 个，O3 完成后补 |
| **B6**（`electron/*` 50 件） | O4 改 `electron/commands.ts`，与 B6 重叠 |
| **B2**（api，已完成 `a8c6c59f2`） | `mcp_routes.py` 当时是否已对齐需复核 |
| **harness**（#2275） | 无重叠 |

## 6. 待确认的高风险项

1. **loopback 回听需要本机端口 + 拉起浏览器**（O3）。
   Win7 上防火墙弹窗、端口占用、默认浏览器拉起行为都需要真机验证。
   按仓库规则这属于「需要 host-local 人工确认」的操作 → **实施 O3 前要先问**。

2. **`McpTab.tsx` 差异 1944 行**（O4）。
   需先判断 win7 侧是否有 main 缺失的独有修复（判据：数特征标记，
   同 harness 的 `alpha.36 (Bug` 手法），再决定整体对齐还是外科嫁接。

3. **token 落盘位置与加密**（O1）。
   `oauth_store.py` 用 `pathlib` + `json` 明文存 token。
   win7 LTS 的安全基线是否接受明文落盘需确认——main  accepted，
   但 win7 可能有更严的要求。

## 7. 建议顺序

O1 → O2 → （B4，排除 2 个 oauth 测试）→ O3 → O4 →（B6）

理由：O1/O2 是纯后端、零 UI 风险，能最快解锁 B4 的大部分；
O3 需要真机确认，放在 B4 之后可以避免阻塞；O4 最大且与 B6 重叠，最后做。
