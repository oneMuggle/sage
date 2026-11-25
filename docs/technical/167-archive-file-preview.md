# 167 · 压缩包预览

## 1. 背景与定位

聊天里引用一个 `.zip` / `.tar.gz` 时，旧行为只会落到「二进制文件不支持预览」。压缩包预览把这类文件变成可浏览对象：后端列出条目、按需读取单个条目内容，前端渲染条目清单或文件树。

能力边界（以代码为准）：

- **只读、不落盘**：所有条目内容以 `bytes` 读进内存，没有任何「解压到磁盘」的路径或解压目标目录。
- **纯标准库**：`zipfile` / `tarfile` / `gzip` / `bz2` / `lzma`，不引入第三方解压库；7z / rar 目前不可读。
- **三种消费方**：工作区预览端点（前端）、`read_file` AI 工具（`archive.zip::entry` 语法）、`list_dir` 摘要（文件清理场景）。

职责分配：

| 层 | 位置 | 做什么 |
| --- | --- | --- |
| 读取核心 | `backend/data/archive_reader.py` | 格式判定、目录列表、条目读取、安全限额 |
| HTTP | `backend/api/workspace_preview_routes.py` | 按后缀分流到 `_preview_archive`，条目内容转成 kind |
| AI 工具 | `backend/tools/file_tool.py` | `read_file` 的 `::` 语法、`list_dir` 的 `archive_summary` |
| 前端 | `src/widgets/chat/preview/` | 静态清单（已接线）+ 交互式文件树组件（已实现但未接线） |

---

## 2. 后端 `archive_reader`

位置：`backend/data/archive_reader.py`。文件首行带 `# ruff: noqa: UP006, UP007, UP035`，理由是 release/win7 的 Python 3.8 兼容——只用 `typing.Optional/List/Dict/Tuple`，不写 `str | None`。

### 2.1 对外接口

`__all__` 导出的公开面：

| 名称 | 签名 | 行为 |
| --- | --- | --- |
| `detect_archive_kind` | `(path: Path) -> Optional[str]` | 返回格式标签（`zip` / `tar` / `tar.gz` / `gzip` / …）；非文件或未知格式返回 `None` |
| `read_archive_listing` | `(path: Path) -> ArchiveInfo` | 目录列表；失败抛 `ValueError` |
| `read_archive_entry` | `(path: Path, entry_path: str, max_bytes=50 MiB) -> bytes` | 读单个条目原始字节 |
| `read_archive_entry_text` | `(path, entry_path, encoding="utf-8", max_bytes=50 MiB) -> str` | 上面结果的解码封装 |
| `get_archive_summary` | `(path: Path) -> Dict[str, object]` | 摘要（格式 / 条目数 / 解压总大小 / 加密 / 截断 / Top10 扩展名），失败返回 `{"ok": False, "error": ...}` |
| `ArchiveEntry` / `ArchiveInfo` | dataclass | 条目与整体信息 |

`ArchiveEntry` 字段：`name`（压缩包内相对路径，无末尾斜杠）、`size`、`compressed_size`、`is_dir`、`mtime`（Unix 秒，目录为 `None`）、`is_archive`（文件名是否又是压缩包）。tar 不记录单条压缩大小，`compressed_size` 恒为 0。

`ArchiveInfo` 字段：`format`、`path`、`size`（压缩包文件大小）、`entry_count`、`total_uncompressed`、`entries`、`encrypted`、`truncated`。

### 2.2 内部分派

`read_archive_listing` / `read_archive_entry` 都先调 `detect_archive_kind`，再按格式标签分派：

- `zip` → `zipfile.ZipFile`
- `tar` / `tar.gz` / `tar.bz2` / `tar.xz` → `tarfile.open`，模式分别是 `r:` / `r:gz` / `r:bz2` / `r:xz`
- `gzip` / `bzip2` / `xz` → `gzip.open` / `bz2.open` / `lzma.open`，单文件整体读取

单文件压缩格式（`.gz` / `.bz2` / `.xz`）没有内部路径概念：`read_archive_entry` 会**忽略 `entry_path`**，直接返回整个解压内容。列表侧合成一个条目，名字是去掉压缩后缀后的文件名。

`get_archive_summary` 在 `read_archive_listing` 之上统计扩展名分布，给 `list_dir` 用。

---

## 3. 格式矩阵与格式探测

### 3.1 支持矩阵

「读列表」= `read_archive_listing` 能产出 `entries`；「读条目」= `read_archive_entry` 能返回内容。

| 格式 | 扩展名（`_EXT_FORMAT_MAP`） | 读列表 | 读条目 | 说明 |
| --- | --- | --- | --- | --- |
| zip | `.zip` `.jar` `.war` `.ear` `.whl` `.epub` `.docx` `.xlsx` `.pptx` | 支持 | 支持 | Office 三件套虽被识别为 `zip`，但工作区预览会先命中 Office 分支，走 office 预览 |
| tar | `.tar` | 支持 | 支持 | |
| tar.gz | `.tar.gz` `.tgz` | 支持 | 支持 | 统一返回格式标签 `tar.gz` |
| tar.bz2 | `.tar.bz2` `.tbz2` | 支持 | 支持 | |
| tar.xz | `.tar.xz` `.txz` | 支持 | 支持 | |
| gzip | `.gz` | 支持（单条目） | 支持（整文件） | 忽略 `entry_path` |
| bzip2 | `.bz2` | 支持（单条目） | 支持（整文件） | 忽略 `entry_path` |
| xz | `.xz` | 支持（单条目） | 支持（整文件） | 忽略 `entry_path` |
| 7z | — | **不支持** | **不支持** | 无 `py7zr` 依赖，`detect_archive_kind` 返回 `None` |
| rar | — | **不支持** | **不支持** | 无 `rarfile` 依赖，同上 |

匹配方式是对 `path.name.lower()` 做 `endswith`。`_EXT_FORMAT_MAP` 是 dict，插入顺序保证复合扩展名先命中：`.tar.gz` 排在 `.gz` 之前，所以 `foo.tar.gz` 得到 `tar.gz` 而不是 `gzip`。

### 3.2 magic byte 常量与生效范围

文件头常量定义在 `backend/data/archive_reader.py`：

```python
_MAGIC_FORMAT: Tuple[Tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),          # 空 zip
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ\x00", "xz"),
)
```

**当前实现状态**：`_MAGIC_FORMAT` 在全仓库只有定义处一处引用，`detect_archive_kind` 实际只查扩展名表，没有打开文件读头部。`detect_archive_kind` 的 docstring 写的是「按扩展名 + 魔数判定」，与实现不一致。因此：

- 真 zip 但扩展名是 `.txt` → `detect_archive_kind` 返回 `None`，报「不是支持的压缩包格式」。
- 扩展名 `.zip` 但内容不是 zip → 交给 `zipfile` 后抛 `BadZipFile`，`archive_reader` 转成 `ValueError("无效的 ZIP 文件")`。

为什么不能只靠扩展名：扩展名只是用户/系统给的标签，决定「用哪个标准库解析器」的是真实容器格式。标签与内容不符时，靠解析器自校验（`BadZipFile` / `TarError`）兜底只能得到格式无关的报错，无法反向识别真实格式。魔数字节常量正是为这种交叉校验准备的，但尚未接入判定链路。

### 3.3 多张扩展名表的差异

同一个「压缩包」概念在五处各有一张表，用途不同，集合也不完全相同：

| 表 | 位置 | 用途 | 是否含 7z/rar |
| --- | --- | --- | --- |
| `_EXT_FORMAT_MAP` | `backend/data/archive_reader.py` | 真正决定能否读取 | 否 |
| `_ARCHIVE_PREVIEW_SUFFIXES` | `backend/api/workspace_preview_routes.py` | 预览路由分流 | 是（会落到 `archive_error`） |
| `_EXT_KIND_MAP` | `backend/data/artifact_repo.py` | 产物 kind 分类（`archive`） | 是 |
| `_ARCHIVE_EXTS` | `backend/tools/file_tool.py` | `list_dir` 是否附带 `archive_summary` | 否 |
| `FILE_EXTENSIONS` / `_MIME_KINDS` | `backend/tools/file_links.py` | 网页候选文件链接嗅探打分 | 是 |

**能否读取只取决于第一张表**。其余表出现 7z/rar 只代表「被识别为压缩包」，不代表可预览——预览端点会把 `ValueError` 包成 `{"ok": False, "code": "archive_error", "error": ...}`。

---

## 4. 压缩包内路径表示与安全边界

### 4.1 条目路径

- 条目 `name` 是压缩包**内部相对路径**，例如 `src/utils/helper.py`。目录条目在源文件里通常带末尾 `/`，但导出时统一 `rstrip("/")`，靠 `is_dir` 区分。
- 目录判定：zip 看 `filename.endswith("/")`，tar 看 `member.isdir()`。
- 条目查找是**精确名称匹配**：zip 走 `zipfile.namelist()`，tar 走 `tarfile.getmember()`，都依次尝试 `entry_path`、`entry_path + "/"`、`entry_path.rstrip("/")` 三种写法以兼容目录斜杠差异。没有做 `./` 前缀归一化——tar 内若存成 `./src/main.py`，传 `src/main.py` 匹配不到。
- 不存在「解压目标路径」：读取结果直接是 `bytes`，不写磁盘。

### 4.2 AI 工具的 `::` 语法

`read_file` 用 `archive.zip::internal/path` 表示压缩包内条目：

```python
if "::" in path:
    return self._read_archive_entry(path, offset, limit)
```

`_read_archive_entry` 用 `path.split("::", 1)` 拆成「压缩包路径」与「条目名」，校验压缩包存在且是文件后调 `archive_reader.read_archive_entry`。返回值里 `path` 是条目名，`archive_source` 是压缩包的真实路径。条目内容额外走三道校验：

1. 首 `BINARY_SNIFF_BYTES` 含 NUL → `binary_file` 错误；
2. 解压后字节数超过 `MAX_READ_SIZE_BYTES`（5 MiB）→ `file_too_large` 错误；
3. 按 `utf-8` + `errors="replace"` 解码，再按 `offset` / `limit` 做行切片。

注意分派顺序：`::` 分支在 `_check_read_access`（工作区读取边界）与 `check_sensitive_path`（`.env` / 私钥守卫）之前 `return`，这两项检查对压缩包内条目语法不生效；压缩包路径本身与条目名的安全约束仅由 `archive_reader._is_path_safe` 及上述大小/二进制检查承担。

### 4.3 限额常量

`backend/data/archive_reader.py`：

| 常量 | 值 | 生效点 |
| --- | --- | --- |
| `MAX_ARCHIVE_SIZE_BYTES` | 500 MiB | 压缩包文件本身超限 → 只返回 `format/size`，`entries=[]`、`entry_count=0`、`truncated=True` |
| `MAX_EXTRACTED_SIZE_BYTES` | 1 GiB | 列表阶段累加条目声明的解压大小，超限即 `truncated=True` 并停止遍历（zip bomb 防护） |
| `MAX_ENTRY_COUNT` | 10000 | 条目数超限 → 截断并标记 `truncated` |
| `MAX_ENTRY_SIZE_BYTES` | 50 MiB | `read_archive_entry` 默认 `max_bytes`；zip 比较 `info.file_size`，tar 比较 `member.size` |

下游还有两道独立上限：

- 工作区预览文本条目按 `artifact_reader.WORKSPACE_PREVIEW_CONTENT_CAP`（512 KiB）截断并置 `truncated`；
- AI 工具 `read_file` 的上限为 `MAX_READ_SIZE_BYTES`（5 MiB），比 `archive_reader` 的 50 MiB 更严。

已知口径差异：单文件压缩格式（`.gz` / `.bz2` / `.xz`）的 `_read_single_compressed_entry` 拿**压缩文件本身**的大小与 `max_bytes` 比较，随后 `f.read()` 全量解压，没有对解压后字节数再做上限；其 `total_uncompressed` 也是用「压缩大小 × 4」估算，并非真实值。

### 4.4 路径穿越防护

`_is_path_safe(entry_path)` 同时拒绝三类：

```python
if not entry_path:
    return False                                   # 空
if entry_path.startswith("/") or entry_path.startswith("\\"):
    return False                                   # 绝对路径
if ".." in entry_path.split("/"):
    return False                                   # 任一段恰为 ..
if ".." in entry_path.split("\\"):
    return False                                   # 同上（Windows 分隔符）
return True
```

`read_archive_entry`（zip / tar 分支）在查条目之前先调它，不通过则 `ValueError(f"不安全的路径: {entry_path}")`。检查按 `/` 与 `\` 双分隔符切段，兼容 Windows 风格条目名。由于读取只做内存中的名称查找、不写文件系统，这一层防的是「用穿越路径拼出越界读取」而不是解压逃逸。

---

## 5. 前端 ArchivePreview 组件

### 5.1 数据来源与类型

预览 API：

```
GET /api/v1/sessions/{session_id}/workspace/preview?path=<archive>            → 目录列表
GET /api/v1/sessions/{session_id}/workspace/preview?path=<archive>&entry=<e>  → 条目内容
```

（`workspace_preview_routes` 无独立前缀，嵌入 `/sessions/{session_id}/workspace`，再由 `main.py` 统一加 `/api/v1`。Electron 侧通过 `workspace_preview_file` IPC 命令拼 URL，`entry` 非空才追加 `&entry=`。）

列表响应形状：

```ts
{ ok: true, kind: 'archive', format: string, entry_count: number,
  total_uncompressed: number, encrypted: boolean, truncated: boolean,
  entries: { name, size, compressed_size, is_dir, mtime, is_archive }[] }
```

条目响应的 `kind` 由条目扩展名决定：图片扩展名 → `kind: "image"` + `data_url`；UTF-8 可解码 → `classify_artifact(entry)` 得到的 kind（`code` / `json` / `markdown` / `text` 等）+ 截断后的 `content`；解码失败 → `ok: false, code: "binary_file"`。

前端类型定义在 `src/shared/api/workspaceApi.ts`（`WorkspacePreviewContent` 的 archive 字段 + `ArchiveEntryInfo`）与 `src/widgets/chat/preview/FileContentRenderer.tsx`（`PreviewContentPayload` + `ArchiveEntryInline`）。`workspaceApi.previewArchiveEntry(sessionId, path, entry)` 是对带 `entry` 版本端点的封装。

### 5.2 交互式组件

位置：`src/widgets/chat/preview/ArchivePreview.tsx`。

```ts
interface ArchivePreviewProps {
  sessionId: string;
  path: string;                        // 压缩包路径（工作区相对或绝对）
  data: WorkspacePreviewContent;       // 初始目录列表
}
```

内部状态与交互：

| 能力 | 实现 |
| --- | --- |
| 文件树 | `buildTree(entries)` 按 `name.split('/')` 建树，目录在前、同级按名称排序；父目录条目缺失的节点降级为根节点（孤儿兜底），深度用于缩进 |
| 展开 / 折叠 | `expanded: Set<string>` 保存展开目录名，`ChevronRight` / `ChevronDown` 切换；点击目录行即切换 |
| 搜索过滤 | 输入框按名称子串（小写）过滤，**目录始终保留**以便继续下钻；无匹配文件时目录仍显示 |
| 条目预览 | 点击文件行 → `workspaceApi.previewArchiveEntry` → 右侧面板；加载中显示「加载中...」 |
| 内容渲染 | 图片 → `<img src={data_url}>`；`code` / `json` → `ShikiCodeBlock`（`json` 固定 json，其余用 `langFromPath(entryName)`）；`markdown` → `Markdown tier="chat"`；其余 → `<pre>` |
| 头部信息 | 文件名、`entry_count` 条目、`total_uncompressed`；`encrypted` 时显示橙色提示 |
| 图标 | 目录蓝色文件夹、嵌套压缩包琥珀色 `FileArchive`、普通文件灰色 `FileIcon` |
| 尺寸 | `formatSize` 输出 B / KB / MB，条目按 `depth * 16px` 缩进 |

组件带有 `data-testid="archive-preview"`。

### 5.3 当前接线状态

`ArchivePreview` 目前**没有被任何页面或组件引用**（全仓库只有自身定义与 `FileContentRenderer` 里的一句注释）。实际渲染走的是 `FileContentRenderer` 的 `kind === 'archive'` 分支——`ArchiveListingInline`：

- 显示格式 / 条目数 / 解压大小 / 加密提示；
- **最多渲染前 200 条**，超出提示「仅显示前 200 条」；
- 只读静态清单，没有展开、搜索和条目点击预览。

也就是说：目录列表 + 条目内容两条 API 已完整可用，交互式浏览器组件代码已落地，但 UI 接线仍停在静态清单。渲染入口链路是 `FilePreviewPanel` → `FileContentRenderer` → `ArchiveListingInline`。

---

## 6. 相关文件

| 类别 | 路径 |
| --- | --- |
| 读取核心 | `backend/data/archive_reader.py` |
| 后端测试 | `backend/tests/data/test_archive_reader.py` |
| 预览路由 | `backend/api/workspace_preview_routes.py`（`_ARCHIVE_PREVIEW_SUFFIXES`、`_preview_archive`） |
| 路由挂载 | `backend/api/workspace_routes.py`、`backend/main.py` |
| 产物分类 | `backend/data/artifact_repo.py`（`_EXT_KIND_MAP`） |
| AI 工具 | `backend/tools/file_tool.py`（`read_file` 的 `::` 分支、`_read_archive_entry`、`_ARCHIVE_EXTS`、`_get_archive_summary`） |
| 网页链接嗅探 | `backend/tools/file_links.py`（`FILE_EXTENSIONS`、`_MIME_KINDS`） |
| 前端 API | `src/shared/api/workspaceApi.ts`、`src/features/artifacts/artifactApi.ts` |
| 前端组件 | `src/widgets/chat/preview/ArchivePreview.tsx`、`src/widgets/chat/preview/FileContentRenderer.tsx`、`src/widgets/chat/artifacts/ArtifactRow.tsx` |
| Electron IPC | `electron/commandRoutes/sessions.ts`（`workspace_preview_file`） |
