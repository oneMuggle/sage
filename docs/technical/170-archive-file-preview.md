# 170 压缩包文件预览与浏览

> 面向开发者。压缩包读取层只依赖 Python 标准库，`release/win7`（Python 3.8）
> 与 main 共用同一实现；模块与路由不引入第三方压缩库。

## 定位

压缩包预览是**只读**能力：列出压缩包内条目、读取单个条目的内容，不落盘解压、
不提供提取/删除/写回。它服务于两个入口：

1. 消息内文件引用/文件链接 → 右栏文件预览；
2. AI 工具 `read_file` 读取压缩包内条目（`archive.zip::entry/path` 语法）。

与 Office 预览互不重叠：`.docx` / `.xlsx` / `.pptx` 的扩展名虽然底层是 zip，
但预览路由会先按 Office 三件套分派，不会进入压缩包分支。

## 模块与调用链

```
backend/data/archive_reader.py            # 读取层（仅标准库）
  ├─ backend/api/workspace_preview_routes.py   # HTTP 预览端点
  ├─ backend/tools/file_tool.py                # read_file 的 :: 语法 + list_dir 摘要
  └─ backend/tools/file_links.py               # 网页候选链接的 archive 分类（不读文件）

前端：
src/shared/api/workspaceApi.ts             # previewFile / previewArchiveEntry
src/widgets/chat/preview/FilePreviewPanel.tsx
src/widgets/chat/preview/FileContentRenderer.tsx  # ArchiveListingInline 静态清单
src/widgets/chat/preview/ArchivePreview.tsx       # 交互式浏览器（当前未被引用）

Electron：
electron/commandRoutes/sessions.ts         # workspace_preview_file → 后端 GET
```

`workspace_preview_routes.py` 的 router 无独立 prefix，由
`workspace_routes.py`（prefix `/sessions/{session_id}/workspace`）内嵌挂载，
最终路径为 `/api/v1/sessions/{session_id}/workspace/preview`。

## 读取层对外接口

`backend/data/archive_reader.py` 公开的符号（`__all__`）：

| 符号 | 签名 | 说明 |
| --- | --- | --- |
| `ArchiveEntry` | dataclass | 条目：`name`、`size`、`compressed_size`、`is_dir`、`mtime`（Unix 秒，目录为 `None`）、`is_archive` |
| `ArchiveInfo` | dataclass | 整体：`format`、`path`、`size`、`entry_count`、`total_uncompressed`、`entries`、`encrypted`、`truncated` |
| `detect_archive_kind` | `(path: Path) -> Optional[str]` | 判定格式标签，非压缩包返回 `None` |
| `read_archive_listing` | `(path: Path) -> ArchiveInfo` | 目录列表；文件不存在/格式不支持时抛 `ValueError` |
| `read_archive_entry` | `(path: Path, entry_path: str, max_bytes=MAX_ENTRY_SIZE_BYTES) -> bytes` | 读取单个条目原始字节 |
| `read_archive_entry_text` | `(path, entry_path, encoding="utf-8", max_bytes=...) -> str` | 在上者基础上解码 |
| `get_archive_summary` | `(path: Path) -> Dict[str, object]` | 文件清理场景摘要；失败返回 `{"ok": False, "error": ...}` |

`get_archive_summary` 成功时返回 `ok`、`format`、`size`、`entry_count`、
`total_uncompressed`、`encrypted`、`truncated`、`top_file_types`（按扩展名计数，
取前 10）。`top_file_types` 的键为小写后缀，无后缀文件归入 `(无扩展名)`。

`ArchiveEntry.name` 已去掉目录末尾的 `/`；目录判定以 `is_dir` 为准。
`is_archive` 仅表示条目的文件名命中压缩包扩展名（用于前端显示嵌套图标），
**不代表已递归解析**。

## 支持的格式矩阵

格式标签由扩展名决定，压缩包内条目读取全部走标准库：

| 类别 | 扩展名 | 返回的 `format` | 读取实现 | 目录列表 |
| --- | --- | --- | --- | --- |
| ZIP 家族 | `.zip` `.jar` `.war` `.ear` `.whl` `.epub` `.docx` `.xlsx` `.pptx` | `zip` | `zipfile.ZipFile` | 支持 |
| tar | `.tar` | `tar` | `tarfile`（`r:`） | 支持 |
| tar.gz | `.tar.gz` `.tgz` | `tar.gz` | `tarfile`（`r:gz`） | 支持 |
| tar.bz2 | `.tar.bz2` `.tbz2` | `tar.bz2` | `tarfile`（`r:bz2`） | 支持 |
| tar.xz | `.tar.xz` `.txz` | `tar.xz` | `tarfile`（`r:xz`） | 支持 |
| 单文件 gzip | `.gz` | `gzip` | `gzip.open` | 单条目 |
| 单文件 bzip2 | `.bz2` | `bzip2` | `bz2.open` | 单条目 |
| 单文件 xz | `.xz` | `xz` | `lzma.open` | 单条目 |
| 7z / rar | `.7z` `.rar` | — | **未实现** | 不支持 |

ZIP 家族的 `.docx/.xlsx/.pptx` 只影响 `archive_reader.detect_archive_kind`
的返回值；工作区预览路由会先用 `_OFFICE_PREVIEW_SUFFIXES` 分派到 Office
预览，因此用户正常点击 Office 文件不会看到 zip 条目树。

**7z/rar 的实际状态**：它们出现在多处"看起来支持"的清单里，但读取层没有
实现——`_EXT_FORMAT_MAP` 无这两项，`read_archive_listing` 会抛
`不是支持的压缩包格式`。这些清单位于：

- `workspace_preview_routes._ARCHIVE_PREVIEW_SUFFIXES`（会进入压缩包分支后失败）；
- `artifact_repo._EXT_KIND_MAP`（分类为 `archive`）；
- `file_links.FILE_EXTENSIONS` / `_MIME_KINDS`（网页下载候选分类为 `archive`）。

### 格式探测方式

`detect_archive_kind` 当前**只看扩展名**：`path.is_file()` 通过后，按
`_EXT_FORMAT_MAP` 的插入顺序做 `name.lower().endswith(ext)`，复合扩展名
（`.tar.gz` / `.tar.bz2` / `.tar.xz`）因排在 `.gz`/`.bz2`/`.xz` 之前而优先命中，
`.tgz/.tbz2/.txz` 归一到对应的 `tar.*` 标签。

模块里定义了魔数表 `_MAGIC_FORMAT`（`PK\x03\x04`、`PK\x05\x06`、`\x1f\x8b`、
`BZh`、`\xfd7zXZ\x00`），但**没有任何调用点**，属于预留常量。因此：

- 扩展名被改掉的压缩包（如 `a.zip.bak`）无法识别；
- 扩展名是 `.zip` 但内容不是 zip 时，`zipfile` 抛 `BadZipFile`，读取层转成
  `无效的 ZIP 文件`。

## 安全边界

读取层的限额常量（`archive_reader.py` 顶部）：

| 常量 | 值 | 作用 |
| --- | --- | --- |
| `MAX_ARCHIVE_SIZE_BYTES` | 500 MiB | 压缩包文件本身超过此值只返回空条目列表，`truncated=True` |
| `MAX_EXTRACTED_SIZE_BYTES` | 1 GiB | 列表阶段累计解压大小超限即截断（zip bomb 防护） |
| `MAX_ENTRY_SIZE_BYTES` | 50 MiB | 单条目读取上限 |
| `MAX_ENTRY_COUNT` | 10000 | 条目数上限，超出 `truncated=True` |

路径穿越防护在**读取条目时**执行（`_is_path_safe`）：空路径、以 `/` 或 `\`
开头、按 `/` 或 `\` 切分后含 `..` 段，一律拒绝并抛 `不安全的路径`。列表阶段
不校验条目名，所以恶意压缩包仍可能在清单里显示 `../evil`，但无法通过
`read_archive_entry` 读出。

加密检测只在 zip 列表阶段进行（`flag_bits & 0x1`，以及 `RuntimeError` 文本含
`password` 时置位），结果体现在 `ArchiveInfo.encrypted`；读取加密条目会抛
`条目已加密，需要密码`。单文件 gz/bz2/xz 恒为 `encrypted=False`。

其他限制：

- 单文件压缩格式的目录列表只有一个条目，`size` 与 `total_uncompressed` 都是
  **按压缩包大小 ×4 的估算值**（不解压无法得知真实大小）；
- 单文件格式读取时的大小闸门用的是**压缩后**文件大小，解压后大小不受
  `MAX_ENTRY_SIZE_BYTES` 约束；
- zip 列表读取加密判断、tar 家族不记录单条目压缩大小（`compressed_size=0`）。

`file_tool` 在读取层之上再叠一道：条目字节超过 `MAX_READ_SIZE_BYTES`（5 MiB）
时报 `file_too_large`；首 8 KiB 含 NUL 报 `binary_file`；文本按 UTF-8
`errors="replace"` 解码后按 `offset/limit` 做行切片。

## 压缩包内路径表示

存在两套等价但独立的接口，不要混用：

1. **AI 工具语法**：`archive.zip::internal/path`。
   `ReadFileTool.execute` 在虚拟路径翻译之后检测 `::`，用
   `path.split("::", 1)` 拆成压缩包路径与条目路径，两侧都必须非空；压缩包路径
   支持 `~` 展开。读取成功后返回：

   ```json
   {
     "total_lines": 120,
     "content": "...",
     "path": "src/main.py",
     "archive_source": "/abs/path/archive.zip",
     "truncated": false,
     "original_bytes": 3456
   }
   ```

   其中 `truncated` 恒为 `false`（行切片不标记截断），`path` 是条目名而非
   压缩包路径。

2. **HTTP 预览参数**：`entry` query 参数（见下一节）。它不是 `::` 字符串，
   而是在 `path` 指向压缩包时额外传入条目名。

注意 `::` 分支位于 `_check_read_access` / `check_sensitive_path` **之前**，
因此压缩包路径不经过工作区读权限与敏感路径守卫；读取能力边界由进程文件系统
权限决定。

## 预览 API 与 Electron IPC

### HTTP 端点

```
GET /api/v1/sessions/{session_id}/workspace/preview
    ?path=<工作区相对路径 | 绝对路径 | file:// | ~ 展开>
    &entry=<压缩包内条目，可选>
```

- `path` 与 `entry` 均 `max_length=1024`；`entry` 缺省表示列目录。
- 会话必须存在且已绑定工作区，否则分别返回 404 / 403；路径必须落在工作区内，
  越界返回 403 `path_outside_workspace`。裸文件名、`file://`、`~` 形态在解析
  失败时允许按**本会话**产物表回退（不跨会话）。
- 分派顺序：PDF → 图片 → Office 三件套 → LaTeX → 压缩包 → 文本。压缩包判定
  使用解析后文件的**后缀**是否在 `_ARCHIVE_PREVIEW_SUFFIXES`
  （`zip/jar/tar/gz/tgz/bz2/xz/7z/rar`），所以 `.tar.gz` 由 `.gz` 命中后再由
  `archive_reader` 细分为 `tar.gz`。

无 `entry` 时返回：

```json
{
  "ok": true,
  "kind": "archive",
  "format": "zip",
  "entry_count": 4,
  "total_uncompressed": 1234,
  "encrypted": false,
  "truncated": false,
  "entries": [
    {"name": "src/main.py", "size": 14, "compressed_size": 12,
     "is_dir": false, "mtime": 1763200000, "is_archive": false}
  ]
}
```

响应**不含**压缩包自身字节大小与磁盘路径。

有 `entry` 时按条目类型返回：

| 条目类型 | 返回 |
| --- | --- |
| 图片（`_IMAGE_PREVIEW_SUFFIXES`） | `{ok:true, kind:"image", data_url:"data:image/png;base64,..."}` |
| UTF-8 文本 | `{ok:true, kind:<classify_artifact 结果>, content:"...", truncated:bool}`，超过 `WORKSPACE_PREVIEW_CONTENT_CAP`（512 KiB）截断 |
| 非 UTF-8 | `{ok:false, code:"binary_file", error:"二进制文件不支持预览"}` |
| 读取失败（不存在/穿越/加密/超限） | `{ok:false, code:"archive_error", error:"..."}` |

与文本/LaTeX 分支不同（后者经 `_raise_preview_failure` 映射为 4xx/502），
压缩包与 Office 的读取失败都返回 HTTP 200 + `ok:false`；前端需读取 `ok`
字段判断。

### Electron 命令路由

桌面端没有为压缩包单开 IPC 通道，而是复用通用命令路由表
`electron/commandRoutes/sessions.ts` 的 `workspace_preview_file`：

```ts
workspace_preview_file: {
  method: 'GET',
  path: (a) => {
    const sessionId = encodeURIComponent(String(a.sessionId));
    const path = encodeURIComponent(String(a.path ?? ''));
    const entry = a.entry ? `&entry=${encodeURIComponent(String(a.entry))}` : '';
    return `/api/v1/sessions/${sessionId}/workspace/preview?path=${path}${entry}`;
  },
}
```

前端封装在 `src/shared/api/workspaceApi.ts`：

- `previewFile(sessionId, path)` —— 不传 `entry`，用于列目录与普通文件；
- `previewArchiveEntry(sessionId, path, entry)` —— 追加 `entry`，用于读条目。

## 前端渲染与接线状态

当前实际生效的链路是**静态清单**：

```
RightPanel（懒加载）
  └─ FilePreviewPanel(sessionId, path)
       ├─ workspaceApi.previewFile(...)
       └─ FileContentRenderer(content, name)
            └─ content.kind === 'archive' → ArchiveListingInline
```

`ArchiveListingInline`（`FileContentRenderer.tsx`）展示格式、条目数、解压总大小、
加密提示与条目清单：按 `/` 数量缩进、目录/嵌套压缩包/普通文件三种图标、文件
大小；**最多渲染前 200 条**，超出提示"仅显示前 200 条"。它不响应点击，不能
读取条目内容，也不展示后端返回的 `truncated`。

`ArchivePreview.tsx` 是完整的交互式浏览器（文件树展开/折叠、搜索过滤、右侧
条目预览，图片 / 代码 / JSON / Markdown 分支），通过
`workspaceApi.previewArchiveEntry` 拉取条目内容。但它虽然 `export`，**在 `src`
中没有任何 import**（`FileContentRenderer` 的注释也写明"此处展示静态清单"），
即当前处于未接线状态。

产物预览路径同样未接通压缩包：

- `src/features/artifacts/artifactApi.ts` 的 `ArtifactKind` 已包含 `'archive'`，
  `ArtifactRow` 也给了 `FileArchive` 图标；
- 但 `GET /sessions/{session_id}/artifacts/{artifact_id}/content`
  （`backend/api/artifact_routes.py`）没有 archive 分支，会落到
  `artifact_reader.read_text`，zip 字节 UTF-8 解码失败后返回
  `{ok:false, error:"binary file cannot be previewed"}`；
- `ArtifactViewer` 复用 `FileContentRenderer`，因此拿不到 `entries`。

`backend/tools/file_links.py` 的 `archive` 只是网页候选下载链接的分类标签
（供 `http_download` 使用），不参与本地压缩包读取。

## 相关文件

| 层面 | 文件 | 职责 |
| --- | --- | --- |
| 后端读取层 | `backend/data/archive_reader.py` | 格式判定、目录列表、条目读取、摘要、限额与路径安全 |
| 后端路由 | `backend/api/workspace_preview_routes.py` | `GET .../workspace/preview` 分派、`_preview_archive`、响应整形 |
| 路由挂载 | `backend/api/workspace_routes.py` | 以内嵌 router 形式挂载预览路由 |
| 类型注册 | `backend/data/artifact_repo.py` | `_EXT_KIND_MAP` 将压缩包扩展名分类为 `archive` |
| AI 工具 | `backend/tools/file_tool.py` | `::` 语法读取条目；`list_dir` 的 `archive_summary` |
| 网页链接分类 | `backend/tools/file_links.py` | 下载候选链接的 `archive` 标签（含 7z/rar MIME） |
| 产物路由（未接入） | `backend/api/artifact_routes.py` | 产物内容读取，无 archive 分支 |
| 前端 API | `src/shared/api/workspaceApi.ts` | `WorkspacePreviewContent`、`ArchiveEntryInfo`、两个预览方法 |
| 前端渲染 | `src/widgets/chat/preview/FileContentRenderer.tsx` | `ArchiveListingInline` 静态清单（200 条上限） |
| 前端交互组件（未接线） | `src/widgets/chat/preview/ArchivePreview.tsx` | 文件树 + 搜索 + 条目预览 |
| 前端面板 | `src/widgets/chat/preview/FilePreviewPanel.tsx`、`src/widgets/chat/RightPanel.tsx` | 右栏预览入口 |
| Electron | `electron/commandRoutes/sessions.ts` | `workspace_preview_file` 命令路由（含可选 `entry`） |
| 测试 | `backend/tests/data/test_archive_reader.py` | 读取层单测（格式判定/列表/读条目/摘要/穿越拦截） |

## 已知限制

- **魔数探测未生效**：`_MAGIC_FORMAT` 无调用点，格式完全依赖扩展名；改扩展名
  或伪装扩展名无法正确识别。
- **7z/rar 未实现**：路由、类型映射、链接分类都把它们标成 `archive`，但读取层
  不支持，预览返回 `archive_error`。`list_dir` 的摘要扩展名集合也不含它们。
- **交互式浏览器未接线**：`ArchivePreview.tsx` 未被任何模块引用；用户只能看到
  `ArchiveListingInline` 的静态前 200 条。
- **产物预览未接入**：`/artifacts/{id}/content` 无 archive 分支，压缩包产物预览
  报二进制错误。
- **无嵌套递归**：`is_archive` 只是文件名标记；点击嵌套压缩包条目会按普通字节
  读取并因二进制/解码失败告错，没有"最大嵌套 5 层"的展开实现。
- **无提取能力**：没有"提取选中文件"或"按类型批量提取"接口与前端按钮。
- **AI 上下文未自动注入目录结构**：`@` 引用压缩包不会自动带上条目列表；
  仅 `list_dir` 对每个压缩包附加 `archive_summary`（格式/条目数/解压大小）。
- **条目文本无编码回退**：预览与 `read_file` 均只按 UTF-8 解码（后者
  `errors="replace"`），GBK 等编码条目会显示乱码或失败。
- **单文件格式限额口径**：gz/bz2/xz 以压缩后大小判断 50 MiB 闸门，且列表大小
  为 ×4 估算值。
- **错误语义分层**：压缩包与 Office 失败返回 HTTP 200 + `ok:false`，文本/LaTeX
  失败经 `_raise_preview_failure` 映射为 4xx/502。
- **权限边界**：`read_file` 的 `::` 分支先于工作区读权限与敏感路径检查执行。
- **测试覆盖**：仅有读取层单测；工作区预览路由、`file_tool` 的 `::` 语法、
  `list_dir` 摘要、前端渲染均无自动化测试。
