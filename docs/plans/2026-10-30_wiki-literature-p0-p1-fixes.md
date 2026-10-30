# Wiki × 文献库 P0/P1 修复实施计划

> **状态：** 2026-10-30 已实施完成（Task 1-6 + 回归 + 技术文档更新）。分支 `fix/wiki-literature-p0-p1`，待 PR 合并与 main cherry-pick。
> **评审修复：** 导入后缀白名单、队列 409 互斥锁 + 取消/崩溃回滚 + 原子持久化、Zotero 导出目录校验与 no-follow 写、Windows reparse-safe 落盘。

> **For agentic workers:** 按任务顺序执行，每个任务独立测试、独立提交。步骤使用 `- [ ]` 跟踪。

**Goal:** 修复 Wiki 图谱与 Zotero 设置页的真实缺陷，并把 Wiki 的来源管理、Deep Research、排队摄入、Zotero 项目绑定从"半成品"补到可用闭环。

**Architecture:** 以"后端 REST 契约归一 + 前端去 mock + 设置持久化"为主线；不引入新框架、不迁移存储格式。后端保持 py3.8 兼容，前端保持 Zustand + 现有 API 客户端模式。

**Tech Stack:** FastAPI (py3.8) / pytest；React 19 + TypeScript + Zustand + Vitest；Electron IPC（文件选择器）。

**Spec/依据:** 本次分析结论（2026-10-30）；相关文档 `docs/technical/25-llm-wiki-integration.md`、`docs/technical/104-zotero-llm-integration.md`、`docs/technical/106-wiki-completeness-optimization.md`。

---

## 背景与目标

2026-10-30 的完整性审计发现：

- 图谱后端输出 `direct_link/source_overlap/type_affinity`，前端只认 `DirectLink/SourceOverlap/TypeAffinity`，真实图谱边全部退化为灰色、无动画。
- Zotero REST 路由文档声明 `year / authors:list[str] / collections / tags:list[str] / page_label`，但 `ZoteroClient` 实际返回 `date / authors:str / tags:[{name,type}] / pageLabel / parentKey/itemCount`，设置页"文献库"在真实库上会报错或筛选失效。
- `SourcesView` 使用 `mockSourcesTree`，导入/新建/删除/预览全部是假操作；Wiki 的日常入口实际不可用。
- `WikiResearchPanel` 已实现但无人挂载；右栏研究区是"待实现"。
- 摄入队列有状态机和 API，但没有处理入口，也没有入队 UI。
- Zotero → Wiki 沉淀只在手动同步且传 `project_path` 时发生，没有持久化项目绑定。

本计划范围 = P0（两项真实缺陷）+ P1（来源管理、Deep Research 面板、项目绑定、队列处理）。**不包含** P2：PDF FTS itemID 修复、`literature_aggregator` 目录收敛、HNSW 接入、Adamic-Adar 第四信号。

---

## 全局约束

- 分支：`fix/wiki-literature-p0-p1`（从 `release/win7` 的 `cd35023e3` 切出）。完成后 cherry-pick 到 `main`。
- 后端解释器：`/home/fz/anaconda3/envs/sage-backend-py38/bin/python`；禁止 PEP 604/585 等 py3.10 语法。
- 前端：Node `v25.9.0`；不得引入新依赖；UI 文案中文；设置页新增文案走 `settings.*` i18n key（zh/en 同步）。
- 安全边界：任何写入项目目录的路径必须 resolve 后仍在项目根内；symlink / 非普通文件 fail-closed；外部导入文件 ≤ `backend.wiki.ingest.MAX_FILE_BYTES`。
- 每个任务结束必须跑对应测试并提交；提交信息用 Conventional Commits。
- 不修改 `backend/requirements.txt` / `backend/requirements-py38.txt`。

---

## 文件结构

| 模块 | 文件 | 责任 |
|---|---|---|
| 图谱前端 | `src/shared/types/wiki.ts`、`src/widgets/wiki/WikiGraphView.tsx`、`src/widgets/wiki/__tests__/WikiGraphView.test.tsx` | 信号枚举兼容 + 归一化显示 |
| Zotero 契约 | `backend/api/zotero_routes.py`、`backend/zotero/client.py`、`backend/tests/unit/api/test_zotero_routes.py`、`backend/tests/unit/zotero/test_client.py` | REST 形状归一 |
| 来源管理 | `backend/api/wiki_routes.py`、`backend/wiki/ingest.py`、`backend/tests/unit/wiki/test_ingest_import.py`、`src/widgets/wiki/SourcesView.tsx`、`src/widgets/wiki/SourcesTree.tsx`、`src/shared/api-client/wiki.ts`、`electron/main.ts`、`electron/preload.ts`、`src/shared/types/electron-api.d.ts`、`src/widgets/wiki/__tests__/SourcesView.test.tsx` | 真实列表/预览/删除/导入 |
| Deep Research | `src/widgets/wiki/RightPanel.tsx`、`src/widgets/wiki/WikiResearchPanel.tsx`、`src/pages/Knowledge.tsx`、`src/shared/lib/searchConfig.ts`、`src/widgets/wiki/__tests__/RightPanel.research.test.tsx` | 面板挂载 + Tavily 配置 |
| Zotero 绑定 | `backend/data/settings_repo.py`、`backend/api/zotero_sync_routes.py`、`backend/tests/unit/test_zotero_sync_routes.py`、`src/shared/api/zoteroClient.ts`、`src/pages/settings/zotero/ZoteroSyncPanel.tsx`、i18n | 项目持久绑定 + 后台沉淀 |
| 队列处理 | `backend/wiki/queue_worker.py`、`backend/api/wiki_routes.py`、`backend/tests/unit/wiki/test_queue_worker.py`、`src/shared/api-client/wiki.ts`、`src/entities/wiki/queue-store.ts`、`src/widgets/wiki/WikiQueuePanel.tsx`、`src/widgets/wiki/SourcesView.tsx` | 入队 + 服务端处理入口 |

---

## Task 1: 图谱信号归一化（P0）

**Files:**
- Modify: `src/shared/types/wiki.ts:196,206-210`
- Modify: `src/widgets/wiki/WikiGraphView.tsx:69-73,316-329`
- Test: `src/widgets/wiki/__tests__/WikiGraphView.test.tsx`

**Interfaces:**
- Produces: `normalizeGraphSignal(signal: string): GraphSignal | null`（从 `WikiGraphView.tsx` 导出，`@internal` 供测试）。
- Produces: `GraphSignalWire = 'direct_link' | 'source_overlap' | 'type_affinity'`；`GraphEdge.signal: GraphSignal | GraphSignalWire`。

- [x] **Step 1: 写失败测试**

在 `WikiGraphView.test.tsx` 增加：

```tsx
import { buildGraph, colorByType, normalizeGraphSignal } from '../WikiGraphView';

describe('normalizeGraphSignal', () => {
  it('maps backend snake_case values to canonical signals', () => {
    expect(normalizeGraphSignal('direct_link')).toBe('DirectLink');
    expect(normalizeGraphSignal('source_overlap')).toBe('SourceOverlap');
    expect(normalizeGraphSignal('type_affinity')).toBe('TypeAffinity');
  });
  it('accepts canonical values and unknown falls back to null', () => {
    expect(normalizeGraphSignal('DirectLink')).toBe('DirectLink');
    expect(normalizeGraphSignal('mystery')).toBeNull();
  });
});

describe('buildGraph with backend wire signals', () => {
  it('colors and animates direct_link edges like DirectLink', () => {
    const data: GraphData = {
      nodes: [
        { id: 'a', label: 'A', sources: [], wikilinks: [] },
        { id: 'b', label: 'B', sources: [], wikilinks: [] },
      ],
      edges: [{ source: 'a', target: 'b', signal: 'direct_link' as never, weight: 3 }],
    };
    const { edges } = buildGraph(data);
    expect(edges[0].label).toBe('DirectLink');
    expect((edges[0].style as { stroke: string }).stroke).toBe('#0ea5e9');
    expect(edges[0].animated).toBe(true);
  });
});
```

- [x] **Step 2: 运行确认失败**

Run: `npm run test:run -- src/widgets/wiki/__tests__/WikiGraphView.test.tsx`
Expected: FAIL（`normalizeGraphSignal` 未导出）。

- [x] **Step 3: 最小实现**

`src/shared/types/wiki.ts`：

```ts
export type GraphSignal = 'DirectLink' | 'SourceOverlap' | 'TypeAffinity';
export type GraphSignalWire = 'direct_link' | 'source_overlap' | 'type_affinity';

export interface GraphEdge {
  source: string;
  target: string;
  signal: GraphSignal | GraphSignalWire;
  weight: number;
}
```

`WikiGraphView.tsx` 增加：

```ts
// eslint-disable-next-line react-refresh/only-export-components
export function normalizeGraphSignal(signal: string): GraphSignal | null {
  const key = signal.replace(/[_\s-]/g, '').toLowerCase();
  if (key === 'directlink') return 'DirectLink';
  if (key === 'sourceoverlap') return 'SourceOverlap';
  if (key === 'typeaffinity') return 'TypeAffinity';
  return null;
}
```

`buildGraph` 的边循环改为：

```ts
const edges: Edge[] = data.edges.map((e, i) => {
  const signal = normalizeGraphSignal(e.signal);
  return {
    id: `${e.source}->${e.target}-${e.signal}-${i}`,
    source: e.source,
    target: e.target,
    label: signal ?? e.signal,
    style: {
      stroke: signal ? SIGNAL_COLORS[signal] : '#94a3b8',
      strokeWidth: Math.max(1, e.weight / 2),
      opacity: 0.6,
    },
    animated: signal === 'DirectLink',
  };
});
```

- [x] **Step 4: 运行确认通过**

Run: `npm run test:run -- src/widgets/wiki/__tests__/WikiGraphView.test.tsx`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add src/shared/types/wiki.ts src/widgets/wiki/WikiGraphView.tsx src/widgets/wiki/__tests__/WikiGraphView.test.tsx
git commit -m "fix(wiki): 图谱信号兼容后端 snake_case 输出"
```

---

## Task 2: Zotero REST 契约归一（P0）

**Files:**
- Modify: `backend/api/zotero_routes.py:139-246`
- Modify: `backend/zotero/client.py:453-469,1004-1040`
- Test: `backend/tests/unit/api/test_zotero_routes.py`

**Interfaces:**
- Produces: `_item_to_summary(row) -> {year:int|null, authors:list[str], tags:list[str], collections:list[str], ...}`
- Produces: `_item_to_detail(row) -> {authors:list[str], tags:list[str], collections:list[str], attachments:[{key,filename,path,content_type}]}`
- Produces: `_annotation_to_rest(row) -> {page_label, date_added, ...}`；`/collections` 输出 `parent_key/item_count`。
- Consumes: `ZoteroClient.get_item()` 附件新增 `key` / `filename` 字段（其余字段不变，MCP 兼容）。

- [x] **Step 1: 写失败测试**

在 `backend/tests/unit/api/test_zotero_routes.py` 增加：

```python
def test_item_to_summary_normalizes_client_shape():
    out = zr._item_to_summary(
        {
            "key": "K1",
            "title": "T1",
            "item_type": "journalArticle",
            "date": "2021-05-01",
            "authors": "Doe John, Smith Jane",
            "tags": ["a", "b"],
            "collections": ["Col A"],
        }
    )
    assert out["year"] == 2021
    assert out["authors"] == ["Doe John", "Smith Jane"]
    assert out["tags"] == ["a", "b"]


def test_item_to_detail_normalizes_objects():
    out = zr._item_to_detail(
        {
            "key": "K1",
            "date": "2019",
            "authors": [{"firstName": "John", "lastName": "Doe", "creatorType": "author"}],
            "tags": [{"name": "ml", "type": 0}],
            "collections": [{"key": "C1", "name": "Paper"}],
            "attachments": [
                {"itemID": 7, "contentType": "application/pdf", "path": "storage:a.pdf", "linkMode": 1}
            ],
        }
    )
    assert out["year"] == 2019
    assert out["authors"] == ["John Doe"]
    assert out["tags"] == ["ml"]
    assert out["collections"] == ["Paper"]
    assert out["attachments"][0]["filename"] == "a.pdf"
    assert out["attachments"][0]["content_type"] == "application/pdf"


def test_annotation_to_rest_renames_page_label():
    out = zr._annotation_to_rest(
        {"key": "a1", "type": "highlight", "text": "x", "pageLabel": "3", "dateModified": "2026-01-01"}
    )
    assert out["page_label"] == "3"
    assert out["date_added"] == "2026-01-01"


def test_collection_to_rest_normalizes_camel_case():
    out = zr._collection_to_rest({"key": "C1", "name": "Col", "parentKey": None, "itemCount": 2})
    assert out["parent_key"] is None
    assert out["item_count"] == 2
```

- [x] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/api/test_zotero_routes.py -q`
Expected: FAIL（`_annotation_to_rest` / `_collection_to_rest` 不存在；年份/作者断言失败）。

- [x] **Step 3: 实现归一化助手并接入路由**

在 `zotero_routes.py` Helpers 区：

```python
import re

def _year_from_date(value: Any) -> Optional[int]:
    if value is None:
        return None
    match = re.match(r"^\s*(\d{4})", str(value))
    return int(match.group(1)) if match else None


def _author_name(entry: Any) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        parts = [entry.get("firstName"), entry.get("lastName")]
        return " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return ""


def _author_names(value: Any) -> List[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [name for name in (_author_name(item) for item in value) if name]
    return []


def _tag_names(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        name = item if isinstance(item, str) else item.get("name") if isinstance(item, dict) else ""
        if name and str(name).strip():
            names.append(str(name).strip())
    return names


def _collection_names(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("key") or ""
        else:
            name = ""
        if str(name).strip():
            names.append(str(name).strip())
    return names


def _attachment_to_rest(entry: Dict[str, Any]) -> Dict[str, Any]:
    path = entry.get("path") or ""
    filename = entry.get("filename") or ""
    if not filename and path:
        filename = path[len("storage:") :] if path.startswith("storage:") else Path(path).name
    return {
        "key": entry.get("key") or "",
        "filename": filename,
        "path": path or None,
        "content_type": entry.get("content_type") or entry.get("contentType") or None,
    }


def _annotation_to_rest(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "key": row.get("key", ""),
        "type": row.get("type", ""),
        "text": row.get("text") or None,
        "comment": row.get("comment") or None,
        "color": row.get("color") or None,
        "page_label": row.get("page_label") or row.get("pageLabel") or None,
        "date_added": row.get("date_added") or row.get("dateModified") or None,
    }


def _collection_to_rest(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "key": row.get("key", ""),
        "name": row.get("name", ""),
        "parent_key": row.get("parent_key", row.get("parentKey")),
        "item_count": row.get("item_count", row.get("itemCount", 0)),
        "version": row.get("version", 0),
    }
```

`_item_to_summary` 改为：

```python
    return {
        "key": row.get("key", ""),
        "title": row.get("title", ""),
        "item_type": row.get("item_type", ""),
        "year": row.get("year") if isinstance(row.get("year"), int) else _year_from_date(row.get("date")),
        "authors": _author_names(row.get("authors")),
        "abstract": row.get("abstract"),
        "collections": _collection_names(row.get("collections")),
        "tags": _tag_names(row.get("tags")),
        "date_added": row.get("date_added"),
    }
```

`_item_to_detail` 同样使用 `_author_names/_tag_names/_collection_names`，附件映射 `[_attachment_to_rest(a) for a in row.get("attachments") or []]`。

`get_annotations` 返回 `[_annotation_to_rest(a) for a in annotations]`；`list_collections` 返回 `[_collection_to_rest(r) for r in rows]`，并更新文件头注释（detail collections 现为 `list[str]`）。

`backend/zotero/client.py` 的 `get_item()` 附件查询改为：

```sql
SELECT ia.itemID, i.key AS attachment_key, ia.contentType, ia.path, ia.linkMode
FROM itemAttachments ia
JOIN items i ON i.itemID = ia.itemID
WHERE ia.parentItemID = ?
```

并输出：

```python
{
    "itemID": r["itemID"],
    "key": r["attachment_key"],
    "filename": self._attachment_filename(r["path"]),
    "contentType": r["contentType"],
    "path": r["path"],
    "linkMode": r["linkMode"],
}
```

新增静态方法：

```python
@staticmethod
def _attachment_filename(path: Optional[str]) -> str:
    if not path:
        return ""
    if path.startswith("storage:"):
        return path[len("storage:") :]
    return Path(path).name
```

- [x] **Step 4: 运行后端测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/api/test_zotero_routes.py backend/tests/unit/zotero -q
```
Expected: PASS（若 `test_client.py` 旧断言依赖 attachments 字段集合，更新为新字段并保留旧字段）。

- [x] **Step 5: 前端类型确认**

`src/shared/api/zoteroClient.ts` 的 `ZoteroItemDetail.collections` 与后端 detail 现统一为 `string[]`；`ZoteroAttachment` 已匹配。无需改 UI 代码。

- [x] **Step 6: 提交**

```bash
git add backend/api/zotero_routes.py backend/zotero/client.py backend/tests/unit/api/test_zotero_routes.py backend/tests/unit/zotero
git commit -m "fix(zotero): REST 契约归一 authors/tags/collections/annotations"
```

---

## Task 3: SourcesView 真实数据 + 外部文件导入（P1）

**Files:**
- Modify: `backend/wiki/ingest.py`（新增 `import_source_into_raw`）
- Modify: `backend/api/wiki_routes.py`（新增 `POST /wiki/source/import`）
- Create: `backend/tests/unit/wiki/test_ingest_import.py`
- Modify: `electron/main.ts`（`sage:dialog:select-file`）
- Modify: `electron/preload.ts:196-200`、`src/shared/types/electron-api.d.ts:432-437`
- Modify: `src/shared/api-client/wiki.ts`（`wikiImportSource`）
- Modify: `src/widgets/wiki/SourcesView.tsx`、`src/widgets/wiki/SourcesTree.tsx`
- Create: `src/widgets/wiki/__tests__/SourcesView.test.tsx`

**Interfaces:**
- Produces: `async def import_source_into_raw(project_root: Path, external_path: Path, max_bytes: int = MAX_FILE_BYTES) -> Path`
- Produces: `POST /api/v1/wiki/source/import` body `{source_path, project_path}` → `{relative_path, name}`
- Produces: `wikiImportSource(sourcePath: string, projectPath: string): Promise<{relative_path: string; name: string}>`
- Produces: `window.electronAPI.selectFile(opts?: {title?: string; filters?: {name: string; extensions: string[]}[]}): Promise<string | null>`

- [x] **Step 1: 写后端失败测试**

`backend/tests/unit/wiki/test_ingest_import.py`：

```python
import os
from pathlib import Path

import pytest

from backend.wiki.ingest import import_source_into_raw

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_imports_regular_file_into_raw_sources(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    src = outside / "paper.md"
    src.write_text("# hi", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()

    dest = await import_source_into_raw(project, src)

    assert dest == project / "raw" / "sources" / "paper.md"
    assert dest.read_text(encoding="utf-8") == "# hi"


@pytest.mark.asyncio
async def test_rejects_symlink_and_traversal_name(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "real.md"
    real.write_text("x", encoding="utf-8")
    link = outside / "link.md"
    link.symlink_to(real)
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError):
        await import_source_into_raw(project, link)


@pytest.mark.asyncio
async def test_rejects_oversized_file(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    big = outside / "big.md"
    big.write_bytes(b"x" * 32)
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError):
        await import_source_into_raw(project, big, max_bytes=16)
```

- [x] **Step 2: 运行确认失败**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/wiki/test_ingest_import.py -q
```
Expected: FAIL（`import_source_into_raw` 不存在）。

- [x] **Step 3: 实现导入助手（`backend/wiki/ingest.py`）**

```python
async def import_source_into_raw(
    project_root: Path,
    external_path: Path,
    max_bytes: int = MAX_FILE_BYTES,
) -> Path:
    """把项目外部的普通文件导入 ``raw/sources/``。

    外部路径必须是绝对路径、存在的普通文件（symlink fail-closed）；
    读取量受 ``max_bytes`` 限制，随后复用 :func:`copy_to_raw` 的
    O_EXCL/no-follow 落盘与内容一致性检查。
    """
    path = external_path.expanduser()
    if not path.is_absolute():
        raise ValueError("源文件必须是绝对路径")
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise ValueError("源文件不存在") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError("仅支持普通文件")
    payload = secure_read_file_bounded(path.parent, path, max_bytes)
    return await copy_to_raw(
        project_root,
        path,
        logical_filename=path.name,
        source_content=payload,
    )
```

（`os`/`stat`/`secure_read_file_bounded` 在 ingest.py 已导入；若 `secure_read_file_bounded` 未导入则补充。）

- [x] **Step 4: 实现导入路由（`backend/api/wiki_routes.py`）**

```python
class SourceImportRequest(BaseModel):
    source_path: str
    project_path: str


@router.post("/source/import")
async def import_source(req: SourceImportRequest) -> dict:
    """把项目外部文件导入 ``raw/sources/``，返回项目内相对路径。"""
    from backend.wiki.ingest import import_source_into_raw

    authorize_registered_project(req.project_path)
    project_root = _canonical_project_root(req.project_path)
    try:
        dest = await import_source_into_raw(project_root, Path(req.source_path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.warning("source import failed: error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="文件导入失败") from exc
    relative = str(dest.relative_to(project_root)).replace("\\", "/")
    return {"relative_path": relative, "name": dest.name}
```

- [x] **Step 5: 运行后端测试**

Run: `... -m pytest backend/tests/unit/wiki/test_ingest_import.py backend/tests/unit/api/test_wiki_routes.py -q`
Expected: PASS。

- [x] **Step 6: Electron 文件选择器**

`electron/main.ts` 在 `sage:dialog:select-directory` 之后新增：

```ts
ipcMain.handle(
  'sage:dialog:select-file',
  async (evt, opts: { title?: string; filters?: { name: string; extensions: string[] }[] }) => {
    if (!isTrustedRenderer(evt.sender)) throw new Error('未授权的窗口请求');
    const win = BrowserWindow.fromWebContents(evt.sender);
    const result = await dialog.showOpenDialog(win ?? undefined!, {
      properties: ['openFile'],
      title: opts?.title,
      filters: opts?.filters,
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    return result.filePaths[0];
  },
);
```

`electron/preload.ts`（`selectDirectory` 旁）：

```ts
selectFile: (opts?: { title?: string; filters?: { name: string; extensions: string[] }[] }) =>
  ipcRenderer.invoke('sage:dialog:select-file', opts) as Promise<string | null>,
```

`src/shared/types/electron-api.d.ts` 同步加入方法签名。

- [x] **Step 7: 前端 API + SourcesView 重写**

`src/shared/api-client/wiki.ts` 增加：

```ts
export async function wikiImportSource(
  sourcePath: string,
  projectPath: string,
): Promise<{ relative_path: string; name: string }> {
  return httpPost('/wiki/source/import', { source_path: sourcePath, project_path: projectPath });
}
```

`SourcesView.tsx` 改造要点（完整替换文件本地实现）：

- 删除 `mockSourcesTree` 导入；新增 `useEffect` 调 `wikiListDirectory('raw/sources', project.path)`，取 `response[0]?.children ?? []`；404/目录缺失显示空态。
- `handleImport`：`window.electronAPI.selectFile?.({ title: '选择要导入的文件', filters: [{ name: '文档', extensions: ['md','markdown','txt','pdf','docx','pptx','xlsx','html','csv'] }] })` → 成功后 `wikiImportSource(path, project.path)` → `toast.success` → `refresh()` → `handleIngest(result.relative_path)`（自动进入 Wiki）。
- `handleDelete`：调用 `wikiDeleteSource(path, project.path)`，成功后 `refresh()`；错误 toast。
- 预览：选中文件后，后缀 ∈ `.md/.markdown/.txt` 时调 `wikiReadFile(path, project.path)` 渲染 `<pre>`；其他类型显示"该类型文件不支持文本预览"。删除硬编码大小/时间。
- Header：移除无实现的"新建文件夹"按钮；"导入文件"绑定 `handleImport`。
- `SourcesTree` 不需要改（列表为空时显示空态）。

- [x] **Step 8: 写前端测试**

`src/widgets/wiki/__tests__/SourcesView.test.tsx` mock `shared/api-client/wiki` 与 `window.electronAPI`：

```tsx
it('renders raw/sources entries from the backend', async () => {
  vi.mocked(wikiListDirectory).mockResolvedValue([
    { name: 'sources', path: 'raw/sources', is_dir: true, children: [
      { name: 'a.md', path: 'raw/sources/a.md', is_dir: false, children: [] },
    ] },
  ]);
  render(<SourcesView />);
  expect(await screen.findByText('a.md')).toBeInTheDocument();
});

it('imports a picked file then ingests the returned relative path', async () => {
  window.electronAPI = { selectFile: vi.fn().mockResolvedValue('/tmp/x.md') } as never;
  vi.mocked(wikiImportSource).mockResolvedValue({ relative_path: 'raw/sources/x.md', name: 'x.md' });
  render(<SourcesView />);
  await userEvent.click(screen.getByRole('button', { name: /导入文件/ }));
  expect(wikiImportSource).toHaveBeenCalledWith('/tmp/x.md', '/proj');
  expect(wikiIngestStream).toHaveBeenCalledWith(expect.objectContaining({ sourceFile: 'raw/sources/x.md' }));
});
```

（`useWikiStore.setState({ project: { id:'p', name:'p', path:'/proj' } })` 在 beforeEach 设置。）

- [x] **Step 9: 运行前后端测试**

Run:
```bash
npm run test:run -- src/widgets/wiki/__tests__/SourcesView.test.tsx src/widgets/wiki/__tests__/SourcesTree.p140.test.ts
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/wiki/test_ingest_import.py backend/tests/unit/api/test_wiki_routes.py -q
```
Expected: PASS。

- [x] **Step 10: 提交**

```bash
git add backend/wiki/ingest.py backend/api/wiki_routes.py backend/tests/unit/wiki/test_ingest_import.py \
  electron/main.ts electron/preload.ts src/shared/types/electron-api.d.ts \
  src/shared/api-client/wiki.ts src/widgets/wiki/SourcesView.tsx src/widgets/wiki/__tests__/SourcesView.test.tsx
git commit -m "feat(wiki): SourcesView 接真实数据并支持外部文件导入"
```

---

## Task 4: Deep Research 面板挂载（P1）

**Files:**
- Modify: `src/widgets/wiki/RightPanel.tsx:41-58`
- Modify: `src/widgets/wiki/WikiResearchPanel.tsx:10-18,129-135`
- Modify: `src/pages/Knowledge.tsx:104-105`
- Create: `src/shared/lib/searchConfig.ts`
- Create: `src/widgets/wiki/__tests__/RightPanel.research.test.tsx`

**Interfaces:**
- Produces: `parseTavilyKey(raw: string | null): string`（从 `searchConfig.ts`）。
- Consumes: `useSettings()` + `resolveEndpoint()`（同 `WikiChat` 的模式）、`settingsClient.getPreference('search_config')`。

- [x] **Step 1: 写失败测试**

`RightPanel.research.test.tsx`：mock `useSettings` 返回聊天端点、`settingsClient.getPreference` 返回 `{"tavily_key":"tvly-x"}`、`useResearchStore.setState({panelOpen:true})`、`useWikiStore.setState({project:{...}})`；断言渲染出 "Deep Research" 文本框且"开始研究"按钮可用。第二个用例 tavily_key 为空时断言按钮 disabled 且出现配置提示。

- [x] **Step 2: 运行确认失败**

Run: `npm run test:run -- src/widgets/wiki/__tests__/RightPanel.research.test.tsx`
Expected: FAIL（右栏仍是"待实现"）。

- [x] **Step 3: 实现**

`src/shared/lib/searchConfig.ts`：

```ts
export interface SearchConfigPayload {
  order: string[];
  tavily_key: string;
  zhipu_key: string;
}

export function parseTavilyKey(raw: string | null): string {
  if (!raw) return '';
  try {
    const parsed = JSON.parse(raw) as { tavily_key?: unknown };
    return typeof parsed.tavily_key === 'string' ? parsed.tavily_key.trim() : '';
  } catch {
    return '';
  }
}
```

`WikiResearchPanel` props 增加 `disabledReason?: string | null`，按钮 `disabled={!topic.trim() || Boolean(disabledReason)}`，并在按钮上方展示 reason。

`RightPanel.tsx` 在 `researchPanelOpen` 分支内：

```tsx
{researchPanelOpen && (
  <div className={`${selectedFile ? 'h-1/2' : 'flex-1'} overflow-hidden`}>
    {/* header 保持不变 */}
    <div className="flex-1 overflow-y-auto">
      {project && endpoint && model ? (
        <WikiResearchPanel
          projectPath={project.path}
          llmBaseUrl={endpoint.baseUrl}
          llmApiKey={endpoint.apiKey}
          llmModel={model}
          searchProvider="tavily"
          searchApiKey={tavilyKey}
          disabledReason={tavilyKey ? null : '需要在「设置 → 网络」配置 Tavily API Key'}
        />
      ) : (
        <p className="text-sm text-muted p-4">请先选择项目并配置聊天模型</p>
      )}
    </div>
  </div>
)}
```

组件顶部通过 `useSettings()` + `resolveEndpoint` 取 endpoint/model；`useEffect` 读 `search_config` 并 `setTavilyKey(parseTavilyKey(raw))`。

`Knowledge.tsx` 右侧面板条件改为 `(activeView === 'browser' || useResearchStore.getState().panelOpen)`（用订阅变量 `researchPanelOpen`，新增一行 `const researchPanelOpen = useResearchStore((s) => s.panelOpen);`），保证任意视图点研究按钮都能看到面板。

- [x] **Step 4: 运行前端测试**

Run:
```bash
npm run test:run -- src/widgets/wiki/__tests__/RightPanel.research.test.tsx src/widgets/wiki/__tests__/WikiChat.sources.test.tsx
npm run typecheck
```
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add src/shared/lib/searchConfig.ts src/widgets/wiki/RightPanel.tsx src/widgets/wiki/WikiResearchPanel.tsx \
  src/pages/Knowledge.tsx src/widgets/wiki/__tests__/RightPanel.research.test.tsx
git commit -m "feat(wiki): 挂载 Deep Research 面板并接入 Tavily 配置"
```

---

## Task 5: Zotero 项目绑定 + 后台 wiki 沉淀（P1）

**Files:**
- Modify: `backend/data/settings_repo.py:106`（白名单新增 key）
- Modify: `backend/api/zotero_sync_routes.py:59-105,182-221`
- Modify: `backend/tests/unit/test_zotero_sync_routes.py`
- Modify: `src/shared/api/zoteroClient.ts:169-190`
- Modify: `src/pages/settings/zotero/ZoteroSyncPanel.tsx:60-69,105-135,250-310`
- Modify: `src/shared/lib/i18n/locales/zh/chatAndSider.ts`、`src/shared/lib/i18n/locales/en/chatAndSider.ts`
- Modify: `src/pages/settings/__tests__/ZoteroSyncPanel.test.tsx`

**Interfaces:**
- Produces: settings key `zotero_wiki_project_path`（绝对路径字符串）。
- Produces: `zoteroClient.getWikiProjectPath(): Promise<string>` / `setWikiProjectPath(path: string): Promise<void>`（空串 = 清除绑定）。
- Produces: `_configured_wiki_project() -> Optional[str]`；`POST /zotero/sync` 在 `project_path` 缺省时使用绑定；`run_background_sync()` 在绑定存在时执行 wiki 导出。
- Produces: `GET /zotero/sync-status` 新增 `wiki_project_path: str | null`。

- [x] **Step 1: 写后端失败测试**

在 `test_zotero_sync_routes.py` 增加（mock `SettingsRepository.get` 返回 `/proj`，monkeypatch `_run_wiki_export`）：

```python
@pytest.mark.asyncio
async def test_sync_uses_persisted_wiki_project(monkeypatch):
    monkeypatch.setattr(zr, "_configured_wiki_project", lambda: "/proj")
    monkeypatch.setattr(zr, "_run_wiki_export", lambda client, path: {"items_exported": 1})
    ...  # 用现有 fake client/ingestor fixture 调 sync_zotero(SyncRequest())
    assert result["wiki"]["items_exported"] == 1
```

以及：

```python
def test_sync_status_exposes_wiki_project(monkeypatch):
    monkeypatch.setattr(zr, "_configured_wiki_project", lambda: "/proj")
    assert zr.sync_status()["wiki_project_path"] == "/proj"
```

- [x] **Step 2: 运行确认失败**

Run: `... -m pytest backend/tests/unit/test_zotero_sync_routes.py -q`
Expected: FAIL。

- [x] **Step 3: 后端实现**

`settings_repo.py` 白名单追加：

```python
# 2026-10-30: Zotero wiki 沉淀的持久项目路径（手动/后台同步共用）
"zotero_wiki_project_path",
```

`zotero_sync_routes.py`：

```python
WIKI_PROJECT_KEY = "zotero_wiki_project_path"


def _configured_wiki_project() -> Optional[str]:
    try:
        from backend.data.settings_repo import SettingsRepository

        value = SettingsRepository().get(WIKI_PROJECT_KEY) or ""
    except Exception:
        return None
    value = value.strip()
    return value or None
```

`sync_zotero` 内：`project_path = body.project_path or _configured_wiki_project()`；`if project_path: ...`。

`run_background_sync` 在增量同步成功后：

```python
binding = _configured_wiki_project()
if binding:
    wiki_payload = _run_wiki_export(client, binding)
    if not wiki_payload.get("errors"):
        _record_wiki_pages(
            wiki_payload.get("items_exported", 0) + wiki_payload.get("authors_exported", 0)
        )
    else:
        logger.warning("zotero background wiki export errors: %s", wiki_payload.get("errors"))
```

`sync_status` 返回体追加 `"wiki_project_path": _configured_wiki_project()`。

- [x] **Step 4: 前端客户端 + UI**

`zoteroClient.ts` 增加（与 `getWikiTag` 同模式）：

```ts
async getWikiProjectPath(): Promise<string> {
  const pref = await invoke<{ value: string | null } | null>('get_preference', {
    key: 'zotero_wiki_project_path',
  });
  return (pref?.value ?? '').trim();
},

async setWikiProjectPath(path: string): Promise<void> {
  await invoke('set_preference', {
    key: 'zotero_wiki_project_path',
    value: path.trim(),
    value_type: 'string',
    category: 'general',
  });
},
```

`ZoteroSyncStatus` 增加 `wiki_project_path: string | null`。

`ZoteroSyncPanel`：

- 新增 `wikiProjectPath` state，挂载时读取；`resolveProjectPath()` 优先返回绑定值。
- 在 wiki tag 配置下方增加绑定输入 + 保存按钮（`data-testid="zotero-wiki-project-input"` / `-save`），提示文案说明"留空则使用当前/最近打开的项目"。
- i18n keys（zh/en）：
  - `settings.zotero.wiki_project.label` = "Wiki 项目路径（可选）" / "Wiki project path (optional)"
  - `.placeholder` = "留空则自动使用当前/最近项目" / "Empty = use current/recent project"
  - `.save` = "保存绑定" / "Save binding"
  - `.saved` = "项目绑定已保存" / "Project binding saved"
  - `.hint` = "同步时把带 Wiki 标签的文献沉淀到该项目的 wiki/zotero/" / "Tagged items are exported to this project's wiki/zotero/"

`ZoteroSyncPanel.test.tsx` 增加：绑定存在时 `zoteroClient.sync` 收到的 `projectPath` 为绑定值。

- [x] **Step 5: 运行测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_zotero_sync_routes.py backend/tests/unit/api/test_zotero_routes.py -q
npm run test:run -- src/pages/settings/__tests__/ZoteroSyncPanel.test.tsx src/pages/settings/__tests__/ZoteroTab.test.tsx
```
Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add backend/data/settings_repo.py backend/api/zotero_sync_routes.py backend/tests/unit/test_zotero_sync_routes.py \
  src/shared/api/zoteroClient.ts src/pages/settings/zotero/ZoteroSyncPanel.tsx \
  src/shared/lib/i18n/locales/zh/chatAndSider.ts src/shared/lib/i18n/locales/en/chatAndSider.ts \
  src/pages/settings/__tests__/ZoteroSyncPanel.test.tsx
git commit -m "feat(zotero): 持久化 wiki 项目绑定并在后台同步中沉淀"
```

---

## Task 6: 摄入队列处理闭环（P1）

**Files:**
- Create: `backend/wiki/queue_worker.py`
- Modify: `backend/api/wiki_routes.py:833-1000`（入队校验 + `POST /ingest/queue/process`）
- Create: `backend/tests/unit/wiki/test_queue_worker.py`
- Modify: `src/shared/api-client/wiki.ts`（`queueProcess`）
- Modify: `src/entities/wiki/queue-store.ts`（`processQueue`）
- Modify: `src/widgets/wiki/WikiQueuePanel.tsx`（"处理队列"按钮）
- Modify: `src/widgets/wiki/SourcesTree.tsx`（`onQueue` 可选 action）
- Modify: `src/widgets/wiki/SourcesView.tsx`（"加入队列"）
- Create: `src/entities/wiki/__tests__/queue-store.process.test.ts`（如目录不存在则放 `src/widgets/wiki/__tests__`）

**Interfaces:**
- Produces: `async def process_pending(project_root: Path, limit: int = 1) -> dict` → `{"processed": [{task_id,status,wiki_page_path?,error?}], "remaining": QueueStatusSummary, "error"?: str}`
- Produces: `POST /api/v1/wiki/ingest/queue/process` body `{project_path, limit}`（limit 夹紧 1..20）。
- Produces: `queueProcess(projectPath, limit?)` API + `processQueue` store action。

- [x] **Step 1: 写后端失败测试**

`test_queue_worker.py`（真实 `IngestQueue`，monkeypatch 依赖）：

```python
@pytest.mark.asyncio
async def test_process_pending_marks_completed(tmp_path, monkeypatch):
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    src = tmp_path / "raw" / "sources" / "a.md"
    src.write_text("# a", encoding="utf-8")
    queue = IngestQueue(tmp_path)
    task_id = queue.add("raw/sources/a.md")

    monkeypatch.setattr(qw, "load_llm_config_from_settings", lambda: {"base_url": "http://x", "api_key": "k", "model": "m"})
    monkeypatch.setattr(qw, "load_embedding_config", lambda: {"base_url": "http://x", "api_key": "k", "model": "e"})

    class _Result:
        wiki_page_path = "wiki/sources/a.md"
        page_type = "source"

    async def fake_ingest(*args, **kwargs):
        return _Result()

    monkeypatch.setattr(qw, "ingest_source", fake_ingest)

    out = await qw.process_pending(tmp_path, limit=1)
    assert out["processed"][0]["status"] == "completed"
    assert IngestQueue(tmp_path).get_task(task_id).status is QueueStatus.COMPLETED
```

再加失败用例（fake_ingest 抛错 → FAILED）与未配置 LLM 用例（返回 `error` 且任务保持 PENDING）。

- [x] **Step 2: 运行确认失败**

Run: `... -m pytest backend/tests/unit/wiki/test_queue_worker.py -q`
Expected: FAIL（模块不存在）。

- [x] **Step 3: 实现 queue_worker**

```python
"""摄入队列的顺序处理入口（手动触发；不是后台守护进程）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from backend.wiki.ingest import IngestConfig, ingest_source
from backend.wiki.ingest_queue import IngestQueue
from backend.wiki.llm_context import make_llm_context

logger = logging.getLogger(__name__)


def _resolve_task_source(project_root: Path, source_path: str) -> Path:
    root = project_root.resolve()
    candidate = Path(source_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(root)
    return resolved


async def process_pending(project_root: Path, limit: int = 1) -> Dict[str, Any]:
    from backend.orchestration.llm_factory import load_llm_config_from_settings
    from backend.tools.workspace_index import load_embedding_config

    queue = IngestQueue(project_root)
    llm = load_llm_config_from_settings()
    emb = load_embedding_config()
    if llm is None or emb is None:
        return {
            "processed": [],
            "remaining": queue.get_status_summary(),
            "error": "LLM 或 embedding 模型未配置",
        }

    config = IngestConfig(
        llm_base_url=llm["base_url"], llm_api_key=llm["api_key"], llm_model=llm["model"],
        embed_base_url=emb["base_url"], embed_api_key=emb["api_key"], embed_model=emb["model"],
    )
    ctx = make_llm_context(llm["base_url"], llm["api_key"], llm["model"])
    processed: List[Dict[str, Any]] = []

    for _ in range(max(1, min(int(limit), 20))):
        task = queue.get_next_pending()
        if task is None:
            break
        if not queue.mark_processing(task.task_id):
            break
        try:
            source = _resolve_task_source(project_root, task.source_path)
            result = await ingest_source(config, project_root, source, ctx.llm_call, ctx.http_post)
            queue.mark_completed(task.task_id, {
                "wiki_page_path": result.wiki_page_path,
                "page_type": result.page_type,
            })
            processed.append({"task_id": task.task_id, "status": "completed",
                              "wiki_page_path": result.wiki_page_path})
        except Exception as exc:  # noqa: BLE001 - 单任务失败不中断队列
            message = str(exc)[:500] or type(exc).__name__
            queue.mark_failed(task.task_id, message)
            processed.append({"task_id": task.task_id, "status": "failed", "error": message})

    return {"processed": processed, "remaining": queue.get_status_summary()}
```

- [x] **Step 4: 路由 + 入队校验**

`queue_add` 在 authorize 后：

```python
    _, resolved = _resolve_source_file(req.project_path, req.source_path)
    source_path = str(resolved.relative_to(_canonical_project_root(req.project_path)))
    task_id = queue.add(source_path, max_retries=req.max_retries)
```

新增：

```python
class QueueProcessRequest(BaseModel):
    project_path: str
    limit: int = 1


@router.post("/ingest/queue/process")
async def queue_process(req: QueueProcessRequest):
    """按顺序处理 pending 任务（每个任务真实调用 ingest 管线）。"""
    from backend.wiki.queue_worker import process_pending

    project_root = _canonical_project_root(req.project_path)
    authorize_registered_project(req.project_path)
    limit = max(1, min(int(req.limit), 20))
    return await process_pending(project_root, limit=limit)
```

- [x] **Step 5: 运行后端测试**

Run: `... -m pytest backend/tests/unit/wiki/test_queue_worker.py backend/tests/unit/wiki/test_ingest_queue.py backend/tests/integration/test_wiki_queue_routes.py -q`
Expected: PASS。

- [x] **Step 6: 前端 API/store/UI**

`wiki.ts`：

```ts
export interface QueueProcessResult {
  processed: { task_id: string; status: 'completed' | 'failed'; wiki_page_path?: string; error?: string }[];
  remaining: QueueStatusSummary;
  error?: string;
}

export async function queueProcess(projectPath: string, limit = 1): Promise<QueueProcessResult> {
  return httpPost<QueueProcessResult>('/wiki/ingest/queue/process', {
    project_path: projectPath,
    limit,
  });
}
```

`queue-store.ts` 增加 action：

```ts
processQueue: async (projectPath, limit = 1) => {
  set({ loading: true, error: null });
  try {
    const result = await queueProcess(projectPath, limit);
    await get().loadStatus(projectPath);
    await get().loadTasks(projectPath);
    set({ loading: false });
    return result;
  } catch (err) {
    const message = err instanceof Error ? err.message : '处理队列失败';
    set({ error: message, loading: false });
    return null;
  }
},
```

`WikiQueuePanel` 在头部按钮区增加：

```tsx
<button
  type="button"
  data-testid="queue-process"
  disabled={loading || statusSummary.pending === 0}
  onClick={() => void processQueue(projectPath, 10)}
>
  处理队列（{statusSummary.pending}）
</button>
```

`SourcesTree` 新增可选 `onQueue?: (path: string) => void`，文件 action 区增加"加入队列"按钮；`SourcesView` 传入 `handleQueue`（调用 `useQueueStore.getState().addTask(project.path, path)`，成功 toast）。

- [x] **Step 7: 前端测试**

新增 store 测试：mock `queueProcess` 返回 1 completed + remaining，断言调用 `loadStatus/loadTasks` 并返回结果。`SourcesView.test.tsx` 增加"加入队列"调用 `addTask` 的断言。

- [x] **Step 8: 运行测试**

Run:
```bash
npm run test:run -- src/entities/wiki src/widgets/wiki/__tests__/SourcesView.test.tsx
npm run typecheck
```
Expected: PASS。

- [x] **Step 9: 提交**

```bash
git add backend/wiki/queue_worker.py backend/api/wiki_routes.py backend/tests/unit/wiki/test_queue_worker.py \
  src/shared/api-client/wiki.ts src/entities/wiki/queue-store.ts src/widgets/wiki/WikiQueuePanel.tsx \
  src/widgets/wiki/SourcesTree.tsx src/widgets/wiki/SourcesView.tsx src/entities/wiki/__tests__
git commit -m "feat(wiki): 队列处理入口与入队 UI 闭环"
```

---

## 回归与收尾

- [x] 后端全量相关测试：
  ```bash
  /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
    backend/tests/unit/wiki backend/tests/unit/api/test_zotero_routes.py \
    backend/tests/unit/zotero backend/tests/unit/test_zotero_sync_routes.py \
    backend/tests/integration/test_wiki_queue_routes.py -q
  ```
- [x] 前端相关测试 + 类型检查：
  ```bash
  npm run test:run -- src/widgets/wiki src/pages/settings/__tests__/ZoteroSyncPanel.test.tsx src/entities/wiki
  npm run typecheck
  ```
- [x] 文档：更新 `docs/technical/25-llm-wiki-integration.md`（来源导入、Research 面板、队列处理）、`docs/technical/104-zotero-llm-integration.md`（项目绑定 + 后台沉淀）、`docs/technical/106-wiki-completeness-optimization.md`（勾选对应项）。
- [x] 本计划文件保留在 `docs/plans/` 直至 PR 合并；合并后按文档规范并入技术手册并删除。
- [x] 完成后提醒：cherry-pick 本分支到 `main`，验证 py3.10 + pydantic 2.x。

## 风险与依赖

| 风险 | 缓解 |
|---|---|
| Zotero 真实库 schema 与测试夹具不同 | 归一化只依赖 REST 契约形状；单测覆盖 client 字符串/对象两种输入；建议用户用真实库手工验证一次 |
| 外部文件导入是新增写路径 | 复用 `copy_to_raw` 的 O_EXCL/no-follow；只读普通文件、大小上限、symlink fail-closed；补安全单测 |
| Deep Research 后端只支持 tavily/serpapi/searxng | 面板当前固定 Tavily 并明确提示；不做 bing/ddg 适配（P2） |
| 队列处理是同步 HTTP 长请求 | 前端按钮 loading + limit 上限 20；真正的后台守护进程留 P2 |
| win7/py3.8 兼容 | 全程用 `sage-backend-py38` 跑测试；不用 PEP 604/585 |
| 前端 worktree 无 node_modules | 首次 `npm ci` 后跑测试 |
