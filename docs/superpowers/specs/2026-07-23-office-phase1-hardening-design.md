# Office Phase 1 生产加固设计

> **状态：** 已 superseded，不得作为实施依据
> **替代设计：** `docs/superpowers/specs/2026-07-23-office-chat-native-crud-design.md`
> **日期：** 2026-07-23
> **目标分支：** `main`
> **实施分支：** `fix/office-phase1-hardening`
> **关联计划：** `docs/plans/2026-07-16_office-features.md`
> **后续分支：** `release/win7` 仅在 main 合并验证后通过独立 cherry-pick PR 同步

## 1. 背景

Office Phase 1 已通过 PR #183 和 PR #184 合入 main，提供 `/office` 页面、PPTX/DOCX/XLSX 读取、基础生成、历史列表和 Electron IPC 骨架。静态审计发现该实现尚不能作为正式可用能力发布：

1. Python 路径 containment 使用硬编码 `/`，Windows 上合法 Workspace 子路径会被拒绝；
2. 正式 Windows bundle 的 `requirements-bundled.txt` 缺少 Office 运行依赖；
3. 文件选择器允许 `.ppt/.doc/.xls` 和 All Files，但 reader 只支持 OOXML；
4. “导入”只传递外部绝对路径，没有复制、持久化或失败清理；
5. read endpoint 返回 summary，但没有保存到 SQLite；
6. Save As dialog 已暴露但没有调用者，也没有打开文件或定位目录入口；
7. 删除先删数据库后删文件，文件锁失败时会留下失去记录的托管文件；
8. Office 单元测试位于 `backend/office/__tests__/`，不在 `backend/pytest.ini` 的 `testpaths=tests` 下，默认 CI 不收集；
9. Office API 对确定性错误和有副作用的 generate/delete 统一重试，可能造成延迟或重复生成。

本设计只加固 Phase 1。编辑现有文档、LLM tool、Round-trip、模板和图表仍属于原计划 Phase 2/3。

## 2. 能力声明

加固完成后，用户可以从 Workspace 外选择或拖入 `.pptx/.docx/.xlsx`，Sage 会保留外部源文件不变，把副本导入 Workspace 托管目录，解析并显示简化预览，同时写入历史。用户也可以生成基础 OOXML 文件，并对托管文件执行打开、定位、另存为和经确认的删除。

本能力不承诺 Office 原貌渲染、复杂格式保真、现有文件编辑、自然语言问答或格式转换。

## 3. 已确认决策

| 决策 | 结果 |
|---|---|
| 导入语义 | 外部文件复制到 Workspace 托管目录，源文件永不修改或删除 |
| 保存模型 | 生成结果保留 Workspace 托管主副本；Save As 仅复制到用户路径 |
| 删除语义 | 明确确认后删除托管文件和 DB 记录；先删文件，再删记录 |
| 总体架构 | Electron 文件网关负责用户授权的文件副作用，Python 后端负责解析、生成、元数据和安全删除 |
| 旧格式 | 仅支持 `.pptx/.docx/.xlsx`，移除 `.ppt/.doc/.xls` 和 All Files |
| Win7 | 本次只修 main；main 合并验证后另开 Win7 PR |
| pandas | 当前代码未使用，不加入 bundled requirements；真正引入 DataFrame 能力时再单独评估 |

## 4. 范围

### 4.1 本次范围

- 修复 Windows/POSIX 路径 containment；
- 建立 Electron Office 文件网关；
- 实现真实导入、失败清理和读取历史持久化；
- 接通 Save As、打开文件和打开所在目录；
- 修正删除顺序、语义、文案和确认流程；
- 将 Office tests 纳入默认 pytest/CI；
- 增加 Backend、Electron、React、contract 和 Playwright 覆盖；
- 补齐 Windows bundle 所需 Office 运行依赖；
- 增加 Windows 路径和 bundle 依赖 canary；
- 完成 Office Phase 1 技术文档和用户手册。

### 4.2 非目标

- 编辑现有 PPTX/DOCX/XLSX；
- LLM/Agent Office tool 或 `/office` slash command；
- Office 原貌渲染；
- PDF 或其他格式转换；
- `.ppt/.doc/.xls` 旧二进制格式；
- `.pptm/.docm/.xlsm` 宏保留承诺；
- CSV、ODF；
- COM、MS Office、LibreOffice、OnlyOffice 或 OfficeCLI 集成；
- Phase 2/3 的模板、图表、缓存或大文件流式处理；
- 在本分支修改 `backend/requirements-py38.txt` 或直接同步 `release/win7`。

## 5. 架构

### 5.1 职责边界

| 层 | 模块 | 职责 |
|---|---|---|
| Electron 文件网关 | `electron/officeIpc.ts` 及纯辅助模块 | 原生选择、导入复制、Save As、打开、定位、失败清理、路径与扩展名验证 |
| Renderer bridge | `electron/preload.ts`、`src/shared/types/electron-api.d.ts` | 暴露强类型 Office 文件动作，不暴露任意 shell 命令 |
| React feature | `src/pages/Office.tsx`、`src/features/office/*` | 编排导入→读取→刷新、历史动作、确认对话框和用户提示 |
| Typed API | `src/shared/api/officeApi.ts`、`types.ts` | Backend read/generate/list/delete 契约；控制重试策略 |
| Backend path safety | `backend/office/path_safety.py` | 标准库实现的跨平台 canonicalization 与 component-aware containment |
| Backend storage | `backend/office/storage.py` | 托管目录、SQLite 映射、文档路径重构 |
| Backend routes | `backend/api/office_routes.py` | 托管路径验证、大小/类型验证、解析持久化和安全删除 |
| Format adapters | `backend/office/ppt.py`、`word.py`、`excel.py` | OOXML 读取和基础生成，不处理 HTTP 或原生 dialog |

### 5.2 托管目录不变量

所有 UI 可操作的 Office 主副本必须符合：

```text
<canonical-workspace>/office/<doc-type>/<document-id>/<filename>
```

约束：

- `doc-type` 只能是 `ppt|word|excel`；
- `document-id` 必须满足现有 `_DOC_ID_PATTERN`；
- `filename` 必须是 basename，不能包含 `/`、`\`、`.`/`..` 路径语义；
- 文件扩展名必须与 `doc-type` 匹配；
- resolve symlink 后仍必须位于 canonical Workspace 内；
- SQLite `OfficeDocumentSummary.id` 必须等于 `<document-id>` 目录名；
- `generated_filename` 表示托管主副本文件名，导入和生成都使用该字段；
- `original_filename` 仅表示外部导入时用户看到的源文件名，不能用于路径重构。

### 5.3 路径安全实现

新增标准库模块 `backend/office/path_safety.py`，提供独立、可测试的路径 primitive：

- canonical Workspace validation；
- `relative_to()`/`try-except` containment，不使用字符串前缀；
- 托管路径解析和结构验证；
- 托管文件路径重构；
- symlink escape 检测。

实现采用 Python 3.8 可用语法，方便后续 byte-for-byte cherry-pick；本次仍只在 main 的 Python 3.11 环境验证和提交。

Electron 侧使用 `path.resolve()` + `path.relative()` 实现同等 component-aware 校验，并对 Windows `path.win32` 契约单测。两侧实现相同不变量，但不共享运行时代码。

## 6. 接口契约

### 6.1 Electron bridge 类型

```typescript
export interface OfficeManagedDocumentRef {
  workspacePath: string;
  docType: OfficeDocType;
  documentId: string;
  filename: string;
}

export interface ImportedOfficeFile extends OfficeManagedDocumentRef {
  managedPath: string;
  originalName: string;
  sizeBytes: number;
  importToken: string;
}

export interface OfficeSaveAsResult {
  savedPath: string;
}
```

Renderer bridge 提供：

```typescript
pickAndImportOfficeFile(
  workspacePath: string,
  docType: OfficeDocType,
): Promise<ImportedOfficeFile | null>

importDroppedOfficeFile(
  workspacePath: string,
  docType: OfficeDocType,
  sourcePath: string,
): Promise<ImportedOfficeFile>

completeOfficeImport(importToken: string): Promise<void>
discardOfficeImport(importToken: string): Promise<void>

saveOfficeDocumentAs(
  ref: OfficeManagedDocumentRef,
): Promise<OfficeSaveAsResult | null>

openOfficeDocument(ref: OfficeManagedDocumentRef): Promise<void>
showOfficeDocumentInFolder(ref: OfficeManagedDocumentRef): Promise<void>
```

`importToken` 是 Electron 生成的不可预测一次性 token。Electron 仅在内存中保存 `token → pending managed ref` 映射：

- import 成功复制后创建 pending token；
- parse 和 DB 持久化成功后，Renderer 调用 `completeOfficeImport()` 使 token 失效；
- parse 失败时，Renderer 只能用仍处于 pending 状态的 token 调用 `discardOfficeImport()`；
- token 不能删除已 complete 的文档，也不能指定任意路径；
- Electron 重启后 pending map 丢失，旧 token 自动失效，不执行清理；
- pending token 定时失效时只移除授权，不自动删除文件，避免后台误删。

所有 public API 使用显式参数和返回类型，不使用 `any`。

### 6.2 Backend read request

在现有 `OfficeReadRequest` 增加：

```python
original_filename: Optional[str] = Field(default=None, min_length=1, max_length=255)
```

该字段只写入 summary，不参与文件访问。

read endpoint 从经过验证的托管路径取得 `document_id` 和 `generated_filename`，显式传给 reader。reader 返回的 summary 随结果一起返回，并由 route 调用 `save_document()` 持久化。

### 6.3 数据库

现有 `office_documents` 表字段足够，不新增 migration。

读入文件：

- `id`: 托管 UUID 目录名；
- `status`: `parsed`；
- `original_filename`: 外部源文件名；
- `generated_filename`: Workspace 托管副本名。

生成文件：

- `id`: generator 创建的 UUID 目录名；
- `status`: `generated`；
- `original_filename`: `NULL`；
- `generated_filename`: 托管文件名。

Save As 外部副本不写入第二条记录。

## 7. 生命周期

### 7.1 选择并导入

```text
用户选择或拖入文件
→ Electron 验证源文件
→ 创建 UUID 托管目录
→ COPYFILE_EXCL 复制源文件
→ 创建 pending import token
→ 返回 ImportedOfficeFile
→ Renderer 调用对应 read API
→ Backend 验证托管结构、大小和类型
→ reader 解析并构造 summary
→ route save_document(summary)
→ Renderer 调用 completeOfficeImport(token)
→ Renderer refresh()
→ 显示预览和历史记录
```

Electron 复制时：

- 不覆盖已有文件；
- 不移动或删除源文件；
- 复制失败时清理刚创建的空目录；
- 文件选择对话框只显示对应现代 OOXML 格式，不附加 All Files；
- pending token 只授权完成或清理本次新导入的 UUID 目录。

### 7.2 解析失败恢复

若 copy 成功但 parse 失败：

1. Renderer 保留原始解析错误；
2. 调用 `discardOfficeImport(importToken)`；
3. Electron 从 pending map 取得托管引用，重新验证后删除该 UUID 目录；
4. token 立即失效，不能重复清理；
5. 清理成功后显示解析错误；
6. 清理失败时在原错误后追加残留路径提示，并写详细日志。

该补偿不是数据库事务。parse 与 DB 持久化成功后必须先调用 `completeOfficeImport(importToken)`，使 Electron 不再接受针对该文档的 discard。

### 7.3 生成

保留现有三个 generate endpoint 和托管目录布局。成功生成后：

- route 保存 `generated` summary；
- Renderer 刷新历史；
- 结果面板和历史项均可执行打开、定位和 Save As。

read、generate、delete 不进行自动重试。`listDocuments` 仅对明确的瞬时连接失败做有限重试。

### 7.4 Save As

```text
用户点击另存为
→ Electron 根据 managed ref 重构并验证源路径
→ showSaveDialog（带正确扩展名过滤器和建议名称）
→ 用户取消：返回 null，无错误 toast
→ 用户确认：copyFile 到目标路径
→ 返回 savedPath，显示成功提示
```

Save As 不移动托管文件、不修改 DB 记录、不新增历史项。目标与源解析为同一路径时视为已保存，不覆盖自身。

### 7.5 打开和定位

- `openOfficeDocument` 使用 `shell.openPath()`；返回非空错误字符串时抛出明确错误；
- `showOfficeDocumentInFolder` 使用 `shell.showItemInFolder()`；
- 两个动作只能接受合法 managed ref；
- 不使用 shell command，不拼接命令字符串。

### 7.6 删除

```text
用户点击删除
→ React 确认对话框明确说明会删除 Workspace 托管副本
→ 用户确认
→ DELETE /office/documents/{id}
→ Backend 查询记录
→ 重构并验证托管目录
→ 删除目录（目录已不存在视为文件清理完成）
→ 删除 SQLite 记录
→ Renderer 移除历史项
```

规则：

- 外部导入源文件永不删除；
- 文件删除失败时不删除 DB 记录；
- 文件被占用时提示用户关闭 Office 应用后重试；
- DB 删除失败可能留下指向已删除文件的记录，该状态可通过重试删除恢复，且比无记录孤儿文件更可诊断；
- React 仅在 API 成功后确认移除，或使用现有 optimistic update + rollback 保证失败恢复。

## 8. 错误处理

### 8.1 用户可见错误

| 场景 | 用户提示 |
|---|---|
| 不支持格式 | 仅支持 `.pptx`、`.docx` 和 `.xlsx` |
| 类型不匹配 | 请选择与当前文档类型匹配的文件 |
| 文件消失 | 源文件不存在，请重新选择 |
| 文件超过上限 | 文件超过 50 MB 上限 |
| 文件损坏 | 文件无法解析，可能已损坏或格式不匹配 |
| Workspace 无效 | 工作区不可用，请重新选择 |
| 文件被占用 | 请关闭 Word、Excel 或 PowerPoint 后重试 |
| 无默认打开程序 | 系统没有可打开该格式的应用 |
| Save As 取消 | 静默结束 |
| 导入清理失败 | 显示主错误，并告知残留托管路径 |

UI 不直接显示 HTTP URL、原始 JSON 或内部 stack。完整上下文写入既有 Electron/backend logger。

### 8.2 重试策略

- `read`: 不自动重试；
- `generate`: 不自动重试，避免重复 UUID 文件；
- `delete`: 不自动重试；
- Electron 文件动作：不自动重试；
- `listDocuments`: 只对可识别的瞬时连接错误有限重试；
- 400/404/413/422 等确定性错误不重试。

## 9. 依赖与打包

在 `backend/requirements-bundled.txt` 加入与 `backend/requirements.txt` 一致的实际运行依赖：

```text
python-pptx==0.6.23
python-docx==1.1.2
openpyxl==3.1.5
```

不加入 pandas/numpy，因为当前 Office runtime 没有 import 或 DataFrame 逻辑。修正 `excel.py` 中声称使用 pandas 的失真注释；保留未来 Phase 2/3 独立引入的可能。

正式 bundle 继续使用现有 `import backend.main` canary。新增 contract test 读取 bundled requirements，防止三个包再次遗漏，并验证 distribution name 与 import name映射：

| Distribution | Import |
|---|---|
| `python-pptx` | `pptx` |
| `python-docx` | `docx` |
| `openpyxl` | `openpyxl` |

本次不修改 `backend/requirements-py38.txt`。

## 10. 测试与 CI

### 10.1 Backend

把现有 Office tests 从：

```text
backend/office/__tests__/
```

迁到：

```text
backend/tests/unit/office/
```

使现有 `backend/pytest.ini` 的 `testpaths=tests` 自动收集。

新增测试：

- `test_path_safety.py`
  - 合法 POSIX 与 Windows 路径；
  - sibling-prefix；
  - `..`；
  - symlink escape；
  - 非法 doc ID 和 filename；
  - 托管路径重构；
- route integration
  - PPT/Word/Excel read 后写入历史；
  - document ID 与目录 UUID 一致；
  - 50 MB 限制；
  - 错误扩展名和损坏 OOXML；
  - 删除成功；
  - 文件删除失败时记录保留；
- bundled requirements contract
  - 三个 distribution 存在；
  - 版本与开发 requirements 一致；
  - import 名映射存在。

Office Backend 关键模块覆盖率不得低于 80%。

### 10.2 Electron

为纯文件网关和 IPC registration 增加测试：

- 过滤器只含现代 OOXML；
- native dialog 取消；
- pick + copy + pending import token；
- drag-drop copy；
- complete 后 token 失效；
- discard 只能清理 pending token 对应目录且只能执行一次；
- forged/expired token 拒绝；
- copy 冲突与失败清理；
- 50 MB 拒绝；
- Save As 成功、取消和同路径；
- `openPath` 成功和错误；
- show in folder；
- forged managed ref、traversal 和 sibling-prefix 拒绝；
- Windows `path.win32` containment。

### 10.3 React/TypeScript

新增或补齐：

- `officeApi` 参数映射和无副作用重试策略；
- `useOfficeDocuments` 导入→读取→刷新；
- parse 失败→discard；
- `OfficeFilePicker` 选择、拖放和格式错误；
- `OfficeDocumentList` 打开、定位、Save As 和删除确认；
- 删除取消、成功和 rollback；
- 生成成功后的动作入口。

### 10.4 E2E

新增 Playwright Office Phase 1 流程，使用可控 Electron bridge mock 验证：

```text
选择 Workspace
→ 导入文件
→ 显示预览
→ 历史出现记录
→ Save As
→ 打开/定位动作
→ 删除确认
```

真实文件系统、SQLite 和解析器由 Backend integration + Electron tests 覆盖；UI E2E 不伪装验证真实 OOXML 解析。

### 10.5 CI 门禁

- 迁移后的 Office pytest 自动进入现有 Backend job；
- 现有 Windows Electron build job执行轻量 Office path canary；
- bundled requirements contract 进入 Backend CI；
- release bundler 的 `import backend.main` 作为最终 bundle canary；
- Frontend TypeScript、Vitest、Electron tests、Playwright Office flow 全绿；
- 不新增依赖于 `release/win7` 的 CI 操作。

## 11. 文档

实现完成后：

1. 新增或更新 Office 技术章节，记录架构、支持格式、托管目录、信任边界、打包依赖和测试门禁；
2. 新增 Office 用户手册，说明导入、预览、生成、Save As、打开、删除、50 MB 上限和简化预览边界；
3. 更新技术手册和用户手册 README 章节目录；
4. 更新 `docs/plans/2026-07-16_office-features.md`：Phase 1 标为完成，Phase 2/3 保持未完成，并纠正 Win7 同步承诺；
5. 本次 implementation plan 完成并合入正式手册后删除；
6. 本设计 spec 保留，作为设计与实现对比基线。

## 12. 预计修改文件

### Backend

- `backend/office/path_safety.py`（新）
- `backend/office/storage.py`
- `backend/office/models.py`
- `backend/office/ppt.py`
- `backend/office/word.py`
- `backend/office/excel.py`
- `backend/api/office_routes.py`
- `backend/requirements-bundled.txt`
- `backend/tests/unit/office/*`
- `backend/tests/integration/test_office_routes.py`（新）
- `backend/tests/contract/test_office_bundled_requirements.py`（新）

### Electron / Renderer

- `electron/officeIpc.ts`
- `electron/officePaths.ts`（新）
- `electron/preload.ts`
- `electron/main.ts`（仅注册/依赖注入需要时）
- `electron/__tests__/officeIpc.test.ts`（新）
- `electron/__tests__/officePaths.test.ts`（新）
- `src/shared/types/electron-api.d.ts`
- `src/shared/api/types.ts`
- `src/shared/api/officeApi.ts`
- `src/features/office/useOfficeDocuments.ts`
- `src/features/office/OfficeFilePicker.tsx`
- `src/features/office/OfficeDocumentList.tsx`
- `src/features/office/OfficeDeleteConfirmDialog.tsx`（新）
- `src/features/office/OfficeGenerateForm.tsx`
- `src/pages/Office.tsx`
- 对应 Vitest 与 Playwright tests

### CI / Docs

- `.github/workflows/ci.yml`
- `docs/technical/33-office-phase1.md`（新）
- `docs/technical/README.md`
- `docs/user-manual/07-office.md`（新）
- `docs/user-manual/README.md`
- `docs/plans/2026-07-16_office-features.md`

最终文件名与最小改动范围由实施计划在代码探索后锁定；不得扩大到 Phase 2/3。

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Electron 和 Python 路径规则漂移 | 相同 fixture 契约；两侧覆盖 Windows/POSIX、traversal 和 sibling-prefix |
| copy 成功但 parse 前崩溃留下孤儿目录 | Electron pending token 仅授权本次导入的 complete/discard；正常错误路径 discard，进程崩溃时残留可诊断且不影响源文件 |
| 文件锁导致删除失败 | 文件优先删除；失败保留 DB 记录并提示关闭 Office 应用 |
| Save As 覆盖外部文件 | 使用原生 save dialog 覆盖确认；源和目标同路径不复制 |
| bundle 体积增长 | 只加入三个实际使用的 OOXML 包，不加入未使用 pandas/numpy |
| 迁移 tests 造成 import 路径变化 | 先迁移保持 RED/GREEN 基线，再逐项新增测试 |
| Win7 Python 3.8 差异 | 路径模块使用 3.8 语法，但在 main 合并后由独立 PR 和 py38 CI 验证 |
| 生成/删除重试造成重复副作用 | 对有副作用 Office API 禁用自动重试 |

## 14. 验收标准

- [ ] 从 Workspace 外选择真实 `.pptx/.docx/.xlsx` 后，Sage 创建托管副本、显示预览并写入历史；
- [ ] 拖放执行同一导入流程；
- [ ] pending import token 在 complete/discard 后立即失效，不能删除既有托管文档；
- [ ] 外部源文件在导入、Save As 和删除后保持不变；
- [ ] Windows 与 POSIX 路径 contract 全部通过；
- [ ] sibling-prefix、traversal 和 symlink escape 被拒绝；
- [ ] 三种基础生成成功、写入历史并可执行文件动作；
- [ ] Save As 创建外部副本且不改变托管主副本或 DB 记录；
- [ ] 打开文件和打开所在目录成功；
- [ ] 删除前显示明确确认；成功后托管目录和记录都消失；
- [ ] 文件删除失败时 DB 记录保留；
- [ ] `.ppt/.doc/.xls` 和任意格式不能通过 picker 或 drag-drop 导入；
- [ ] read/generate/delete 不自动重试；
- [ ] `requirements-bundled.txt` 包含三个 Office runtime distribution；
- [ ] bundled requirements contract 与 `import backend.main` canary 通过；
- [ ] Office Backend tests 被默认 pytest/CI 收集；
- [ ] Backend、Frontend、Electron 和 Playwright Office tests 全绿；
- [ ] Office 关键模块覆盖率达到或超过 80%；
- [ ] 技术文档和用户手册与实际行为一致；
- [ ] main 本次不修改 `backend/requirements-py38.txt`，Win7 同步留给独立 PR。

## 15. 实施交接

本设计批准后，应编写 TDD 实施计划，按以下顺序拆分可验证里程碑：

1. 测试收集修复与跨平台 path primitive；
2. Backend 托管路径、read 持久化和安全删除；
3. bundled dependency contract；
4. Electron 文件网关；
5. React 导入和文件动作；
6. 错误映射与重试修复；
7. integration/E2E/Windows canary；
8. 真实 Electron 端到端验证；
9. 正式技术文档和用户手册；
10. code review、安全 review、覆盖率和完整验证。
