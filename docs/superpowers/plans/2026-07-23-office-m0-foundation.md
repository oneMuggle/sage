# Office M0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Office 文件基础安全、打包、导入和管理能力，为后续 Chat-native tools 提供可验证的 Workspace 托管层。

**Architecture:** 保留现有 `backend/office` OOXML reader/generator，但把路径安全、托管目录和 SQLite 元数据集中到可复用 storage primitive。Electron 负责用户授权的导入、Save As、打开和定位；本计划不接入 LLM Chat tools，M1–M2 再消费本计划的 managed document contract。

**Tech Stack:** Python 3.11 (`sage-backend` conda env)、FastAPI、Pydantic 2、SQLite、python-pptx 0.6.23、python-docx 1.1.2、openpyxl 3.1.5、Electron 21.4.4、TypeScript、React、Vitest、pytest。

## Global Constraints

- 后端命令必须使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`。
- 不修改 `backend/requirements-py38.txt`，不直接操作 `release/win7`。
- 只支持 `.pptx`、`.docx`、`.xlsx`；移除 `.ppt`、`.doc`、`.xls` 和 All Files filter。
- 所有托管文件必须位于 `<canonical-workspace>/office/<doc_type>/<doc_id>/<filename>`。
- 所有路径 containment 必须使用 component-aware `relative_to()`/`path.relative()`，禁止字符串前缀拼接。
- 外部源文件只复制，不移动、不覆盖、不删除。
- 生成和导入的主文件保留在 Workspace；Save As 只复制到外部路径。
- 后端 Office 关键模块覆盖率必须达到 80%。
- 每个任务完成后单独提交，提交信息使用 Conventional Commits。

## File Map

### Backend

- Create: `backend/office/path_safety.py` — Python 3.8-compatible canonical path and managed-file validation。
- Modify: `backend/office/storage.py` — 使用 path safety、保存/列出/获取 managed document。
- Modify: `backend/api/office_routes.py` — read 持久化 summary、统一扩展名和路径验证。
- Modify: `backend/office/models.py` — read request 的 `original_filename` 和 managed metadata。
- Modify: `backend/data/database.py` — `derived_from`/`archived_at` 向后兼容迁移。
- Modify: `backend/requirements-bundled.txt` — 加入三个实际 Office runtime packages。
- Move: `backend/office/__tests__/conftest.py` → `backend/tests/unit/office/conftest.py`。
- Move: `backend/office/__tests__/test_excel.py` → `backend/tests/unit/office/test_excel.py`。
- Move: `backend/office/__tests__/test_generators.py` → `backend/tests/unit/office/test_generators.py`。
- Move: `backend/office/__tests__/test_ppt.py` → `backend/tests/unit/office/test_ppt.py`。
- Move: `backend/office/__tests__/test_storage.py` → `backend/tests/unit/office/test_storage.py`。
- Move: `backend/office/__tests__/test_word.py` → `backend/tests/unit/office/test_word.py`。
- Create: `backend/tests/unit/office/test_path_safety.py`。
- Create: `backend/tests/integration/test_office_routes.py`。
- Create: `backend/tests/contract/test_office_bundled_requirements.py`。

### Electron / Renderer

- Create: `electron/officePaths.ts` — `path.resolve`/`path.relative` helpers and managed ref reconstruction。
- Modify: `electron/officeIpc.ts` — pick/import/save/open/show-folder/pending-token handlers。
- Modify: `electron/preload.ts` — expose typed Office file gateway。
- Modify: `src/shared/types/electron-api.d.ts` — renderer bridge types。
- Modify: `src/features/office/OfficeFilePicker.tsx` — use import gateway and modern filters。
- Modify: `src/shared/api/officeApi.ts` — disable retries for side-effecting Office actions。
- Modify: `src/features/office/useOfficeDocuments.ts` — import/read/refresh and failure cleanup。
- Modify: `src/features/office/OfficeDocumentList.tsx` — action callbacks and confirmation boundary。
- Create: `electron/__tests__/officePaths.test.ts`。
- Create: `electron/__tests__/officeIpc.test.ts`。
- Create: `src/features/office/__tests__/OfficeFilePicker.test.tsx`。
- Create: `src/features/office/__tests__/OfficeDocumentList.test.tsx`。

### CI / Verification

- Modify: `.github/workflows/ci.yml` in existing backend and Windows build jobs。
- Create: `scripts/verify-office-paths.py` — stdlib-only Windows/POSIX path contract invoked by CI。

---

### Task 1: 收集现有 Office 测试并迁入 pytest 路径

**Files:**
- Move: the six files listed above from `backend/office/__tests__/` to `backend/tests/unit/office/`。
- Test: moved test files。

**Interfaces:**
- Consumes: current reader/generator/storage tests and `backend/pytest.ini:testpaths=tests`。
- Produces: `cd backend && pytest tests/unit/office` collects the existing Office test suite without changing behavior。

- [ ] **Step 1: Record the current direct test baseline**

Run:

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest office/__tests__ -q
```

Expected: the existing Office tests pass; record the collected count in the task log before moving files.

- [ ] **Step 2: Move the tests without changing assertions**

Run:

```bash
cd /home/fz/project/sage && \
  mkdir -p backend/tests/unit && \
  git mv backend/office/__tests__ backend/tests/unit/office
```

Keep `conftest.py` fixtures and all test bodies byte-for-byte unchanged in this step.

- [ ] **Step 3: Run the migrated collection**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/office -q --collect-only
```

Expected: collection reports the same test functions as Step 1, and no test is collected from `backend/office/__tests__`.

- [ ] **Step 4: Run the migrated tests**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/office -q
```

Expected: PASS with no import path or fixture failures.

- [ ] **Step 5: Commit the test relocation**

```bash
cd /home/fz/project/sage && \
  git add backend/office/__tests__ backend/tests/unit/office && \
  git commit -m "test: collect Office unit tests in backend suite"
```

### Task 2: 建立跨平台路径安全 primitive

**Files:**
- Create: `backend/office/path_safety.py`。
- Create: `backend/tests/unit/office/test_path_safety.py`。
- Modify: `backend/office/storage.py:32-89`。
- Modify: `backend/api/office_routes.py:65-84`。
- Modify: `backend/office/ppt.py:230-243`。
- Modify: `backend/office/word.py:196-218`。
- Modify: `backend/office/excel.py:195-221`。

**Interfaces:**
- Produces:

```python
from pathlib import Path, PurePath
from backend.office.models import OfficeDocType

def is_within(base: PurePath, candidate: PurePath) -> bool:
    raise NotImplementedError

def resolve_within(base: Path, candidate: Path) -> Path:
    raise NotImplementedError

def managed_document_path(
    workspace: Path,
    doc_type: OfficeDocType,
    document_id: str,
    filename: str,
) -> Path:
    raise NotImplementedError

def validate_supported_filename(filename: str, doc_type: OfficeDocType) -> str:
    raise NotImplementedError
```

`resolve_within` raises `OfficePathError` for traversal, sibling-prefix, absolute-outside, or symlink escape. `managed_document_path` additionally validates `_DOC_ID_PATTERN`, basename, and doc-type extension.

- [ ] **Step 1: Write failing POSIX and Windows flavor tests**

Create `backend/tests/unit/office/test_path_safety.py` with tests for:

```python
from pathlib import Path, PurePosixPath, PureWindowsPath
import pytest

from backend.office.errors import OfficePathError
from backend.office.models import OfficeDocType
from backend.office.path_safety import (
    is_within,
    managed_document_path,
    resolve_within,
)

def test_is_within_rejects_sibling_prefix() -> None:
    assert is_within(PurePosixPath('/tmp/work'), PurePosixPath('/tmp/work-evil')) is False

def test_is_within_handles_windows_separators() -> None:
    assert is_within(
        PureWindowsPath(r'C:\work'),
        PureWindowsPath(r'C:\work\office\word\id\file.docx'),
    ) is True

def test_managed_document_path_rejects_cross_type_extension(tmp_path: Path) -> None:
    with pytest.raises(OfficePathError):
        managed_document_path(tmp_path, OfficeDocType.WORD, 'abc123', 'file.xlsx')
```

Add tests for `..`, filename separators, invalid document IDs, symlink escape, and a valid path under `tmp_path`.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_path_safety.py -q
```

Expected: FAIL because `backend.office.path_safety` does not exist.

- [ ] **Step 3: Write the minimal standard-library helper**

Implement `is_within` with `candidate.relative_to(base)` inside `try/except ValueError`; never compare string prefixes. Implement `resolve_within` by resolving both paths and then calling `is_within`. Implement `managed_document_path` using the existing document ID regex and `OfficePathError`.

Use only Python 3.8-compatible syntax so the module can be cherry-picked to Win7 later.

- [ ] **Step 4: Replace all Office string-prefix checks**

Make `storage.generate_document_dir`, `office_routes._validate_file_in_workspace`, and all three generators call `resolve_within`/`managed_document_path`. Preserve the existing `validate_workspace` behavior and exception types.

- [ ] **Step 5: Run focused and full Office tests to verify GREEN**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_path_safety.py tests/unit/office -q
```

Expected: PASS, including `PureWindowsPath` sibling and separator cases.

- [ ] **Step 6: Commit the path safety unit**

```bash
cd /home/fz/project/sage && \
  git add backend/office/path_safety.py backend/office/storage.py \
  backend/api/office_routes.py backend/office/ppt.py backend/office/word.py \
  backend/office/excel.py backend/tests/unit/office/test_path_safety.py && \
  git commit -m "fix: make Office workspace containment cross-platform"
```

### Task 3: 持久化读取 summary 和兼容数据库字段

**Files:**
- Modify: `backend/data/database.py:94-99,158-181`。
- Modify: `backend/office/models.py:151-161`。
- Modify: `backend/office/storage.py:92-171`。
- Modify: `backend/api/office_routes.py:195-254`。
- Test: `backend/tests/unit/office/test_storage.py`。
- Test: `backend/tests/integration/test_office_routes.py`。

**Interfaces:**
- Add optional request field:

```python
class OfficeReadRequest(BaseModel):
    workspace_path: str
    file_path: str
    max_size_bytes: int = 50 * 1024 * 1024
    original_filename: str | None = None
```

- Extend `OfficeDocumentSummary` with nullable fields:

```python
derived_from: str | None = None
archived_at: int | None = None
```

- Add storage functions:

```python
def get_document(conn: sqlite3.Connection, document_id: str) -> OfficeDocumentSummary | None:
    raise NotImplementedError

def document_path(summary: OfficeDocumentSummary) -> Path:
    raise NotImplementedError

def list_documents(
    conn: sqlite3.Connection,
    workspace_path: str,
    include_archived: bool = False,
) -> list[OfficeDocumentSummary]:
    raise NotImplementedError
```

- [ ] **Step 1: Write failing migration and read-persistence tests**

Add tests that create an old in-memory schema without `derived_from`/`archived_at`, call `Database.init_db()`, and assert both columns exist. Add route tests that read a fixture and then query `office_documents` for the returned summary ID.

Example assertion:

```python
result = read_ppt_endpoint(
    OfficeReadRequest(workspace_path=str(workspace), file_path=str(managed_file))
)
row = conn.execute(
    'SELECT id, status, generated_filename FROM office_documents WHERE id = ?',
    (result.summary.id,),
).fetchone()
assert row['status'] == 'parsed'
assert row['generated_filename'] == managed_file.name
```

- [ ] **Step 2: Run the tests to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office/test_storage.py tests/integration/test_office_routes.py -q
```

Expected: FAIL because the migration columns, `get_document`, and read `save_document` call are absent.

- [ ] **Step 3: Add idempotent schema migration**

After `office_documents` creation in `Database.init_db`, inspect `PRAGMA table_info(office_documents)` and run these exact statements only when the named column is missing:

```sql
ALTER TABLE office_documents ADD COLUMN derived_from TEXT;
ALTER TABLE office_documents ADD COLUMN archived_at INTEGER;
```

Commit after schema initialization so old databases remain usable.

- [ ] **Step 4: Persist read summaries using the managed directory ID**

In each read route, validate the managed path, use its parent directory name as `document_id`, pass `generated_filename` and `original_filename` into `read_ppt/read_docx/read_xlsx`, then call `save_document` before returning the result. Canonicalize `workspace_path` before querying/listing.

- [ ] **Step 5: Add storage retrieval and archive-aware listing primitives**

Make `_row_to_summary` include the new nullable `derived_from` and `archived_at` fields in the model shape. `list_documents(conn, workspace_path, include_archived=False)` filters `archived_at IS NULL` by default; no existing status enum value named `archived` is introduced.

- [ ] **Step 6: Run focused integration and full Office tests**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/office tests/integration/test_office_routes.py -q
```

Expected: PASS; a read creates exactly one `parsed` record with the managed directory UUID.

- [ ] **Step 7: Commit persistence changes**

```bash
cd /home/fz/project/sage && \
  git add backend/data/database.py backend/office/models.py \
  backend/office/storage.py backend/api/office_routes.py \
  backend/tests/unit/office/test_storage.py backend/tests/integration/test_office_routes.py && \
  git commit -m "feat: persist Office reads in workspace history"
```

### Task 4: 修复 bundled dependencies 并加入 CI canary

**Files:**
- Modify: `backend/requirements-bundled.txt`。
- Create: `backend/tests/contract/test_office_bundled_requirements.py`。
- Create: `scripts/verify-office-paths.py`。
- Modify: `.github/workflows/ci.yml` in existing backend and Windows build jobs。

**Interfaces:**
- Contract test exports no application API; it parses `backend/requirements-bundled.txt`.
- `scripts/verify-office-paths.py` exits `0` for valid POSIX/Windows fixtures and non-zero for a regression.

- [ ] **Step 1: Write the failing requirements contract**

```python
from pathlib import Path

REQUIRED = {
    'python-pptx': 'pptx',
    'python-docx': 'docx',
    'openpyxl': 'openpyxl',
}

def test_bundled_requirements_include_office_runtime_packages() -> None:
    text = Path('requirements-bundled.txt').read_text(encoding='utf-8')
    for distribution in REQUIRED:
        assert any(line.startswith(distribution + '==') for line in text.splitlines())
```

Add a version-parity assertion against `backend/requirements.txt` for these three distributions.

- [ ] **Step 2: Run the contract to verify RED**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/contract/test_office_bundled_requirements.py -q
```

Expected: FAIL because `requirements-bundled.txt` omits the Office distributions.

- [ ] **Step 3: Add only the three imported runtime packages**

Add exact pinned lines:

```text
python-pptx==0.6.23
python-docx==1.1.2
openpyxl==3.1.5
```

Do not add pandas/numpy until an Office implementation imports them.

- [ ] **Step 4: Add the stdlib Windows path canary**

`scripts/verify-office-paths.py` must import `backend.office.path_safety`, assert a `PureWindowsPath(r'C:\work\office\word\id\file.docx')` is inside `PureWindowsPath(r'C:\work')`, and assert `C:\work-evil` is rejected. It must not import FastAPI or third-party packages.

- [ ] **Step 5: Run contract and canary locally**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/contract/test_office_bundled_requirements.py -q
cd /home/fz/project/sage && \
  /home/fz/anaconda3/envs/sage-backend/bin/python scripts/verify-office-paths.py
```

Expected: PASS.

- [ ] **Step 6: Wire CI collection and Windows canary**

Keep backend CI command as `cd backend && python -m pytest`; the moved tests are now collected by `testpaths=tests`. Add the canary to the existing Windows Electron/build job before packaging. Keep the release bundle `import backend.main` canary unchanged so the real bundle still validates top-level Office imports.

- [ ] **Step 7: Commit packaging and CI contract**

```bash
cd /home/fz/project/sage && \
  git add backend/requirements-bundled.txt backend/tests/contract \
  scripts/verify-office-paths.py .github/workflows/ci.yml && \
  git commit -m "fix: include Office runtime dependencies in bundled Python"
```

### Task 5: 实现 Electron Office 文件网关

**Files:**
- Create: `electron/officePaths.ts`。
- Modify: `electron/officeIpc.ts:21-80`。
- Modify: `electron/preload.ts:20-26,125-135`。
- Modify: `src/shared/types/electron-api.d.ts:55-64`。
- Create: `electron/__tests__/officePaths.test.ts`。
- Create: `electron/__tests__/officeIpc.test.ts`。

**Interfaces:**

```typescript
export type OfficeDocType = 'ppt' | 'word' | 'excel';

export interface OfficeManagedRef {
  workspacePath: string;
  docType: OfficeDocType;
  documentId: string;
  filename: string;
}

export interface ImportedOfficeFile extends OfficeManagedRef {
  managedPath: string;
  originalName: string;
  sizeBytes: number;
  importToken: string;
}

export function buildManagedPath(ref: OfficeManagedRef): string;
export function isPathWithinWorkspace(workspacePath: string, targetPath: string): boolean;
```

Bridge methods:

```typescript
pickAndImportOfficeFile(workspacePath: string, docType: OfficeDocType): Promise<ImportedOfficeFile | null>;
importDroppedOfficeFile(workspacePath: string, docType: OfficeDocType, sourcePath: string): Promise<ImportedOfficeFile>;
completeOfficeImport(importToken: string): Promise<void>;
discardOfficeImport(importToken: string): Promise<void>;
saveOfficeDocumentAs(ref: OfficeManagedRef): Promise<{ savedPath: string } | null>;
openOfficeDocument(ref: OfficeManagedRef): Promise<void>;
showOfficeDocumentInFolder(ref: OfficeManagedRef): Promise<void>;
```

- [ ] **Step 1: Write failing path and filter tests**

Test `buildManagedPath` with POSIX and Windows separators, reject sibling-prefix and traversal, map each doc type to exactly one extension, and assert the dialog filters do not contain `All Files`, `.doc`, `.xls`, or `.ppt`.

- [ ] **Step 2: Run Electron tests to verify RED**

```bash
cd /home/fz/project/sage && npm run test:run -- electron/__tests__/officePaths.test.ts electron/__tests__/officeIpc.test.ts
```

Expected: FAIL because the new path module and gateway channels are absent.

- [ ] **Step 3: Implement pure path and filename helpers**

Use `path.resolve`, `path.relative`, `path.isAbsolute`, and a component check equivalent to:

```typescript
const relative = path.relative(resolve(workspace), resolve(candidate));
const inside = relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
```

Validate `documentId` against the existing safe ID policy and require the extension matching the doc type.

- [ ] **Step 4: Implement atomic import and pending tokens**

`officeIpc.ts` must create a UUID directory, copy with `COPYFILE_EXCL`, return `ImportedOfficeFile`, and keep `token -> managedRef` in a process-local Map. `completeOfficeImport` consumes the token without deleting; `discardOfficeImport` deletes only the token’s directory and consumes the token. A forged path or expired token must not delete an existing managed document.

- [ ] **Step 5: Implement Save As/open/show-folder**

Use `dialog.showSaveDialog`, `fs.copyFile`, `shell.openPath`, and `shell.showItemInFolder`. Reconstruct and validate managed source paths from `OfficeManagedRef`; never accept arbitrary renderer paths. Return `null` for Save As cancellation and throw a typed error for `shell.openPath` non-empty results.

- [ ] **Step 6: Expose the bridge and run GREEN tests**

Update `preload.ts` and `electron-api.d.ts` with the exact interfaces above, then run:

```bash
cd /home/fz/project/sage && \
  npm run test:run -- electron/__tests__/officePaths.test.ts electron/__tests__/officeIpc.test.ts && \
  npm run typecheck:electron
```

Expected: PASS.

- [ ] **Step 7: Commit the gateway**

```bash
cd /home/fz/project/sage && \
  git add electron/officePaths.ts electron/officeIpc.ts electron/preload.ts \
  src/shared/types/electron-api.d.ts electron/__tests__/officePaths.test.ts \
  electron/__tests__/officeIpc.test.ts && \
  git commit -m "feat: add Electron Office file gateway"
```

### Task 6: 接通 M0 Office 管理基础动作

**Files:**
- Modify: `src/features/office/OfficeFilePicker.tsx`。
- Modify: `src/features/office/useOfficeDocuments.ts`。
- Modify: `src/features/office/OfficeDocumentList.tsx`。
- Modify: `src/shared/api/officeApi.ts`。
- Create: `src/features/office/__tests__/OfficeFilePicker.test.tsx`。
- Create: `src/features/office/__tests__/OfficeDocumentList.test.tsx`。

**Interfaces:**
- `OfficeFilePicker` calls `pickAndImportOfficeFile(workspacePath, docType)` and passes `managedPath` to the existing `readPpt/readWord/readExcel` wrapper。
- `useOfficeDocuments` exposes `importAndRead`, `refresh`, `deleteDocument`, and action callbacks without changing Office result models。

- [ ] **Step 1: Write failing component tests**

Add tests that mock `window.electronAPI.office.pickAndImportOfficeFile` and assert:

1. selecting a file calls read with the returned `managedPath`;
2. parse rejection calls `discardOfficeImport(importToken)`;
3. unsupported `.doc`/`.xls`/`.ppt` drop shows a user error and does not call read;
4. list action callbacks receive the document ID.

- [ ] **Step 2: Run tests to verify RED**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/features/office/__tests__/OfficeFilePicker.test.tsx \
  src/features/office/__tests__/OfficeDocumentList.test.tsx
```

Expected: FAIL because components still call the old pick-file bridge and have no gateway action props.

- [ ] **Step 3: Wire import/read and no-retry side-effecting API calls**

Update the hook to call import, then the type-specific read API, then `completeOfficeImport` only after a successful read. On read failure call `discardOfficeImport`. Remove `withRetry` from `read`, `generate`, and destructive document actions; retain bounded retry only for list if the existing error classifier marks it transient.

- [ ] **Step 4: Add management actions without destructive Chat semantics**

Add typed callbacks for Save As/open/show-folder. Do not expose a permanent delete action from the M0 management view; archive/restore and the user confirmation flow are implemented in M3–M5. Existing DB delete code may remain unreachable until the archive migration is complete.

- [ ] **Step 5: Run frontend tests and type checks**

```bash
cd /home/fz/project/sage && \
  npm run test:run -- src/features/office/__tests__/OfficeFilePicker.test.tsx \
  src/features/office/__tests__/OfficeDocumentList.test.tsx && \
  npm run typecheck && npm run typecheck:electron
```

Expected: PASS.

- [ ] **Step 6: Commit M0 UI wiring**

```bash
cd /home/fz/project/sage && \
  git add src/features/office src/shared/api/officeApi.ts && \
  git commit -m "fix: wire Office management to managed file gateway"
```

### Task 7: M0 verification and handoff

**Files:**
- Modify: `docs/plans/2026-07-16_office-features.md` only to mark the verified foundation items, without claiming Chat CRUD complete。

- [ ] **Step 1: Run backend gates**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest -q --cov=backend/office --cov-report=term-missing
```

Expected: migrated Office tests and integration/contract tests pass; Office source coverage is at least 80%.

- [ ] **Step 2: Run frontend and Electron gates**

```bash
cd /home/fz/project/sage && \
  npm run test:run && npm run typecheck && npm run typecheck:electron && npm run build
```

Expected: PASS with no `console.log` added in modified production files.

- [ ] **Step 3: Run the live M0 smoke flow**

With the app launched using the project `run-desktop` procedure:

1. select a temporary Workspace;
2. import a real `.docx`, `.pptx`, and `.xlsx` from outside it;
3. verify each source file checksum is unchanged;
4. verify preview succeeds and history gains a `parsed` record;
5. generate a basic file and verify it is under the managed directory;
6. exercise Save As, open file, and show folder;
7. try a legacy extension and verify it is rejected before backend read.

- [ ] **Step 4: Commit only M0 documentation updates**

```bash
cd /home/fz/project/sage && \
  git add docs/plans/2026-07-16_office-features.md && \
  git commit -m "docs: record Office foundation milestone"
```

## M0 Completion Gate

M0 is complete only when the existing `/office` foundation is safe and testable, Windows path canary and bundled import contract pass, and no Chat tool has been advertised yet. M1 may start only from a clean branch with all M0 commits reviewed.
