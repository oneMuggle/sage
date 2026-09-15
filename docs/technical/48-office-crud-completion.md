# 48. Office CRUD 闭环完成（PR-1..5 系列）

> **适用范围**: Sage main @ 2026-09-04 PR #412 / #414 / #415 / #416,#417（release/win7 cherry-pick）
> **基础 commit**: `1f83e1ae`（worktree 文档基线,实际合并时 main HEAD 会推进）
> **前序**: PR #405 `9e919ec5` —— 引入 office_update / office_delete,本系列在其上闭环

## 1. 概述

Sage 的 Office 能力自 2026-07 起分阶段落地（M0 foundation → M1-M2 chat-read → M5 chat-write）,
但落地的只是「拆件」——读、写、改、删各自孤立,缺乏闭环。本系列 5 个 PR 把零散的 Office 能力
拼成一条完整的 CRUD 闭环:

| 维度 | 解决的具体问题 |
|---|---|
| **能力可达性** | office_create / update / delete 工具已实现,但没进任何 profile 的白名单 —— LLM 看得见 schema 但收不到工具调用 |
| **删除语义** | office_delete 是真删除,大量误操作不可恢复 —— 需要「归档而非删除」的温和路径 |
| **编辑安全** | 没有「撤销最近一次编辑」路径 —— 需要在 update 之前自动 snapshot |
| **聊天引用** | 用户在 chat 里 `@MeetingNotes.docx`,后端按 UUID 查不到 → 404 |
| **元数据保持** | re-read 文档时 INSERT OR REPLACE 把 archived_at / derived_from / original_filename 全抹了 |
| **二进制防护** | write_file 允许 LLM 用 utf-8 文本覆盖 `.png` / `.pdf` / `.docx` / `.zip` 等 → 静默文件损坏 |
| **Win7 兼容** | release/win7 分支没跟上,缺 /office 路由 + 整个 CRUD 闭环 |

最终交付:**用户可以放心地用 chat 自然语言增删改查 docx / xlsx / pptx,误删可恢复,二进制文件不会被文本流破坏,Win7 用户也有同等能力。**

---

## 2. 5 个 PR 各自做了什么

### 2.1 PR #412 `fix/office-crud-wiring`（PR-1,base=main）

**GitHub**: https://github.com/oneMuggle/sage/pull/412
**分支**: `fix/office-crud-wiring`
**HEAD**: `6d7646ee`
**关键 commits**:

| Commit | 标题 | 作用 |
|---|---|---|
| `26a96cfa` | `fix(agents): LEGACY_TOOL_NAME_RENAMES migration` | PR #381 把 TerminalTool 改名为 BashTool,但存量 DB 还存着旧名 `terminal` / `file_read` / `file_write`,先跑迁移段把它对齐到当前工具名 |
| `20fa5ff5` | `fix(office): 修复绑定工作区下 PPT 创建必失败` | `_coerce_ppt_request` 把 title=filename 传给 forbid extra 的 `OfficePptGenerateRequest`,`ValidationError` 被折成 `generation_failed`。同时把字符串 content 的裸 `TypeError` 改成 `content_shape_invalid` 错误码 |
| `7c3bba10` | `fix(agents): 启动时差集兜底迁移` | 既有 4 段迁移用 `set(tools) == 旧种子`,存量 DB 一旦落在任何历史快照之外就全部哑炮。新增 `_append_missing_tools` 差集段:当前默认 ⊆ DB 时补缺,真超集与完全不相交一律不动 |
| `884f6175` | `fix(agents): office 五件套接入 primary / writer 白名单` | **核心修复** —— primary.tools 追加 office_list/read/create/update/delete;writer.tools 追加 office_list/read/create/update(不给 delete)。`_PRIMARY_CURRENT_DEFAULT_TOOLS` / `_WRITER_CURRENT_DEFAULT_TOOLS` 同步追加,差集段才能补齐 office 工具 |
| `6d7646ee` | `fix(ci): distinguish npm 503 infrastructure failure from malformed report` | audit fix —— npm 11+ 在 Cloudflare 后面返回的 HTTP envelope 不再被误报成 malformed,所有后续 PR 都 cherry-pick |

**解决的问题**: office 工具从来没进过任何 profile 的 tools 列表 —— LLM 一直看不见。系统提示词 `_OFFICE_CREATE_CAPABILITY_PROMPT` 在声明能力,但白名单过滤把工具一刀切掉。

**关键修改**:

| 文件 | 改动 |
|---|---|
| `backend/agents/profiles.py` | +97 -1 — primary / writer profile 加 office_* 工具,默认常量同步,system prompt 升级 |
| `backend/office/errors.py` | +7 -1 — 新增 `OfficeContentShapeError` (422) |
| `backend/office/tool_service.py` | +18 -14 — PPT / Excel 请求形状校验 |
| `backend/tools/office_create_tool.py` | +2 -1 — 把裸 TypeError 折成 `content_shape_invalid` |
| `backend/tests/unit/office/test_tool_service.py` | +81 — PPT shape validation cases |
| `backend/tests/unit/test_profiles_legacy_tool_rename.py` | +112 新 — 锁住 `terminal → bash` / `file_read → read_file` / `file_write → write_file` |
| `backend/tests/unit/test_profiles_office_tools.py` | +96 新 — primary/writer 可见集 + 其他角色不可见 + 未绑定工作区时 list/read 自动隐藏 + 白名单与差集常量同步 |
| `backend/tests/unit/test_profiles_subset_migration.py` | +171 新 — 差集兜底迁移 11 case |

**测试覆盖**:

| 套件 | 新增 case | 状态 |
|---|---|---|
| `test_profiles_legacy_tool_rename.py` | 6 | PASS |
| `test_profiles_office_tools.py` | 8 | PASS |
| `test_profiles_subset_migration.py` | 11 | PASS |
| 完整 profiles / office / agents 回归 | 454 | PASS |

---

### 2.2 PR #414 `feat/office-archive-restore`（PR-2,base=main）

**GitHub**: https://github.com/oneMuggle/sage/pull/414
**分支**: `feat/office-archive-restore`
**HEAD**: `bc51ea74`
**关键 commits**:

| Commit | 标题 | 作用 |
|---|---|---|
| `203a56dd` | `feat(office): archive/restore + pre-edit snapshot` | archive_document / restore_document / snapshot_pre_edit 三个 service 方法 + OfficeToolService.archive / .restore + OfficeRestoreTool 工具 + session_workspace 旁路 helper |
| `bc51ea74` | `fix(ci): distinguish npm 503` | audit fix |

**解决的问题**:

1. **`office_delete` 是真删除** —— 大量误操作不可恢复。需要「归档」而非「删除」的温和路径。
2. **没有「撤销最近一次编辑」路径** —— 用户后悔某次 update,需要 archive/restore 之外的便捷回滚。
3. **profile 白名单缺 office_create/update/delete** —— PR-1 (#405) 当年没挂到 profile,本 PR 一次性补齐。

**关键修改**:

| 文件 | 改动 |
|---|---|
| `backend/office/storage.py` | +111 -5 — `archive_document` / `restore_document` / `snapshot_pre_edit` 三个 service 方法（M0 `archived_at` 列终于有了 service 调用方） |
| `backend/office/session_workspace.py` | +27 — `get_document_in_workspace_any_status` 旁路 `archived_at IS NULL` 过滤,让 archive / restore 能找到 archived 行 |
| `backend/office/tool_service.py` | +127 — `OfficeToolService.archive` / `.restore`（idempotent:archive 已 archived 返原 ts,restore 已 live 返 success 不动行） |
| `backend/tools/office_restore_tool.py` | +93 新 — `requires_tool_context=True`, `WRITE_LOCAL` risk,doc_id mode only |
| `backend/tools/__init__.py` | +7 — 注册 `OfficeRestoreTool` |
| `backend/agents/profiles.py` | +26 -1 — primary + writer profile 加 `office_create` / `office_update` / `office_delete` / `office_restore`;system prompt 补 archive/restore/snapshot 三段 |
| `backend/tests/unit/office/test_storage_snapshot.py` | +275 新 — 13 case(archive / restore / snapshot 行为) |
| `backend/tests/unit/office/test_tool_service_archive_restore.py` | +363 新 — 12 case(archive success/idempotent/unknown/stale、restore 同、round-trip、IO 失败不阻 edit) |

**测试覆盖**:

| 套件 | case | 状态 |
|---|---|---|
| `test_storage_snapshot.py` | 13 | PASS |
| `test_tool_service_archive_restore.py` | 12 | PASS |
| 完整 office 单测回归 | 295 | PASS |

---

### 2.3 PR #415 `fix/office-chat-ref-filename`（PR-3,base=main）

**GitHub**: https://github.com/oneMuggle/sage/pull/415
**分支**: `fix/office-chat-ref-filename`
**HEAD**: `d548ecc2`
**关键 commits**:

| Commit | 标题 | 作用 |
|---|---|---|
| `59a06da7` | `fix(office): chat @ ref filename lookup + persist_read_summary merge` | find_document_by_filename helper + authorize_chat_office_request 兜底 + _persist_read_summary 保留字段 |
| `d548ecc2` | `fix(ci): distinguish npm 503` | audit fix |

**解决两个 Bug**:

#### Bug 1 —— chat `@<filename>` reference 404

`authorize_chat_office_request()` 只按 doc_id 查 `office_documents`,但前端传来的是用户可见的文件名（如 `MeetingNotes.docx`）,不是 managed UUID。lookup 返 None → chat_refs 抛 `WorkspaceDocumentNotFoundError` → 用户看到 404。

**修复**: 新增 `find_document_by_filename(conn, workspace_path, filename)` helper（按 `generated_filename` + workspace + `archived_at IS NULL` 过滤）。`authorize_chat_office_request()` 在 doc_id lookup miss 时 fallback 到 filename lookup;命中后用解析出的 managed UUID 填充 `office_doc_scope`。filename 命中 + doc_type 不匹配抛 `WorkspacePathMismatchError`(400);id 路径继续保留既有 404 行为以保证向后兼容。

#### Bug 2 —— re-read 退化既有元数据

`_persist_read_summary` 每次 read 都 `INSERT OR REPLACE`,覆盖了用户/系统已经写过的:
- `archived_at`(用户 archive 后被 re-read 重新激活)
- `derived_from`(lineage 丢失)
- `original_filename`(用户上传名被 stomp)

**修复**: 先 `get_document(conn, document_id)` 看老 row;存在则保留 `archived_at` / `derived_from` / `original_filename`(caller 传 None 时)/ `created_at`。`status` / `updated_at` / `metadata` 仍走 reader(read 产生新 content facts)。`metadata.file_size_bytes` 由 reader 通过 `file_path.stat().st_size` 自然写入,无需额外 override。

**关键修改**:

| 文件 | 改动 |
|---|---|
| `backend/office/session_workspace.py` | +36 — `find_document_by_filename` helper |
| `backend/office/chat_refs.py` | +40 -10 — filename fallback + type mismatch 400 分支 |
| `backend/api/office_routes.py` | +54 -13 — `_persist_read_summary` 合并字段 |
| `backend/tests/unit/office/test_chat_refs_filename_lookup.py` | +275 新 — 7 case(id hit / filename fallback / both miss / type mismatch / helper isolation ×3) |
| `backend/tests/unit/office/test_persist_read_summary_merge.py` | +390 新 — 5 case(fresh insert / archived 保留 / derived_from + updated_at / original_filename None 保留 / caller-supplied 覆盖) |

**测试覆盖**:

| 套件 | case | 状态 |
|---|---|---|
| `test_chat_refs_filename_lookup.py` | 7 | PASS |
| `test_persist_read_summary_merge.py` | 5 | PASS |
| office 单测回归 | 216 | PASS |
| office 集成测试 | 28 | PASS |

---

### 2.4 PR #416 `fix/write-file-binary-guard`（PR-4,base=main）

**GitHub**: https://github.com/oneMuggle/sage/pull/416
**分支**: `fix/write-file-binary-guard`
**HEAD**: `f8fbaeba`
**关键 commits**:

| Commit | 标题 | 作用 |
|---|---|---|
| `74368f71` | `fix(tools): write_file reject binary-extension targets` | `_BINARY_WRITE_BLACKLIST` frozenset + `WriteFileTool.execute()` 早返回拒绝 |
| `f8fbaeba` | `fix(ci): distinguish npm 503` | audit fix |

**解决的问题**:

`write_file` 此前允许 LLM 用 utf-8 文本流覆盖 `.png` / `.pdf` / `.docx` / `.zip` 等已知二进制扩展名文件,导致文件损坏。LLM 在生成 png / pdf / docx / 压缩包这类文件时,如果走错路径用 write_file 写文本,会静默写出不可读的损坏文件,用户得手动从 snapshot 恢复。

**关键修改**:

| 文件 | 改动 |
|---|---|
| `backend/tools/file_tool.py` | +32 — `_BINARY_WRITE_BLACKLIST` frozenset + workspace 边界检查后做早返回拒绝 |
| `backend/tests/unit/test_write_file_binary_guard.py` | +137 新 — 9 case(黑名单契约 / 命中拒绝 / 大小写归一 / 白名单放行 / 无扩展名 / 不落盘) |

**`_BINARY_WRITE_BLACKLIST` 扩展名分类**:

| 类别 | 扩展名 |
|---|---|
| 图片 | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.ico` |
| Office / PDF | `.pdf` `.docx` `.xlsx` `.pptx` `.doc` `.xls` `.ppt` |
| 归档 | `.zip` `.tar` `.gz` `.tgz` `.bz2` `.7z` `.rar` `.xz` |
| 音视频 | `.mp3` `.mp4` `.mov` `.avi` `.mkv` `.flac` `.wav` `.ogg` |
| 可执行 / 编译产物 | `.exe` `.dll` `.so` `.dylib` `.class` `.jar` `.pyc` `.pyo` `.wasm` `.o` `.obj` |

**测试覆盖**:

| 套件 | case | 状态 |
|---|---|---|
| `test_write_file_binary_guard.py` | 9 | PASS |
| file_tool + edit_tool 回归 | 90 | PASS |

---

### 2.5 PR #417 `fix/win7-office-crud-parity`（PR-5,base=release/win7）

**GitHub**: https://github.com/oneMuggle/sage/pull/417
**分支**: `fix/win7-office-crud-parity`
**HEAD**: `613803db`
**关键 commits**:

| Commit | 标题 | 作用 |
|---|---|---|
| `22059be1` | cherry-pick `6241c67d` (#402) | agent profile migration recovery |
| `3175d85b` | cherry-pick `26a96cfa` | LEGACY_TOOL_NAME_RENAMES migration |
| `50b227b9` | cherry-pick `7c3bba10` | 差集兜底迁移 |
| `d75f4365` | cherry-pick `20fa5ff5` | PPT 创建失败修复 |
| `959b023f` | cherry-pick `884f6175` | office 五件套接入 profile 白名单 |
| `9e32895a` | cherry-pick `6d7646ee` | audit fix(三个 PR 重复引用同一 commit 内容,只 cherry-pick 一次) |
| `7f4ae8ba` | cherry-pick `203a56dd` (PR-2) | archive / restore / snapshot |
| `90e61a21` | cherry-pick `59a06da7` (PR-3) | chat ref filename + persist merge |
| `89a23b71` | cherry-pick `74368f71` (PR-4) | write_file 二进制黑名单 |
| `a45f41c2` | `fix(win7): cherry-pick office CRUD completion` | **Win7 专项**:`src/App.tsx` 恢复 `/office` route + `Office` import(缺失自 alpha.11);同步默认工具集加入 `office_restore` |
| `613803db` | `fix(win7): restore researcher profile memory_save` | cherry-pick 副作用修复 —— #402 的 cherry-pick -x 把 win7 的 `researcher.tools` 从 5 工具带回到 main 的 4 工具,丢掉了 `memory_save` |

**Win7 专项改动**:

| 文件 | 改动 |
|---|---|
| `src/App.tsx` | +10 -1 — 恢复 `/office` route(缺失自 alpha.11) |
| `backend/agents/profiles.py` | +196 -14 — 同步 primary / writer 默认工具集加入 `office_restore`,修正 `test_profiles_office_tools` 期望 |
| `backend/office/session_workspace.py` | 冲突合并 —— PR-2 的 `get_document_in_workspace_any_status` 与 PR-3 的 `find_document_by_filename` 共存为兄弟函数 |
| (cherry-picked 文件) | 上面 PR-1..4 涉及的所有 backend / 测试文件 |

**py38 兼容**:

| 风险点 | 处理 |
|---|---|
| PEP 604 `X \| None` | 通过 `from __future__ import annotations` 兼容(与 win7 已有的 profiles.py 一致模式) |
| `Optional[X]` / `Dict[X, Y]` | 老 typing 风格直接兼容 |
| PEP 585 泛型基类 runtime | 无 runtime 风险 |

**测试覆盖**(`sage-backend-py38` 环境):

| 套件 | 结果 |
|---|---|
| `pytest backend/tests/unit/` | **4076 passed**(22 min) |
| `ruff check backend/` | All checks passed |
| `npm run typecheck` | TypeScript 编译通过 |

---

## 3. 架构要点

### 3.1 profile 白名单设计

office 工具在不同 profile 里的可见集:

| Profile | office_list | office_read | office_create | office_update | office_delete | office_restore |
|---|---|---|---|---|---|---|
| **primary**(coordinator) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **writer** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| researcher / coder / memory_manager / reviewer | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**设计取舍**:

- **writer 不给 delete** —— writer 是「把资料整理成文档」的角色,删除是用户决策;让 writer 能删会扩大误删面。但 writer 给 restore —— 归档恢复属于「资料整理」范畴。
- **未绑定工作区时 office_list/read 自动隐藏** —— `office_list` / `office_read` 自带 `requires_tool_context=True`,ToolRegistry 在没工作区绑定时自动隐藏。`office_create` / `update` / `delete` / `restore` 没有这个约束,因为它们可以基于用户对话历史(LLM 会问)创建文档。
- **`_OFFICE_CREATE_CAPABILITY_PROMPT`** —— 在 system prompt 里显式声明这些能力,LLM 不需要靠 tool schema 推断。
- **PR-1 (#405) 没挂白名单** —— 这是核心 bug。本系列 PR-1 把白名单补齐,PR-2 顺手把 PR-1 当年漏挂的 create/update/delete/restore 一起加进去,避免再发一个 PR。

### 3.2 archive vs delete 的语义区别

| 维度 | archive | delete |
|---|---|---|
| **数据持久性** | 文件保留,DB 行 `archived_at` 戳时间 | 文件 + DB 行都移除 |
| **list 可见性** | 不可见(过滤 `archived_at IS NULL`) | 不可见(无行) |
| **read 可见性** | 不可见(同 list 过滤) | 不可见(无行) |
| **restore 可恢复** | ✅ —— 还原 archived_at = NULL | ❌ —— 不可恢复 |
| **snapshot 触发** | 不触发 | 不触发 |
| **幂等性** | archive 已 archived 返原 ts,不报错 | delete 已无行返 success 不动行 |
| **LLM 入口** | `office_restore` 不存在 archive 入口 —— 通过 tool prompt 告知 LLM「用 office_delete」还是「告知用户手工管理」(实际 PR-2 只实现了 restore 工具,archive 由用户手动告知 LLM「把这份归档」) | `office_delete` |

> ⚠️ **注意**: 本次实现里 **`office_archive` 工具并未单独实现**。M0 的 `archived_at` 列 + service 层的 `archive_document` / `restore_document` 是为了支撑未来的 `office_archive` 工具入口;现阶段 LLM 通过告知「把它归档」+ 后台手动调度(未实现)的路径并不通畅。**未来需要补 `office_archive` 工具入口,本次 PR-2 只实现了 restore 侧。**

### 3.3 pre-edit snapshot 的存放路径与作用

**触发点**: `OfficeToolService.update()` 成功前,先调 `storage.snapshot_pre_edit()`。

**存放路径**: `<managed_dir>/.snapshots/<ms>-<filename>`

例:`/Users/me/sage-workspace/.snapshots/1725436800123-quarterly-report.docx`

**作用**:

- 每次 `office_update` 成功前把旧版复制到 `.snapshots/`
- 用户/agent 有了「撤销最近一次编辑」路径,与 archive/restore 互不冲突
- archive/restore 是「按文档级别」管理(整文档归档),snapshot 是「按编辑级别」管理(每次编辑留痕)

**失败行为**: snapshot IO 失败不阻挡 edit(best-effort)。用户在测试里覆盖了 `OSError` 吞掉场景(`test_tool_service_archive_restore.py::test_snapshot_io_failure_does_not_block_edit`)。

**不实现**:

- ❌ 不实现结构化版本表(YAGNI;一个 `.snapshots/` 目录够覆盖 MVP"撤销最近一次编辑"需求)
- ❌ 不做 snapshot 生命周期管理 —— 用户/系统责任

### 3.4 chat `@` reference 的双重查找

`authorize_chat_office_request()` 流程:

```
传入: doc_id_or_filename + workspace + declared doc_type
  ↓
[路径 1] doc_id 直接 lookup
  ↓ (命中)
  → 用解析出的 managed UUID 填充 office_doc_scope
  ↓ (未命中)
[路径 2] filename lookup (按 generated_filename + workspace + archived_at IS NULL)
  ↓ (命中)
  → 解析出的 managed UUID 填充 office_doc_scope
  → 校验 doc_type 一致(不一致抛 WorkspacePathMismatchError 400)
  ↓ (未命中)
  → WorkspaceDocumentNotFoundError 404
```

**关键设计**:

- **路径 1 失败不报错** —— 因为可能是路径 2 会命中。失败是正常的 fallback。
- **路径 1 命中后类型校验被跳过** —— 这是有意保留 404 行为以保证向后兼容(id 路径失败模式不变)。
- **路径 2 命中后做类型校验** —— 因为 filename 可能撞名(同一 workspace 不同 doc_type 可能有同名文件,但 office 用 doc_type 区分),所以必须校验。
- **路径 2 失败还是抛 404** —— 而不是 400,保持用户可见的错误语义一致。

### 3.5 `_persist_read_summary` 保留字段的设计

| 字段 | 保留策略 | 理由 |
|---|---|---|
| `archived_at` | **保留**(caller 不传时) | 用户/系统已设置的状态,reader 不应重置 |
| `derived_from` | **保留**(caller 不传时) | 派生 lineage,read 不知道 |
| `original_filename` | **保留**(caller 传 None 时) | 用户上传的原始名,系统内是 managed UUID |
| `created_at` | **保留** | 文档创建时间,read 不会更新 |
| `status` | 走 reader | read 产生新状态(parsing 状态) |
| `updated_at` | 走 reader | re-parse 刷新这个字段是合理的 |
| `metadata` | 走 reader | re-parse 产生新 content facts(包括 `file_size_bytes` via `file_path.stat().st_size`) |

**caller-supplied 覆盖**: 如果 caller 显式传 `original_filename = "X.docx"`,就用 caller 的 —— 这是显式覆盖路径,例如用户改名上传。

### 3.6 write_file 二进制黑名单的扩展名分类

参见 §2.4 表格。

**设计取舍**:

- **早返回,不做 NUL bytes 嗅探** —— write 路径 content 已是 unicode 字符串,嗅探无意义;扩展名预检足够且便宜。
- **白名单放行(`.txt` / `.md` / `.py` 等)** —— 不需要这些在黑名单里,默认走原路径。
- **大小写归一** —— `ext = Path(target).suffix.lower()`,`.PNG` 也会被拦。
- **不实现混淆 / 解码路径** —— 保持 LLM 用专用工具生成二进制(office_create 等)。

---

## 4. 数据流:用户用 chat 调用 office_create → 落 DB + 文件 → chat 引用 → 二次读取

```
┌────────┐                          ┌─────────────┐                    ┌─────────────┐
│  用户   │ "帮我做一份 Q4 销售报告 PPT" │  chat 后端   │                    │  SQLite      │
└───┬────┘                          └──────┬──────┘                    └──────┬──────┘
    │                                     │                                  │
    │ 1. 用户在 chat 里说需求              │                                  │
    ├────────────────────────────────────►│                                  │
    │                                     │                                  │
    │                                     │ 2. primary LLM 看到系统声明      │
    │                                     │    (PROMPT 含 office_create)     │
    │                                     │                                  │
    │                                     │ 3. LLM 调 office_create         │
    │                                     │    {doc_type:"pptx",             │
    │                                     │     output_dir:work_dir,         │
    │                                     │     filename:"Q4-report.pptx",   │
    │                                     │     title:"Q4 销售报告",         │
    │                                     │     outline:[...]}                │
    │                                     │                                  │
    │                                     │ 4. OfficeToolService.create()    │
    │                                     │    ┌─────────────────────┐       │
    │                                     │    │ _coerce_ppt_request │       │
    │                                     │    │ (形状校验, PR-1 修) │       │
    │                                     │    └──────────┬──────────┘       │
    │                                     │               │                  │
    │                                     │    5. storage.insert_document() │
    │                                     ├─────────────────────────────────►│
    │                                     │    {id:<uuid>,                  │
    │                                     │     generated_filename:"<uuid>.pptx",│
    │                                     │     workspace_path:...,         │
    │                                     │     doc_type:"pptx",             │
    │                                     │     status:"generating",         │
    │                                     │     archived_at:NULL,           │
    │                                     │     derived_from:NULL,          │
    │                                     │     original_filename:"Q4-report.pptx"}│
    │                                     │                                  │
    │                                     │ 6. LLM 用 python-pptx 写文件      │
    │                                     │    /work_dir/<uuid>.pptx         │
    │                                     │                                  │
    │                                     │ 7. storage.update_status("ready")│
    │                                     ├─────────────────────────────────►│
    │                                     │                                  │
    │ 8. LLM 回复"报告已生成" + 自动 attach │                                  │
    │◄────────────────────────────────────│                                  │
    │                                     │                                  │
    │ 9. 用户后续消息:"把这份报告的标题改成 XX"│                                  │
    ├────────────────────────────────────►│                                  │
    │                                     │                                  │
    │                                     │ 10. LLM 决定调 office_update    │
    │                                     │     doc_id = <uuid>             │
    │                                     │                                  │
    │                                     │ 11. OfficeToolService.update() │
    │                                     │     a. snapshot_pre_edit()      │
    │                                     │        → /work_dir/.snapshots/  │
    │                                     │          1725436800123-<uuid>.pptx │
    │                                     │     b. 用 python-pptx 改文件     │
    │                                     │     c. _persist_read_summary()  │
    │                                     │        → get_document(老 row)    │
    │                                     │        → 保留 archived_at 等     │
    │                                     │        → INSERT OR REPLACE       │
    │                                     │        (但 archived_at 仍是 NULL)│
    │                                     │                                  │
    │                                     │                                  │
    │ 12. 用户:"@Q4-report.pptx 第二页有问题"│                                  │
    ├────────────────────────────────────►│                                  │
    │                                     │                                  │
    │                                     │ 13. authorize_chat_office_request│
    │                                     │     "Q4-report.pptx" 路径 1 miss  │
    │                                     │     → fallback 到 filename 查找  │
    │                                     │     → 命中 original_filename=   │
    │                                     │       "Q4-report.pptx"          │
    │                                     │     → 解析出的 UUID 填 office_doc_scope │
    │                                     │     (注意:返回的不是 filename)   │
    │                                     │                                  │
    │                                     │ 14. LLM 拿到 office doc context │
    │                                     │     → 用 office_read 看第二页     │
    │                                     │     → 用 office_update 改        │
    │                                     │                                  │
    │ 15. 用户:"把这份归档,下季度再用"     │                                  │
    ├────────────────────────────────────►│                                  │
    │                                     │                                  │
    │                                     │ 16. (本期不实现 office_archive 工具)│
    │                                     │     用户告知 → LLM 无法直接调   │
    │                                     │     → 后续需补 office_archive 工具│
    │                                     │                                  │
    │ 17. 用户:"它不见了!"               │                                  │
    │                                     │                                  │
    │ 18. 用户:"恢复我上季度归档的报告"   │                                  │
    ├────────────────────────────────────►│                                  │
    │                                     │                                  │
    │                                     │ 19. LLM 调 office_restore      │
    │                                     │     doc_id = <uuid>             │
    │                                     │                                  │
    │                                     │ 20. OfficeToolService.restore() │
    │                                     │     → storage.restore_document() │
    │                                     │     → archived_at = NULL        │
    │                                     ├─────────────────────────────────►│
    │                                     │                                  │
    │                                     │                                  │
```

---

## 5. win7 兼容要点

### 5.1 profile 字段名差异

main 与 win7 都用 `backend/agents/profiles.py`,但 win7 的 `_PRIMARY_CURRENT_DEFAULT_TOOLS` 在 PR-1 cherry-pick 后漏挂 `office_restore`(PR-2 才加的,win7 一次性 cherry-pick 时这个 commit 的 win7 副本同步过来就行)。

**冲突解决**:`backend/agents/profiles.py` 有 6 处冲突,primary 合并 office_restore;writer 合并 office_restore(保留 PR-1 "不给 delete" 设计)。

### 5.2 py38 vs py311

| 项目 | 风险点 | win7 处理 |
|---|---|---|
| PEP 604 `X \| None` runtime | Python 3.10+ 才有 | `from __future__ import annotations` 兼容(win7 profiles.py 已用此模式) |
| PEP 585 `list[int]` 等 runtime | Python 3.9+ 才有 | 全部走 `from __future__ import annotations`,无 runtime 风险 |
| `match/case` 语句 | Python 3.10+ 才有 | PR-1..4 代码不用 |
| `dataclasses` slots | Python 3.10+ 才有 kw_only | 不涉及 |

### 5.3 `/office` 路由恢复

`src/App.tsx` 自 alpha.11 起丢失了 `/office` 路由注册(`Office` import 也丢了)。本次 PR-5 一次性恢复:

```tsx
// src/App.tsx
+ import { Office } from './pages/Office';
+ <Route path="/office" element={<Office />} />
```

### 5.4 cherry-pick 的取舍

| 取舍点 | 决策 |
|---|---|
| main 未合并的 PR,win7 直接 cherry-pick | ✅ 跟随 main 设计方向,但要求 PR 4xx 测试全绿 |
| cherry-pick -x 加 commit message 引用 | ✅ 保留溯源链 |
| `6d7646ee` audit fix 在三个 PR 都重复 cherry-pick | 只 cherry-pick 一次(取最早引用方,后续 PR 不重复) |
| `613803db` cherry-pick 副作用修复 | 必须;不然 win7 researcher 失去 memory_save,test_researcher_profile_has_memory_tools 失败 |
| `release/win7` 与 `main` 的 `requirements.txt` | 严格隔离,不动 main 上的 `requirements.txt` |

---

## 6. 测试矩阵

| PR | 测试文件 | 新增 case | 状态 |
|---|---|---|---|
| #412 | `tests/unit/test_profiles_legacy_tool_rename.py` | 6 | PASS |
| #412 | `tests/unit/test_profiles_office_tools.py` | 8 | PASS |
| #412 | `tests/unit/test_profiles_subset_migration.py` | 11 | PASS |
| #412 | `tests/unit/office/test_tool_service.py` | (扩展 PPT shape cases) | PASS |
| #414 | `tests/unit/office/test_storage_snapshot.py` | 13 | PASS |
| #414 | `tests/unit/office/test_tool_service_archive_restore.py` | 12 | PASS |
| #415 | `tests/unit/office/test_chat_refs_filename_lookup.py` | 7 | PASS |
| #415 | `tests/unit/office/test_persist_read_summary_merge.py` | 5 | PASS |
| #416 | `tests/unit/test_write_file_binary_guard.py` | 9 | PASS |
| #417 | (cherry-pick,全部跑通) | — | py38 4076 passed(22 min) |

**整体回归**:

| 套件 | 数量 | 状态 |
|---|---|---|
| backend office 单测(`tests/unit/office`) | 295 | PASS |
| backend office 集成测试(`tests/integration/test_*office*`) | 28 | PASS |
| backend profiles / agents 单测 | 454 | PASS |
| backend file_tool + edit_tool | 90 | PASS |
| backend 全套单测(py38,win7) | 4076 | PASS |

---

## 7. 回滚指南

> ⚠️ 5 个 PR 状态:**截至 2026-09-04,所有 PR 仍 OPEN(未 merge)**。
> 本节假设 PR 已 merge 到目标分支。

### 7.1 main 上的 PR-1..4 (#412, #414, #415, #416)

每个 PR 都有独立 squash merge commit(待合时)。revert 流程:

```bash
# 1. 找到 squash commit hash(在 main 上 git log --grep="PR-N")
git log main --oneline --grep="office" | head -20

# 2. revert(假设 PR-1 的 squash commit 是 abc1234)
git revert --no-edit abc1234

# 3. 验证
pytest backend/tests/unit/ -k "office or profiles"
```

**注意**: 如果某个 PR 已被下游 PR 依赖(例如 PR-2 假设 PR-1 的 profile 白名单已落地),单独 revert PR-1 会破坏 PR-2。回滚顺序:**先 revert 后合的,再 revert 先合的**(后进先出)。

### 7.2 win7 上的 PR-5 (#417)

PR-5 是 squash 的多个 cherry-pick commit + win7 专项(`a45f41c2`)+ 副作用修复(`613803db`)。

```bash
# 1. 在 release/win7 上找 PR-5 squash commit
git log release/win7 --oneline --grep="cherry-pick office CRUD"

# 2. revert
git revert --no-edit <squash-commit>

# 3. 注意:win7 还会丢失 /office 路由,需要手工恢复
git revert --no-edit <a45f41c2-original-commit-on-win7>

# 4. 验证 py38 测试
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/
```

### 7.3 已知回滚陷阱

| 陷阱 | 表现 | 修复 |
|---|---|---|
| **PR-2 假设 PR-1 白名单已就位** | revert PR-1 后 PR-2 涉及的工具白名单常量会指向不存在的工具 | revert PR-2 再 revert PR-1 |
| **PR-3 修改 _persist_read_summary** | revert 后 re-read 会重新激活 archived 文档 | 同时 revert PR-2(archive)和 PR-3(persist) |
| **PR-4 是纯工具防护** | 可独立 revert,但 revert 后 LLM 重新能写损坏二进制 | 无陷阱 |
| **PR-5 依赖 PR-1..4** | cherry-pick 是 squash,revert 必须整批 | revert 整个 squash commit,不要试图拆 |

---

## 8. 已知限制

| # | 限制 | 影响 | 后续工作 |
|---|---|---|---|
| **L1** | `office_archive` 工具入口未实现 —— M0 有 `archived_at` 列 + service 层 `archive_document`,但 LLM 没有对应工具 | 用户告知"归档"后,LLM 无法直接调;必须用户手动告知 restore 路径,或 LLM 用 office_delete 替代(不可逆) | 后续 PR:补 `office_archive` 工具,挂在 primary + writer 白名单 |
| **L2** | `_OFFICE_CREATE_CAPABILITY_PROMPT` 只覆盖了 archive/restore/snapshot 三段,未描述 archive 入口缺失 | LLM 不知道「告诉用户归档后无法直接恢复」(因为没工具) | 待 L1 解决后,同步更新 prompt |
| **L3** | `snapshot_pre_edit` 没有生命周期清理 | 长期使用会导致 `.snapshots/` 累积 | 后续 PR:加 retention 策略(30 天或 N 个版本) |
| **L4** | `_BINARY_WRITE_BLACKLIST` 是静态列表,新出现的格式(例如 `.parquet` / `.arrow` / `.webp` 子格式)不会自动覆盖 | LLM 用 write_file 写新格式时会静默失败 | 后续 PR:从 `python-magic` / 文件头嗅探动态判定,黑名单只作为 fast-path |
| **L5** | archive / restore / snapshot 都没有 win7 专项 E2E | win7 真实 GUI 上未验证 | win7 release 前需在真机跑 office 流程 |
| **L6** | `_persist_read_summary` 合并策略对 caller-supplied 字段语义没有完整文档 | 调用方需要猜哪些字段覆盖有效 | 待 office_routes.py 顶部 docstring 补充 |
| **L7** | PR-5 win7 cherry-pick 是手工 squash,未保留每个原始 commit 的 `cherry-picked from` 全部元数据 | 审计链弱化,但 `git log -x` 仍可追 | 待 release/win7 仓库完成 squash 后单独审计 |
| **L8** | `chat_refs.find_document_by_filename` 用精确等值匹配 | 拼写错误 / 大小写差异都会 miss | YAGNI 决策;后续如需要可加 normalized 索引 |
| **L9** | archive / restore 都是 doc_id 模式,没有 file_path 模式 | LLM 必须先 office_list 拿 doc_id 才能操作 | 与 office_delete / update 一致设计;不视为限制 |
| **L10** | `write_file` 二进制黑名单大小写不敏感 | 已经 `.lower()` 归一 | 不视为限制 |

---

## 9. 相关文档

- [33-office-m1-m2-completion.md](./33-office-m1-m2-completion.md) —— Office M1-M2 完整收尾(本系列的前置)
- [47-git-worktree-workflow.md](./47-git-worktree-workflow.md) —— 并行开发基础设施(本系列是首个跨 main+win7 双分支并行 cherry-pick 的实战案例)
- [30-release-tiers.md](./30-release-tiers.md) —— Release Tiers(main + win7 LTS 派生)
- [31-win7-lts.md](./31-win7-lts.md) —— Win7 LTS 维护策略
- 用户手册: [`../user-manual/09-office.md`](../user-manual/09-office.md)
- PR 链接:#405 / #412 / #414 / #415 / #416 / #417
- 设计 spec: `docs/superpowers/specs/2026-09-04-office-crud-completion-design.md`
- 实施计划: `docs/superpowers/plans/2026-09-04-office-crud-completion.md`