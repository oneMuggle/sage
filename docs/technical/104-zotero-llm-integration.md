# Zotero → LLM 集成（可见性、索引、wiki 沉淀与图谱）

> 2026-10-27 `feat/zotero-llm-visible` 交付。解决「Zotero 已连接但 LLM 不可见」的四层阻断，
> 并补齐语义检索、wiki 沉淀与最小知识图谱。

---

## 1. 背景：四层阻断

设置页能读到 Zotero 本地库，但聊天里的 LLM 既看不到工具、也检索不到文献。
根因是四层叠加，缺一层都仍然"不可见"：

| 层 | 阻断点 | 症状 | 修复 |
| --- | --- | --- | --- |
| ① 工具白名单 | `backend/agents/profiles.py` 的 primary 种子只认内置精确名与插件通配，`mcp__*` 被过滤 | 工具注册表里没有 `mcp__zotero__*` | 种子加 `mcp__*`（`profiles.py`）；执行期仍走 PermissionEngine 风险分级 |
| ② 路径分裂 | REST 读 settings 里的 `zotero_db_path`，MCP 子进程只认 `ZOTERO_DB_PATH` 环境变量 | 设置页连得上，MCP 工具读不到同一个库 | 新增 `backend/zotero/paths.py:resolve_zotero_db_path()` 单一来源：settings → env → 空 |
| ③ 无提示 | prompt 没有任何一处提及文献库 | LLM 不知道有库可查 | 新增 `backend/core/zotero_prompt.py`：注册表出现任意 `mcp__zotero__*` 时注入 system prompt（legacy 编排 + ChatService 两处） |
| ④ 无索引 | 只能 SQL LIKE 检索关键词，没有语义检索 | 问"那篇讲辐射换热的"检索不到 | M2 新增向量索引 + `zotero_search` 语义通路 + SQL LIKE 降级 |

设计原则：①③ 解决"看得见"，②④ 解决"查得到"。任何一层都不得让聊天启动失败——
路径解析、prompt 注入、语义检索全部"永不抛错、逐层降级"。

---

## 2. 架构

```
┌─────────────── 渲染进程 ───────────────┐
│ Settings → Zotero Tab                  │
│   ├─ 只读浏览（status/search/items）    │
│   └─ ZoteroSyncPanel（M5）              │
│        ├─ 立即同步 / 完整重建            │
│        └─ wiki 沉淀标签（preferences）   │
└───────────────┬────────────────────────┘
                │ invoke('zotero_sync' / 'zotero_sync_status' / 'get_preference' …)
┌───────────────▼──────────────────────────┐
│ Electron main（commandRoutes/integrations.ts）│
└───────────────┬──────────────────────────┘
                │ HTTP
┌───────────────▼────────────────────────┐
│ FastAPI                                │
│  api/zotero_routes.py      只读浏览     │
│  api/zotero_sync_routes.py 同步控制     │
│        │                               │
│        ▼                               │
│  zotero/service.py  ── 共用装配 ──┐     │
│        │                          │     │
│        ├─ zotero/ingest.py        │     │
│        │    ZoteroIngestor        │     │
│        │    → rag/zotero.json     │     │
│        └─ zotero/wiki_export.py   │     │
│             → wiki/zotero/*.md    │     │
└───────────────────────────────────┼─────┘
                                    │
┌───────────────────────────────────▼─────┐
│ MCP 子进程（backend/mcp/servers/zotero） │
│  9 个 mcp__zotero__* 工具，复用 service   │
└─────────────────────────────────────────┘
```

REST 与 MCP 跑在不同进程，但**接线只写一份**（`backend/zotero/service.py`）：
数据根目录、向量库路径、客户端构造、embedding 配置解析与调用、ingestor 组装、
语义检索都在这里。历史上两处各写一份，改一处忘另一处就是"工具能调但检索不到"的复发路径。

---

## 3. 索引层（M2）

`backend/zotero/ingest.py` 的 `ZoteroIngestor`：

- **一篇文献一个 chunk**：标题 / 作者 / 年份 / 期刊 / 摘要 / 标签 / 批注拼成文本，
  嵌入后写入独立向量库 `data/rag/zotero.json`（`ZOTERO_PAGE_PREFIX` 前缀区分）。
- **依赖显式注入**（client / storage_path / embed_config / http_post），测试可换 fake，不碰网络。
- **维度不写死**：首次嵌入后从首个向量推断，其后从存储文件读；维度变化 → 清库重建。
- **降级不阻塞**：embedding 未配置 / 调用失败 → 记 error 返回，不抛异常；
  `semantic_search()` 返回 `None` 表示 RAG 不可用，调用方退回 SQL LIKE。

同步水位持久化在 settings `zotero_sync_state`：

```json
{"last_sync_ts": "2026-09-22 10:00:00", "items": 1284, "wiki_pages": 12, "errors": []}
```

`last_sync_ts` 存 Zotero `items.dateModified` 的**原样字符串**（`YYYY-MM-DD HH:MM:SS` UTC），
因为增量过滤靠它与 SQL 列做字典序比较；改写成 ISO 8601 的 `T`/`Z` 分隔符会与库内格式错位，
同一天的条目会被漏掉。对外的 `sync-status.last_sync_at` 才是供人阅读的 ISO 8601。

### 同步触发

| 触发 | 入口 | 语义 |
| --- | --- | --- |
| 启动增量 | 后端启动期 `sync_incremental()` | 静默、失败只记 error，不阻塞启动 |
| 手动增量 | `POST /api/v1/zotero/sync` `{force:false}` | UI「立即同步」 |
| 完整重建 | `POST /api/v1/zotero/sync` `{force:true}` | UI「完整重建」，重新嵌入全部文献 |

- 首次全量不会自动执行（大库耗时/费用不可控），必须用户显式点按钮。
- 进程内 `asyncio.Lock` 防并发：已有同步在跑 → 409；未构建 client（Zotero 不可用）→ 503。
- `project_path` 为空时**只建索引不沉淀 wiki**——设置页没有项目上下文，
  由前端解析"当前打开的项目 → 最近打开的项目"，都没有就返回提示。

---

## 4. MCP 工具（M3）

`backend/mcp/servers/zotero/server.py` 提供 9 个工具：
`zotero_status` / `zotero_search` / `zotero_get_item` / `zotero_get_annotations` /
`zotero_list_collections` / `zotero_get_bibtex` / `zotero_read_pdf` / `zotero_related` / `zotero_sync`。

- `zotero_search` 先走语义检索，`None` 时退回 SQL LIKE；两条通路返回同一摘要结构。
- `zotero_related` 通过作者/标签/collection 找相关文献（最小关联召回，不做引用图谱）。
- PDF 全文**不入**向量库（体积大、噪声高），保留 `zotero_read_pdf` 按需读取。

---

## 5. Wiki 沉淀与图谱（M4）

`backend/zotero/wiki_export.py`：只把**显式标记**的文献渲染成 wiki 页面，
默认 tag `sage:wiki`，可在设置页改（preferences KV `zotero_wiki_tag`）。

```
wiki/zotero/items/{KEY}.md     — type: source
wiki/zotero/authors/{slug}.md  — type: entity（该作者至少有一篇标记文献）
```

图谱由现有 `backend/wiki/graph.py` **零改动**自动推导：

| frontmatter 约定 | 推导出的边 |
| --- | --- |
| 文献页 `related: [[作者显示名]]` → 作者页 `title` 精确匹配 | DirectLink |
| 作者页 `related: [[论文标题]]` → 文献页 `title` 精确匹配 | DirectLink |
| 两页共享 `sources: [zotero:KEY]` | SourceOverlap |
| 所有 `type: source` 文献页之间 | TypeAffinity |

约束：wikilink 文本**必须等于目标页 title**。解析顺序是「label 精确匹配 → id 精确匹配 → slug」，
只有 label 层无歧义。内容未变则不重写文件（幂等，避免 mtime 抖动触发 wiki 重索引）。

---

## 6. 设置页同步 UI（M5）

`src/pages/settings/zotero/ZoteroSyncPanel.tsx`，挂在 Zotero Tab 的路径配置之下：

- 状态行：`已索引 N 篇 · wiki 页面 M 个 · 上次同步 …`（未同步显示「尚未同步」）。
- 按钮：「立即同步」（增量）/「完整重建」（`force=true`，附"首次可能数分钟"提示）。
- embedding 未配置 → 琥珀色引导「请先在 设置 → 模型 配置 embedding 模型」。
- 同步结果：条目数 / 耗时 / wiki 沉淀统计 / 逐条 error；`skipped` 单独文案。
- wiki 标签输入（默认 `sage:wiki`），写入 preferences KV `zotero_wiki_tag`
  （`backend/data/settings_repo.py` 白名单项）。

Electron 侧新增两个通道（`electron/commandRoutes/integrations.ts`）：

| 通道 | 方法 / 路径 |
| --- | --- |
| `zotero_sync` | `POST /api/v1/zotero/sync`，body `{force, project_path}` |
| `zotero_sync_status` | `GET /api/v1/zotero/sync-status` |

`sync-status` 响应：

```json
{
  "last_sync_ts": null,
  "last_sync_at": "2026-10-27T03:05:00Z",
  "item_count": 12,
  "wiki_page_count": 3,
  "embedding_configured": true,
  "vector_dim": 1024,
  "sync_in_progress": false,
  "errors": []
}
```

新增通道后必须 `npm run ipc:manifest` 重新生成 `electron/ipc-manifest.json`，
否则 `electron/__tests__/ipc-contract.test.ts` 与后端
`backend/tests/contract/test_ipc_manifest_routes.py` 会同时红。

---

## 7. 测试覆盖

| 层 | 文件 |
| --- | --- |
| 可见性 | `backend/tests/unit/test_zotero_visible.py`、`test_tool_names.py` |
| 索引 | `backend/tests/unit/test_zotero_ingest.py`、`test_zotero_sync_routes.py` |
| MCP 工具 | `backend/tests/unit/test_zotero_mcp_server.py` |
| wiki 沉淀 | `backend/tests/unit/test_zotero_wiki_export.py` |
| 前端 API | `src/shared/api/__tests__/zoteroClient.test.ts` |
| 同步面板 | `src/pages/settings/__tests__/ZoteroSyncPanel.test.tsx` |
| Tab 集成 | `src/pages/settings/__tests__/ZoteroTab.test.tsx` |

---

## 8. 风险与边界

| 风险 | 缓解 |
| --- | --- |
| `mcp__*` 全局放行过宽 | 仅 primary 种子加；工具执行仍走 PermissionEngine 风险分级 |
| 大库首次全量索引耗时/费用 | 不自动全量；按钮明示耗时；分批嵌入 |
| embedding 未配置 | 分层降级到 SQL LIKE；同步记 error；UI 引导 |
| 图谱过密（标记文献互连） | 仅标记文献进图；标记数 >200 时在设计文档标注上限 |
| SQLite 读锁冲突 | `mode=ro` + 指数退避重试；失败进 `sync-status.errors` |
| py3.8（release/win7） | 新增后端代码纯 dataclass + `Optional[X]`/`List[X]`；不引入 pydantic 模型 |

**非目标（YAGNI）**：PDF 全文入向量库、PDF reference 段抽取 → 引用边、vision 图表理解、
inotify 实时监听、Collection/Tag 图谱节点、独立导入对话框（标记走 Zotero tag）。

## 2026-10-30 修复：REST 契约归一 + 项目绑定

- **REST 形状归一**：`backend/api/zotero_routes.py` 在路由层把
  `ZoteroClient` 的混合形状转换为文档化契约：`date → year`、拼接作者
  字符串/对象数组 → `list[str]`、标签对象 → `list[str]`、Collection
  `parentKey/itemCount → parent_key/item_count`、`pageLabel →
  page_label`；`get_item()` 附件新增 `key` / `filename`。修复设置页
  「文献库」在真实库上的渲染报错与分类筛选失效。
- **项目绑定**：新增设置键 `zotero_wiki_project_path`（设置 → 文献库 →
  Wiki 项目路径）。`POST /zotero/sync` 在未显式传 `project_path` 时回退
  到绑定值；启动期后台增量同步在绑定存在时也会把带 Wiki 标签的文献
  沉淀到该项目的 `wiki/zotero/`。`GET /zotero/sync-status` 返回
  `wiki_project_path` 供 UI 显示。

