# Chat-native Office CRUD 设计

> **状态：** 已批准设计，待 spec 自审和用户复核
> **日期：** 2026-07-23
> **目标分支：** `main`
> **实施分支：** `fix/office-phase1-hardening`
> **关联计划：** `docs/plans/2026-07-16_office-features.md`
> **前置审计提交：** `91c2c0e`（独立 Office 组件加固设计，现已 superseded）
> **后续分支：** `release/win7` 仅在 main 完成并验证后通过独立 cherry-pick PR 同步

## 1. 产品能力声明

Sage 的 Office 能力不应以独立页面为主要工作流，而应成为 Chat Agent 可调用的本地文档能力：

> 用户在一个 Chat session 中绑定 Workspace，通过 `@` 文件引用、拖放或文件选择器导入 `.docx/.pptx/.xlsx`；随后可以直接用自然语言让 Sage 列出、读取、创建、修改、归档和恢复 Office 文档。每次创建、修改、归档和恢复都先生成可审阅的操作 proposal，用户批准后才执行；修改始终生成派生新版本，原文件不覆盖。

当前主对话实际走 legacy `SageAgent.run_loop`：

- Chat stream：`backend/api/legacy_routes.py:960-1197`；
- ReAct/tool call：`backend/core/legacy/agent.py:449-621`；
- 工具注册：`backend/tools/registry.py:17-123`；
- Office 当前仍只通过 `/api/v1/office/*` 和 `/office` 页面使用：`backend/api/office_routes.py:195-312`。

因此本设计采用 **共享 Office 领域服务 + legacy-first ToolRegistry + future hex adapter**，不把 Office 只接到当前尚未成为主 Chat 路径的 hex `ChatService`。

## 2. 已确认产品决策

| 决策 | 结果 |
|---|---|
| Chat 入口 | Office 操作主要通过自然语言对话完成 |
| 文件授权 | `@` 文件选择、Chat 拖放或原生选择器；不信任 LLM 自由路径 |
| 会话范围 | 每个 Chat session 绑定一个 Workspace |
| LLM 文件参数 | 只允许 `doc_id`，不允许 `file_path`/`workspace_path` |
| 修改 | 只支持结构化常用操作，始终生成新版本，原文永不覆盖 |
| 删除 | 对话中的删除表现为确认后归档到 Workspace 回收区，可恢复 |
| 写操作确认 | create/edit/archive/restore 全部需要用户确认；list/read 不确认 |
| Office 页面 | 保留为文件管理视图，不再作为主要生成/编辑入口 |
| 独立生成表单 | 移除；创建统一通过 Chat tool |
| 旧格式 | 只支持 `.docx/.pptx/.xlsx`，不支持 `.doc/.xls/.ppt` |
| Windows | M0 需要修复 Windows 路径和 bundled 依赖；Win7 同步另开 PR |
| 迁移策略 | 本次先接入真实 legacy Chat；不在同一阶段迁移整个 Chat 到 hex |

## 3. 范围与非目标

### 3.1 本次范围

- M0：完成旧 Phase 1 的安全、打包、测试和导入基础修复；
- M1：会话 Workspace binding、Office 文件导入和 `@` 引用；
- M2：Office 只读 tools 接入当前 legacy Agent；
- M3：Office create/edit、派生版本和 approval stream；
- M4：archive/restore 和 `/office` 文件管理视图；
- M5：完整验证、工具结果持久化和 future hex adapter 契约；
- 技术文档、用户手册、Chat/Office E2E 和安全 review。

### 3.2 非目标

- Office 原貌渲染；
- 完整 Word/PPT/Excel 编辑器；
- 字体、分页、动画、母版、宏、OLE、修订和复杂图表的高保真 round-trip；
- `.doc/.xls/.ppt` 旧二进制格式；
- CSV、ODF；
- PDF/图片/其他格式转换；
- Microsoft Office COM、LibreOffice、OnlyOffice 或 OfficeCLI；
- LLM 自动执行 shell、打开外部程序或直接永久删除文件；
- 多人协作、云端同步、版本控制系统集成；
- 本次直接迁移 legacy Chat 到 hex ChatService；
- 本次直接修改 `release/win7` 分支。

## 4. 目标架构

```text
ChatInput
  ├── @文件 / 拖放 / Office 文件选择
  └── session Workspace binding
          │
          ▼
/api/v1/chat/stream
          │
          ▼
legacy SageAgent.run_loop
          │
          ├── ToolRegistry.get_schemas(request_context)
          ├── Office*Tool
          │       │
          │       ▼
          │   OfficeToolService
          │       ├── session/doc_id authorization
          │       ├── Office readers/generators/editors
          │       ├── version/archival storage
          │       └── operation audit
          │
          └── ApprovalBus（写操作暂停/恢复）
                  │
                  ▼
           NDJSON approval_required
                  │
                  ▼
             React approval card
                  │
                  ▼
           approve/reject current stream
```

Office 领域逻辑只放在 `OfficeToolService`，不直接依赖 FastAPI、Electron、React 或具体 Agent：

```text
OfficeToolService
  ├── list(session_id, filters)
  ├── read(session_id, doc_id, section)
  ├── create(session_id, spec)
  ├── prepare_edit(session_id, doc_id, operations)
  ├── apply_edit(proposal_id)
  ├── archive(session_id, doc_id)
  └── restore(session_id, doc_id)
```

适配层：

- 当前：`Office*Tool` 继承 `BaseTool`，注册到 legacy `ToolRegistry`；
- 后续：hex `ChatService` adapter 复用同一个 `OfficeToolService`；
- `/office` 页面：管理 API 复用 service，但不重新实现 Office 业务逻辑。

## 5. 会话 Workspace 与文件句柄

### 5.1 Workspace binding

新增 SQLite 表：

```sql
CREATE TABLE IF NOT EXISTS session_workspace_bindings (
  session_id TEXT PRIMARY KEY,
  workspace_path TEXT NOT NULL,
  activated_at INTEGER NOT NULL,
  revoked_at INTEGER NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

规则：

- Workspace 路径由用户通过 Electron 原生目录选择器提供；
- 后端保存 canonical absolute path；
- 一个 session 同时只有一个 active Workspace；
- `revoked_at IS NOT NULL` 的 binding 不能授权 Office tools；
- LLM 不可设置或修改 Workspace path；
- Workspace 变更必须经过用户界面，并重新验证目录存在、是目录且未逃逸。

### 5.2 Office 文档表扩展

现有 `office_documents` 表继续保存文件元数据，增加：

```sql
ALTER TABLE office_documents ADD COLUMN derived_from TEXT NULL;
ALTER TABLE office_documents ADD COLUMN archived_at INTEGER NULL;
```

不增加 `session_id`：同一个 Workspace 可被多个 session 使用，权限通过 session binding 与 `workspace_path` 联表决定。

文档托管路径：

```text
<canonical-workspace>/office/<doc_type>/<doc_id>/<filename>
```

回收区路径：

```text
<canonical-workspace>/.office-trash/<doc_type>/<doc_id>/<filename>
```

路径安全必须使用 component-aware `relative_to()`/`path.relative()`，不能使用硬编码 `/` 的字符串前缀。M0 新增标准库 `backend/office/path_safety.py`，同时修复 `backend/api/office_routes.py:65-84` 和 `backend/office/storage.py:71-89` 的 Windows 问题。

### 5.3 ChatOfficeRef

Renderer 与 Chat API 传递引用而不是路径：

```typescript
export interface ChatOfficeRef {
  docId: string;
  docType: 'ppt' | 'word' | 'excel';
  filename: string;
}
```

消息中的 `@报告.docx` 是展示文本；实际 payload 额外包含 `officeRefs: ChatOfficeRef[]`。LLM tool schema 仍只使用 `doc_id`。

## 6. Chat 文件导入

### 6.1 `@` 文件搜索

当前 `AtFileMenu` 调用 `workspace_search_files`，但 Electron `COMMAND_ROUTES` 和 backend 均未实现：

- `src/shared/api/fileSearchClient.ts:83-95`；
- `electron/commands.ts:13-196`；
- `src/features/chat/AtFileMenu.tsx:43-60`。

M1 实现：

```text
当前 session Workspace
→ workspace_search_files(query)
→ 返回 filename/doc_type/doc_id/status/size
→ 用户选择 Office 文件
→ ChatInput 保存 ChatOfficeRef
→ 发送消息时携带 officeRefs
```

搜索只能作用于当前 session Workspace。后端不得接受一个由 LLM 自由拼接的根路径。

搜索结果分为两类：

- 已托管文件：返回 `doc_id`，用户选择后直接加入 `ChatOfficeRef`；
- Workspace 内但尚未托管的 `.docx/.pptx/.xlsx`：Renderer 只接收用于导入的本地路径和 `needsImport=true`，用户选择后由 Electron copy/import，完成解析并取得 `doc_id`；该路径不会进入 Chat payload 或 LLM context。

任何进入 `ChatOfficeRef` 的 Office 文件都必须先完成托管和 `office_documents` 持久化。

### 6.2 外部文件导入

当前 Chat attachments 在 `useFileUpload` 中只生成 UI data URL，后端 `ChatRequest` 不接收附件：

- `src/shared/lib/hooks/useFileUpload.ts:28-49`；
- `src/widgets/chat/Message.tsx:118-137`；
- `backend/api/legacy_routes.py:89-111`。

M1 改为：

```text
Office 拖放/文件选择
→ Electron 验证扩展名和大小
→ 复制到当前 Workspace 托管目录
→ 解析并创建 office_documents(status=parsed)
→ 返回 ChatOfficeRef
→ ChatInput 将 ref 加入待发送消息
```

Office 二进制不进入 LLM prompt、不以 base64 传输。图片和普通附件保留现有行为。

导入源文件永不移动或删除；复制失败和解析失败必须清理本次临时托管目录。M0 的一次性 pending import token 继续适用，但 token 只能清理当前导入副本。

## 7. Office Tool 契约

### 7.1 `office_list`

```text
office_list(
  query?: string,
  doc_type?: "ppt" | "word" | "excel",
  include_archived?: boolean,
  limit?: integer
)
```

默认返回当前 session Workspace 中未归档文档的：

```text
doc_id, doc_type, filename, status, derived_from, archived_at,
created_at, updated_at, file_size_bytes

`status` 继续使用现有 `parsed/generated/edited` 枚举；归档状态由非空 `archived_at` 表示。
```

不返回任意本机路径。

### 7.2 `office_read`

```text
office_read(
  doc_id: string,
  section?: "summary" | "head" | "all"
)
```

- `summary` 返回元数据；
- `head` 返回受限的开头结构化内容；
- `all` 受 `ToolPolicy.max_read_bytes`、`max_output_bytes` 和结果条数限制；
- 只返回结构化 JSON，不返回原始 OOXML bytes；
- 读取前校验 doc_id 属于当前 session Workspace 且未归档。

### 7.3 `office_create`

```text
office_create(
  doc_type: "ppt" | "word" | "excel",
  filename: string,
  spec: object
)
```

`spec` 复用现有 Pydantic generator constraints：

- PPT：slides/title/bullets/notes；
- Word：title/paragraphs/tables；
- Excel：sheets/headers/rows。

工具不接收路径，输出写入当前 session Workspace 的新 UUID 目录。写入前必须 proposal + 用户确认。

### 7.4 `office_edit`

```text
office_edit(
  doc_id: string,
  operations: OfficeEditOperation[]
)
```

第一版操作：

```text
Word:
  replace_paragraph(index, text)
  append_paragraph(text, heading?)
  replace_table_cell(table, row, col, text)

PPT:
  replace_slide_text(slide, old, new)
  append_slide(title, bullets, notes?)
  delete_slide(slide)

Excel:
  set_cell(sheet, row, col, value)
  set_range(sheet, start, values)
  add_sheet(name, headers, rows)
```

禁止 XML、Python、任意脚本和任意路径作为操作输入。

执行顺序：

```text
validate doc/session
→ load parent
→ prepare real old/new diff
→ proposal + confirmation
→ parent unchanged
→ generate child UUID
→ status=edited, derived_from=parent_id
→ save metadata + operation log
→ return child doc_id
```

确认前 parent 文件发生变化时 proposal 失效，必须重新读取并生成 diff。

### 7.5 `office_archive` / `office_restore`

`office_archive(doc_id)`：确认后把托管目录移动到 `.office-trash`，设置 `archived_at`，默认 list 隐藏。

`office_restore(doc_id)`：确认后检查原路径没有冲突，再移回托管目录并清空 `archived_at`。

归档不是立即永久删除；LLM 没有永久删除工具。

## 8. Approval stream

### 8.1 Proposal

所有 create/edit/archive/restore 在写盘前生成：

```text
OfficeProposal
- proposal_id
- session_id
- stream_id
- tool_name
- doc_id / parent_doc_id
- sanitized_summary
- diff_or_impact
- parent_file_fingerprint
- expires_at
```

Proposal 绑定 session、stream 和 parent 版本。用户可见内容由服务端根据真实文档生成，不能直接相信 LLM 自报 diff。

### 8.2 流程

```text
SageAgent 收到写 tool call
→ OfficeToolService.prepare_*
→ 写入 pending proposal
→ emit approval_required(proposal_id, preview)
→ 前端 OfficeApprovalCard
→ 用户 approve/reject
→ POST 当前 stream approval
→ 后端验证 session/proposal/TTL
→ 唤醒 legacy run_loop
→ apply_* 执行一次
→ tool_result
→ LLM 继续生成最终回答
```

实现 `PendingApprovalStore`：

- key 为 `stream_id + proposal_id`；
- TTL 60 秒；
- approve/reject 只能消费一次；
- 超时、断线、session mismatch、token replay 均 fail-closed；
- 重启后 pending proposal 全部失效；
- operation log 记录 `success/rejected/timeout/error`。

新增 Agent event 类型 `approval_required`，前端 `useChat` 保存待批准操作，`Message` 渲染 OfficeApprovalCard。读/list 不触发 proposal。

### 8.3 确认卡片

卡片展示：

- 操作类型；
- 文件名和版本；
- 目标位置；
- edit 的 old → new diff；
- archive 的影响范围；
- 批准/拒绝按钮。

不允许 LLM 自动确认，不允许 Chat 文本“我确认”绕过 UI approval token。

## 9. 工具执行上下文

当前 `SageAgent.get_available_tools()` 直接从 registry 返回全量 schema：

- `backend/core/legacy/agent.py:501,648-667`；
- `backend/tools/registry.py:90-106`。

增加 request-scoped `ToolExecutionContext`：

```text
ToolExecutionContext
- session_id
- stream_id
- workspace_path
- active_doc_scope
- confirmation_bus
- tool_budget
```

不把 context 变成 LLM 参数，也不把 Workspace 写进全局 singleton，避免多个 Chat session 互相污染。

`registry.get_schemas(context)` 规则：

- 没有 active Workspace：不暴露 Office tools，并由 system context 提示先绑定 Workspace；
- 已绑定 Workspace：暴露 office_list/read/create/edit/archive/restore；
- 工具执行时再次从 DB 校验 doc_id，不只依赖 schema 过滤；
- 现有普通文件工具继续使用 `ToolPolicy` 路径守卫。

## 10. 工具结果与跨轮记忆

当前 legacy 流中 tool result 会追加给同一轮的 LLM，但工具消息没有可靠的跨重启持久化。新版处理：

- 当前轮：继续使用 `tool_call → tool_result → 下一轮 LLM`；
- 每个 Office 操作写 `office_operation_log`；
- log 保存 doc_id、filename、operation、result summary，不保存完整敏感正文；
- 每次新 turn 的 system context 注入当前 session 最近 10 条 Office 操作摘要；
- 用户说“刚才生成的文档”时，LLM 可通过 operation summary 找到 doc_id，再调用 office_read；
- 完整文档内容不永久注入 system prompt，避免上下文膨胀。

## 11. 安全边界

必须满足：

1. tool schema 不包含 `workspace_path` 或任意 `file_path`；
2. 所有 Office tool 只接受 doc_id；
3. doc_id 必须命中当前 session active Workspace；
4. revoked session 立即失去 Office tool authorization；
5. `@` 搜索只搜索当前 Workspace；
6. 导入由 Electron 用户动作触发，源文件不删除；
7. create/edit/archive/restore 经过 proposal token；
8. proposal 绑定 session、stream 和 parent fingerprint；
9. approval 超时、断线、拒绝、重放均不执行；
10. edit 不覆盖 parent；
11. archive 可恢复，不提供 LLM 永久删除；
12. openPath、Save As 和显示文件夹只由用户点击的 Electron UI 执行；
13. 文件名、doc_id、扩展名、大小、symlink 和 containment 双层验证；
14. Office tool budget 限制单轮操作数量和输出大小；
15. 错误返回稳定 code，不向 LLM 暴露不必要的本机路径；
16. operation log 记录每次成功、拒绝、超时和错误。

## 12. `/office` 管理视图

保留 `/office` route 和 Sidebar 入口，但重新定位为当前 session Workspace 的管理视图：

保留：

- 导入和引用；
- 结构化预览；
- 当前文档列表；
- 派生版本树；
- 回收区和恢复；
- 打开文件、打开目录、另存为。

移除：

- 独立 Workspace 真相；
- 独立生成表单；
- 直接覆盖编辑入口。

预览页增加“引用到当前对话”，把 `ChatOfficeRef` 加入 ChatInput。创建和修改统一由 Chat 完成。

## 13. M0-M5 实施分解

### M0：基础安全与打包修复

- Windows path containment；
- `requirements-bundled.txt` 增加 `python-pptx/python-docx/openpyxl`；
- Office tests 迁入 `backend/tests` 并进入 CI；
- 只允许现代 OOXML；
- Electron 导入 copy、Save As、open/show-folder；
- read history 持久化；
- archive 基础目录与安全删除；
- M0 不接 LLM。

### M1：会话 Workspace 与 Chat 文件引用

- binding 表和 CRUD；
- Chat Workspace 绑定 UI；
- `workspace_search_files` backend/IPC；
- `ChatOfficeRef`；
- `@` 选择、Office drag-drop import；
- 当前 session 的 Office 文档列表。

### M2：只读 Chat tools

- `OfficeToolService`；
- `office_list`、`office_read`；
- legacy ToolRegistry request context；
- Office tool schemas 动态过滤；
- read tool result 进入同一轮最终回答；
- operation summary。

### M3：创建、修改、版本和 approval

- `office_create`；
- Word/PPT/Excel structured edit；
- `derived_from` 和 parent fingerprint；
- proposal/diff；
- approval_required stream event；
- approve/reject/timeout resume；
- 原文不变测试。

### M4：归档恢复和管理视图

- `office_archive`、`office_restore`；
- `.office-trash`；
- `/office` 去掉独立生成表单；
- 版本树和 Chat 引用；
- Save As/open/show-folder UI。

### M5：验证与 hex adapter

- Chat/Electron/Backend 完整 E2E；
- 安全 review 和覆盖率；
- tool result 跨轮摘要；
- 定义 hex ChatService adapter 契约，但不迁移整个 Chat；
- main 合并后另开 Win7 cherry-pick PR。

## 14. 测试策略与验收

### 14.1 Backend

- Session binding：session 隔离、revoked、canonical path；
- OfficeToolService：list/read/create/edit/archive/restore；
- doc_id 越权、path 参数拒绝、归档状态；
- 版本 tree、parent fingerprint conflict；
- legacy Agent mock tool call；
- read → tool result → 下一轮回答；
- approval approve/reject/timeout/replay/disconnect；
- migration、operation log、Windows/POSIX path；
- bundled requirements contract 和 `import backend.main` canary。

### 14.2 Electron/Frontend

- Workspace bind；
- picker、drag-drop、copy cleanup；
- `@` 搜索和 ChatOfficeRef；
- approval card 和 stream resume；
- create/edit/archive proposal 展示；
- reject 后文件和 DB 不变；
- open/save/show-folder；
- `/office` 版本树、归档、恢复和“引用到对话”；
- IPC 不接受任意路径。

### 14.3 E2E 主流程

```text
创建 Chat session
→ 绑定 Workspace
→ 导入 docx
→ Chat: “读取这份文档并总结”
→ Chat: “把第 3 段改成……”
→ 显示真实 diff
→ 拒绝：原文和 DB 不变
→ 再次修改并批准：生成新版本
→ Chat: “列出当前文档”
→ Chat: “归档旧版本”
→ 确认后进入回收区
→ /office 恢复旧版本
```

必须验证拒绝不写盘、原文不覆盖、不同 session 不能越权、approval 超时不执行。

### 14.4 验收清单

- [ ] Chat session 可绑定一个 Workspace；
- [ ] `@`/拖放可以导入并得到 ChatOfficeRef；
- [ ] LLM 只能收到 doc_id，不收到自由路径工具参数；
- [ ] `office_list/read` 可在对话中完成文件查找和读取；
- [ ] Chat 可创建基础 docx/pptx/xlsx；
- [ ] Chat 可对 Word/PPT/Excel 执行结构化修改；
- [ ] create/edit/archive/restore 均显示 proposal 并等待确认；
- [ ] reject/timeout/disconnect 不产生文件副作用；
- [ ] edit 始终生成新版本，parent 不变；
- [ ] archive 可在 `/office` 恢复；
- [ ] 操作结果在当前回答和后续 turn 可通过 doc_id 继续引用；
- [ ] `/office` 不再提供独立生成表单，成为管理视图；
- [ ] Windows path 和 bundled dependency canary 通过；
- [ ] Backend、Frontend、Electron、Chat E2E 全绿；
- [ ] Office/Chat 关键模块覆盖率 ≥80%；
- [ ] 技术文档和用户手册准确描述 Chat-native 工作流；
- [ ] main 完成后未直接修改或合并 `release/win7`。

## 15. 文档和交接

实施完成后：

1. 更新 `docs/technical/33-office-phase1.md`，记录 OfficeToolService、工具契约、session binding、approval、版本和安全边界；
2. 新增 `docs/user-manual/07-office.md`，说明 Chat 中导入、读取、创建、修改、归档、恢复和确认；
3. 更新两个 README 目录；
4. 更新 `docs/plans/2026-07-16_office-features.md`，将其 Phase 1 语义改为 Chat-native M0-M4，Phase 2/3 保留未完成；
5. 将旧的独立组件设计 `2026-07-23-office-phase1-hardening-design.md` 标记为 superseded，并链接本文件；
6. 新 implementation plan 完成并合并正式文档后删除；
7. 本 spec 保留作为 Chat-native 设计基线。

下一步只有在本 spec 复核通过后，才调用 writing-plans 生成按 M0-M5 拆分的 TDD 实施计划。
