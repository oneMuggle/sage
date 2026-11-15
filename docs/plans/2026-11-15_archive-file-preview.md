# 压缩包文件预览与浏览

> 日期: 2026-11-15
> 分支: feat/archive-preview
> 状态: 实施中

## 背景与目标

Sage 当前对压缩包文件（zip/tar/gz/7z/rar）零支持——用户引用或预览压缩包时
只能看到"二进制文件不支持预览"。文件清理场景也需要查看压缩包内容。

目标: 让用户和 AI 都能浏览压缩包内部结构、预览单个文件内容、提取需要的文件。

## 涉及的文件与模块

| 层面 | 文件 | 变更 |
|------|------|------|
| 后端核心 | `backend/data/archive_reader.py` | **新增** |
| 后端类型 | `backend/data/artifact_repo.py` | `_EXT_KIND_MAP` 新增 archive 类型 |
| 后端路由 | `backend/api/workspace_preview_routes.py` | 压缩包预览端点 |
| 前端类型 | `src/features/artifacts/artifactApi.ts` | ArtifactKind 新增 `'archive'` |
| 前端渲染 | `src/widgets/chat/preview/FileContentRenderer.tsx` | archive 分支 |
| 前端组件 | `src/widgets/chat/preview/ArchivePreview.tsx` | **新增** |
| AI 工具 | `backend/tools/file_tool.py` | read_file 支持压缩包内路径 |
| 文件链接 | `backend/tools/file_links.py` | 已有 archive 分类，复用 |

## 技术方案

### M1: 后端压缩包读取层 (`archive_reader.py`)

统一接口:
- `detect_archive_kind(path) -> str | None` — 按扩展名+魔数判定格式
- `read_archive_listing(path) -> list[ArchiveEntry]` — 目录列表
- `read_archive_entry(path, entry_path) -> dict` — 读取单文件内容

支持格式 (P0 纯标准库):
- `.zip` → `zipfile`
- `.tar` / `.tar.gz` / `.tgz` / `.tar.bz2` / `.tar.xz` → `tarfile`
- `.gz` / `.bz2` / `.xz` → 单文件解压读取

P2 (可选第三方):
- `.7z` → `py7zr`
- `.rar` → `rarfile`

安全约束:
- 路径穿越防护: entry path 不得含 `..` 或绝对路径
- 大小限制: 压缩包 >500MB 只返回目录结构
- 解压比例防护 (zip bomb): 解压后 >1GB 拒绝
- 加密: 检测后返回 `encrypted` 状态

### M2: 后端 API 扩展

`workspace_preview_routes.py` 新增:
```
GET /preview?path=foo.zip → { kind: "archive", format: "zip", entries: [...], entry_count: N }
GET /preview?path=foo.zip&entry=src/main.py → { kind: "code", content: "..." }
```

`artifact_repo.py` `_EXT_KIND_MAP` 新增:
```python
".zip": "archive", ".tar": "archive", ".gz": "archive", ".tgz": "archive",
".bz2": "archive", ".xz": "archive", ".7z": "archive", ".rar": "archive",
```

### M3: 前端压缩包浏览器

新增 `ArchivePreview.tsx`:
- 文件树展开/折叠
- 点击文件 → 预览内容（代码高亮、图片、PDF、Markdown）
- 嵌套压缩包 → 递归展开
- 搜索过滤文件名
- 提取按钮

### M4: AI 上下文集成

`file_tool.py` 的 `read_file` 支持 `path/to/archive.zip::internal/path` 语法。
AI 对话中 `@` 引用压缩包时自动注入目录结构。

### M5: 文件清理场景

文件管理器中压缩包显示:
- 条目数量、总大小、文件类型分布
- "查看内容"按钮展开目录
- 批量提取特定类型文件

## 实施步骤

- [ ] 步骤 1: M1 后端 `archive_reader.py` (zip + tar 家族)
- [ ] 步骤 2: M2 API 扩展 + artifact_repo 类型注册
- [ ] 步骤 3: M3 前端 ArchivePreview 组件
- [ ] 步骤 4: M4 AI 工具 read_file 支持压缩包内路径
- [ ] 步骤 5: M5 文件清理场景增强
- [ ] 步骤 6: 测试

## 风险评估

- **Python 3.8 兼容**: release/win7 分支用 py38，zipfile/tarfile 标准库 API 兼容
- **大文件性能**: 大压缩包目录列表需全量读取中央目录，可能慢 → 设超时
- **嵌套深度**: 嵌套压缩包递归展开可能很深 → 限制最大嵌套层数 (5)
