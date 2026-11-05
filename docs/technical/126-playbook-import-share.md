# Playbook 文档导入与分享链接

> 日期：2026-11-03
> 状态：已实施（M2 文档导入 / M3 分享链接）
> 计划：`docs/plans/2026-11-03_playbook-import-ux.md`
> 相关：`docs/technical/115-project-playbook.md`（Playbook 核心机制）

## 1. 目标

补齐 Playbook 的两条"入口/出口"链路：

- **入口**：用户手里已有 Word/PDF/Markdown 格式的规范文件（申报指南、质量管理体系文档），
  需要一键转成可用的 Playbook，而不是手写 JSON。
- **出口**：形成可用的一套规程后，需要通过链接分享给同事，而不是传文件。

同时消除 L1/L2/L3/L4 内部层级代号对用户的暴露（术语去技术化）。

## 2. 链路总览

```
                        ┌──────────────────────────────────────┐
  Word/PDF/MD/PPTX ────▶│ POST /playbooks/import/document      │
                        │   base64 → 解析文本 → LLM/确定性草案  │
                        │   （只返回预览，不写库）               │
                        └──────────────┬───────────────────────┘
                                       │ 预览（PlaybookSpec）
                          用户确认 ◀───┴───▶ PUT /projects/{id}/playbook
                                                      │ 绑定快照
                                                       ▼
                                              project_playbooks

  规程库条目 ──▶ POST /playbooks/library/{id}/share ──▶ token
                    │
                    ▼
              GET /playbooks/shared/{token} ──▶ 只读 PlaybookSpec
                    │
                    ▼
              /share/playbook/{token}（前端落地页）
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  导入并绑定项目           仅保存到规程库
```

## 3. 文档导入（M2）

### 3.1 服务层

`backend/services/playbook_document_import.py`：

- `import_playbook_from_document(file_path, filename, *, use_llm=True, llm_client=None)`
  → `DocumentImportResult(playbook, source_doc, rationale, llm_available, source)`。
- 文本抽取复用 `backend/wiki/file_parser.parse_document()`（支持 `.docx` / `.pdf` /
  `.md` / `.pptx` / `.xlsx` / `.html` / `.txt`）。
- **确定性解析**（`_build_deterministic_playbook`）作为降级基线：
  - 阶段：`1. xxx` / `一、xxx` / `Phase 1: xxx` 等 5 类正则，识别 1–8 个阶段；
  - 产物：出现「产物 / 交付物 / 输出 / 成果 / deliverable」小节后的列表项；
  - 规则：出现「规则 / 规范 / 要求 / rule / constraint」小节后的列表项。
- **LLM 路径**：`_build_prompt` 组装抽取提示词，`client.complete()` 返回 JSON，
  `normalize_playbook()` 校验；任一环节异常 → 落回确定性草案，`source="deterministic"`。

### 3.2 API

`POST /api/v1/playbooks/import/document`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `filename` | str | 原始文件名，决定格式判定与规程名 |
| `content_base64` | str | 文件内容 base64 |
| `project_id` | str? | 可选，传入则校验项目存在 |
| `use_llm` | bool | 默认 `true`；`false` 强制走确定性路径 |

响应：`{playbook, source_doc, rationale, llm_available, source}`。

错误：base64 解码失败 → 400；空内容 → 400；扩展名不在白名单 → 400；解析异常 → 500。

**该端点不写库**——只产出预览。落库由前端确认后调用既有
`PUT /api/v1/projects/{id}/playbook`（`spec` 三选一之一）。

### 3.3 前端

- `src/features/playbook/PlaybookDocumentImportDialog.tsx`：文件选择 → 解析 →
  阶段/产物/规则预览 → 「确认并绑定」。入口挂在 `PlaybookToolbar.tsx`。
- `src/shared/api/playbookApi.ts::documentImport()` →
  `playbook_import_document` IPC → `electron/commandRoutes/playbooks.ts`。

## 4. 分享链接（M3）

### 4.1 数据模型

```sql
CREATE TABLE playbook_shares (
  id TEXT PRIMARY KEY,
  playbook_id TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  expires_at INTEGER NOT NULL,   -- epoch 毫秒
  created_at INTEGER NOT NULL    -- epoch 毫秒
);
```

- token 由 `secrets.token_urlsafe(16)` 生成（128 bit 熵）。
- 默认有效期 7 天（`DEFAULT_EXPIRY_DAYS`），可在请求里覆盖。
- 判定过期用 `now_ms >= expires_at`（含边界等值）。

### 4.2 服务与仓库

- `backend/data/playbook_share_repo.py`：`PlaybookShareRepository.create/get_by_token/delete`。
- `backend/services/playbook_share.py`：
  - `create_share_link(library_id, *, expiry_days=7)` → token + `share_url`
    （`/share/playbook/{token}`）；
  - `resolve_share_token(token)` → 只读 payload（`playbook_id` / `playbook_name` /
    `spec` / `shared_at` / `expires_at`）。
  - 异常：`ShareTokenInvalidError`（未知 token）、`ShareTokenExpiredError`（过期）、
    `PlaybookNotFoundError`（规程库条目已删）。

### 4.3 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/playbooks/library/{library_id}/share` | body `{expiry_days}`；库条目不存在 → 404 `playbook_not_found` |
| GET | `/api/v1/playbooks/shared/{token}` | 过期 → 410 `share_expired`；未知 → 404 `share_invalid`；库条目已删 → 404 `playbook_not_found` |

### 4.4 前端

- `src/features/playbook/PlaybookShareDialog.tsx`：生成链接 + 一键复制。
  前端使用 **HashRouter**，故展示与复制的都是绝对地址
  `{origin}/#/share/playbook/{token}`（由 `absoluteUrl()` 统一转换）。
- `src/pages/PlaybookSharePage.tsx`：落地页。预览阶段/产物/规则，两个出口：
  - **导入并绑定项目**：`playbookApi.bind(projectId, {spec, source: 'shared-link'})`；
  - **仅保存到规程库**：`playbookApi.saveLibrary(envelope, 'shared')`，
    envelope 必须是 `{format: 'sage.playbook', playbook: spec, scaffold: {...}}`
    （`validate_import_envelope` 校验 `format`）。
- 路由 `/share/playbook/:token` 挂在 `src/App.tsx` 的 `<Layout>` **之外**，
  接收方无需先进入工作台；i18n 由 `main.tsx` → `AppProviders` 全局提供。

## 5. 术语去技术化（M1）

- `ProjectAdvisorCard.tsx` 及 14 个 `.tsx` 文件中，"L1/L2/L3/L4"全部替换为业务语义描述，
  "约束"统一改为"规则"。
- 新增文案一律走 i18n（`src/shared/lib/i18n/locales/{zh,en}/playbook.ts`），
  zh 为类型源（`PlaybookTranslationKey = keyof typeof zhPlaybook`），en 必须逐键同步。

## 6. 安全与隐私

- 分享链接是**只读**能力：token 只允许读取规程 spec，不能写库、不能列出其他条目。
- token 只经链接分发；落在浏览器历史/剪贴板属预期风险，不承诺一次性语义。
- 分享链接过期后失效，但**不会**自动删除底层规程库条目——分享方删除条目后，
  接收方拿到的是 404 `playbook_not_found`。
- 文档解析在后端本地完成，文件内容不上传第三方；启用 LLM 时仅把抽取文本送入模型
  （见 `_build_prompt` 的 `MAX_DOCUMENT_TEXT` 截断）。

## 7. 双分支注意

- main 与 `release/win7` 均在开发，功能应保持对齐；同步一律用 cherry-pick。
- 后端代码统一 `Optional[...]` 而非 PEP 604 `X | None`，
  `scripts/check_py38_compat.py` 会 AST 扫描拦截。
- 本文档在 main 为 §126；同步到 win7 时需确认该分支已用编号，选不冲突的下一个号

## 8. 测试

| 文件 | 覆盖 |
| --- | --- |
| `backend/tests/unit/test_playbook_document_import.py` | 文档解析服务单测（阶段/产物/规则抽取、降级） |
| `backend/tests/unit/test_playbook_share.py` | share repo/service：创建、解析、过期、未知 token、库条目删除、token 唯一性 |
| `backend/tests/integration/test_playbook_import_share.py` | 两条端到端链路：Word 上传→预览→确认→绑定；生成分享链接→访问→导入 |
| `src/features/playbook/__tests__/PlaybookShareDialog.test.tsx` | 分享弹窗：绝对链接、缺参不发请求、失败提示 |
| `src/pages/__tests__/PlaybookSharePage.test.tsx` | 落地页：预览、无效链接、导入绑定、保存到规程库 |

前端 jsdom 提示：Radix Select 依赖 `hasPointerCapture` / `releasePointerCapture` /
`setPointerCapture` / `scrollIntoView` 与 `window.PointerEvent`，测试需打桩后用
`fireEvent.pointerDown(trigger)` 打开、`fireEvent.click(option)` 选择。

## 9. 已知限制

- 确定性解析只认章节式编号列表，散文体规范文件解析出的阶段可能为空
  （此时回退为单个"实施"阶段）。
- 分享链接不支持手动吊销单个 token（吊销需删除规程库条目），
  也不支持自定义有效期上限。
- 分享落地页只能导入到**当前用户本机**已有的项目，不做跨设备同步。
