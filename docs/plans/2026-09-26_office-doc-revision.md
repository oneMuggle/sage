# 方案：Office 文档版本一致性（F1 + F2）

> 批次：P0-A 第一刀。来源：[docs/mcp-office-capability-analysis-20260926.md](../mcp-office-capability-analysis-20260926.md) 的 F1（预览与应用未绑定同一文档版本）与 F2（预览缓存不按内容版本失效）。
> 分支：`feat/office-doc-revision`，worktree `.worktrees/office-doc-revision`，基线 `origin/main` = `82fbb9938`（与分析报告固定基线一致）。

## 1. 问题复述（已在基线代码核对）

- `OfficeDocUpdateRequest` 只有 `ops`；`POST /office/doc/{doc_id}/update` 直接 `apply_doc_update(conn, doc, req.ops)`，重新读当前磁盘文件，没有任何期望版本校验。
- `preview_update(source, ops)` 返回 `DiffPreviewResult{ok, changes, truncated, error}`，不带来源版本标识，用户批准的差异无法与后续写入绑定。
- 复现（报告第九节）：Excel `Data!A1=10` → 预览 `10→20` → 外部写 `999` → 应用仍成功，结果 `20`，外部写入被静默丢弃。
- 前端 `OfficePreviewPanel` 的高保真缓存键是 `${summary.id}:${summary.metadata.file_size_bytes}`；同 id 同字节大小的不同内容命中同一缓存。`DocxNativePreview` 的 effect 依赖 `[workspacePath, managedPath]`，内容更新不触发重渲染，迟到响应也没有版本判别。

## 2. 目标与非目标

**目标**

1. 预览产出可校验的来源版本（内容哈希）+ 操作哈希 + 预览 ID。
2. 应用可携带 `expected_revision`；不一致返回 **409**，要求重新预览，原文件不动。
3. 应用支持 `idempotency_key`：重复提交不重复追加内容。
4. 同一文档的写入串行化（进程内单文档写锁），把「读哈希 → 编辑 → 落库」变成一个临界区。
5. 前端预览缓存与原生渲染改用内容 revision 作键，消除同大小碰撞与迟到响应错配。
6. 聊天工具写入路径（`OfficeToolService.update`）与 API 走同一版本语义，不再是两套契约。

**非目标（本批次不做，避免夸大）**

- 不做跨进程文件锁：外部 Word/WPS 不遵守应用内锁，本方案只保证「陈旧写入被拒绝」，不保证「外部进程不能改文件」。
- 不做持久化幂等台账：幂等记录是进程内有界缓存，重启即失效（失效后退化为普通写入，不会造成数据损坏）。
- 不动 F3（saved/verified/recoverable 状态区分）、F4、F5，另批次处理。

## 3. 设计

### 3.1 新模块 `backend/office/revision.py`

| 导出 | 职责 |
| --- | --- |
| `compute_file_revision(path)` | 流式 sha256，返回 `sha256:<64hex>`；文件不存在抛 `OfficeFileNotFoundError` |
| `compute_ops_hash(ops)` | 规范化 JSON（`sort_keys`, `ensure_ascii=False`）后 sha256，返回 `ops:<16hex>` |
| `new_preview_id()` | `pv_<32hex>`，仅作关联标识，不承担鉴权 |
| `document_write_lock(doc_id)` | 进程内按 doc_id 的可重入串行锁（contextmanager） |
| `remember_apply / lookup_apply` | 有界（64 条）幂等台账：`(doc_id, key) → {revision_before, revision_after, payload}` |

py38 兼容：只用 `typing.Dict/List/Optional`、`hashlib`、`threading`、`collections.OrderedDict`，不用 `:=` 之外的新语法特性与 `datetime.UTC`。

### 3.2 错误与状态码

`backend/office/errors.py` 新增 `OfficeRevisionConflictError(OfficeError)`，携带 `expected` / `actual`；`office_error_to_http_status` 在写失败分支之前返回 **409**。它不继承 `OfficeEditError`，以免被 `_WRITE_FAILURE_ERRORS` 抢先映射成 500。

### 3.3 预览契约（`backend/office/diff_preview.py`）

`DiffPreviewResult` 增补三个可选字段（新增字段，老客户端忽略即可）：

- `source_revision`：预览读取时刻的源文件内容哈希；
- `ops_hash`：本次预览的操作哈希；
- `preview_id`：本次预览 ID。

`ok=False` 的失败预览同样返回 `source_revision`（能读到文件时），便于 UI 展示「你看到的是哪一版」。

### 3.4 应用契约（`backend/office/apply_update.py` + 路由）

请求增补：`expected_revision`、`idempotency_key`（均可选，保持向后兼容）。

`apply_doc_update` 流程改为：

1. 进入 `document_write_lock(doc.id)`；
2. 幂等查表：命中且 `revision_after == 当前磁盘 revision` → 直接返回旧结果（`idempotent_replay=True`），不再写文件；
3. 计算 `current = compute_file_revision(path)`；`expected_revision` 存在且不等 → 抛 `OfficeRevisionConflictError`（409，文件零改动）；
4. 原有流程：快照 → 编辑 → 落库 → 自检 → 自检历史；
5. 计算 `revision_after`，写入幂等台账；
6. 结果增补 `revision`、`previous_revision`、`idempotent_replay`。

`expected_revision` 缺省时行为与今天完全一致（不阻断存量调用方），但响应里一定带回 `revision`，让调用方能升级为「读改写」闭环。

### 3.5 聊天工具路径（`backend/office/tool_service.py`）

`update()` 增加可选 `expected_revision`，冲突时返回 `{"success": False, "error": {"code": "revision_conflict", "expected", "actual"}}`；成功返回增补 `revision`。`office_update` 工具 schema 增补同名可选参数，描述写明「来自 office 预览/读取返回的 revision」。这样聊天与 API 两条写入路径共用同一语义，不再各写一套。

### 3.6 前端（F2）

- 新增纯函数模块 `src/features/office/previewRevision.ts`：`buildPreviewCacheKey({docId, revision, updatedAt, sizeBytes})` —— 有 revision 用 revision，缺失时退化为 `updated_at:size` 并显式标记 `degraded`，便于测试与后续收敛。
- `officeApi` 增补 `docRevision(docId)`（走新路由 `GET /office/doc/{doc_id}/revision`，返回 `{revision, size_bytes, mtime_ms}`）、`previewUpdate` 结果类型补三字段、`updateDocument` 透传 `expected_revision` / `idempotency_key`。
- `OfficePreviewPanel`：在 summary 变化时拉取 revision；高保真缓存键改用 `buildPreviewCacheKey`；异步响应回来时比对「请求发起时的 key」与「当前 key」，不一致则丢弃（迟到响应隔离）。
- `DocxNativePreview`：新增 `revision` prop 并纳入 effect 依赖 + 响应守卫。
- `OfficeEditPreviewDialog`：预览返回的 `source_revision` 存入 state，应用时作为 `expected_revision` 提交，并生成一次性 `idempotency_key`；409 时提示「文档已被外部修改，请重新预览」并自动重跑预览。
- `electron/commands.ts` 的 `office_doc_update` 已用 rawBody 透传，新字段无需改路由；`demoInterceptors` 同步补字段，保持 demo E2E 不红。

## 4. 测试计划

| 层 | 用例 |
| --- | --- |
| pytest 单测 | `compute_file_revision` 稳定性/变更敏感；`compute_ops_hash` 与键序无关；幂等台账有界淘汰；写锁串行 |
| pytest 集成 | 预览返回 `source_revision` 且等于源文件哈希；预览后外部改文件 → 应用带 `expected_revision` → 409 且**原文件字节不变**（正是报告里那条复现，现在必须被拒）；revision 匹配 → 应用成功且返回新 revision；同 `idempotency_key` 重复应用 → 内容只变一次；缺省 `expected_revision` → 保持旧行为 |
| pytest 工具层 | `OfficeToolService.update` 冲突返回 `revision_conflict`，成功返回 `revision` |
| vitest | `buildPreviewCacheKey`：同 id 同大小不同 revision → 不同键；缺 revision 退化路径；`OfficePreviewPanel` 迟到响应不污染当前文档；`DocxNativePreview` revision 变化触发重载 |

验收口径对齐报告 §7.2：「并发与幂等」「预览一致性」两行；「原件安全」用 409 路径的字节哈希断言覆盖。

## 5. 风险

1. **大文件哈希成本**：20MB 上限下 sha256 约数十毫秒；`GET /revision` 按 `(path, size, mtime_ns)` 做进程内记忆化，避免重复哈希。
2. **存量调用方**：`expected_revision` 可选，默认行为不变；只有前端编辑对话框强制带上。
3. **win7 线**：本批次只用 py38 安全语法，移植另起小批次（不在本 PR）。
4. **进程内锁边界**：多进程/多实例部署下不生效——文档里明确写成「同进程串行 + 版本校验兜底」，不宣称跨进程互斥。

## 6. 交付顺序

1. `revision.py` + errors（含单测）
2. 预览契约 + 应用契约 + 路由 + `GET /revision`（含集成测试）
3. tool_service / 工具 schema
4. 前端 helper + api + 面板/对话框 + demo 拦截器（含 vitest）
5. `npx vitest run` 相关目录 + `pytest -q backend/tests`（Office 相关）+ `npm run typecheck`
6. PR：说明本地 hook 绕过情况（如有），CI 为权威门禁
