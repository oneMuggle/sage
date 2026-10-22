# R88 规格与施工图：后端逻辑路径 POSIX 归一化（修复 Backend unit (Windows) 3 个失败）

> 基线：`origin/main` `978c18e04bd9ddb510afdd184e4f4e081d938879`（P136）；
> 分支：`fix/backend-windows-paths-r88`（独立新 PR，与 PR #2279 无关、不 stack）。

## 1. 背景与证据

main 的 CI run `39707772093`（P135）中，**Backend unit (Windows)** job `119591737016` failure：
3 failed、10925 passed、519 skipped。由于该 job non-blocking，`All Checks` 仍为 success，失败长期隐形。

| # | 失败用例 | 期望 | Windows 实际 |
|---|---|---|---|
| 1 | `test_project_wiki_generator.py::TestScanFiles::test_nested_directories` | `SourceFile.path` 含 `src/main.py` | `src\main.py` |
| 2 | `test_design_templates.py::TestDesignTemplateRegistry::test_assets_collects_css_and_js` | assets key 含 `assets/app.css` | `assets\app.css` |
| 3 | `test_design_studio.py::TestDesignStudio::test_generate_twice_does_not_collide_on_version` | `file_path.endswith("/v2.html")` | `...\v2.html` |

3 个用例在 Linux 全绿；根因一致：生产代码用 `str(Path)` 序列化**逻辑/存储路径**，Windows 原生分隔符为反斜杠。

## 2. 判准：什么路径应该归一化

- **逻辑标识路径**（项目相对路径 `SourceFile.path`、模板资产 key）→ 统一 POSIX（`Path.as_posix()`），跨平台稳定、JSON/引用匹配一致。
- **真实文件系统路径**（`absolute_path`、artifact `file_path`：repo 侧以 `Path(file_path)` 写盘，且 `test_generate_persists_expected_file_path` 契约为原生 `str(Path)` 全等）→ 保持原生不动；失败 #3 的问题在测试对原生路径硬编码 `/` 后缀，改测试为分隔符无关断言。

## 3. 施工图（2 个生产文件 + 1 个测试文件）

1. `backend/services/project_wiki_generator.py`（`_scan_files`）：`rel_path` 统一 `as_posix()`，同时用于 `path_filter` 入参与 `SourceFile.path`；`absolute_path` 保持原生。
2. `backend/design/templates.py`（`_load_template_from_dir`）：assets key 由 `str(relative_to(...))` 改为 `.as_posix()`。
3. `backend/tests/unit/test_design_studio.py`：`test_generate_twice_does_not_collide_on_version` 的 `endswith("/v2.html")` 改为 `Path(second.file_path).name == "v2.html"`；生产 `design_studio.py` 不动。
4. 附带（验证时发现、CI 不受影响）：`backend/tests/unit/wiki/test_ingest_queue.py` 第 71 行 `queue_file.read_text()` 缺 `encoding="utf-8"`，中文 Windows（默认 gbk）本地跑必挂 `UnicodeDecodeError`；生产 `ingest_queue.py:111` 已显式 utf-8。仅补测试侧编码。

## 4. 验证

- 远端 Windows Python312 定向跑 3 个失败用例 + 三个测试文件全量；
- PR CI 常规 checks 全绿（注意 PR 中 Backend Windows 可能 skipped，不能只看 PR checks —— 以定向 Windows 本地证据为准，合并后 main 的 Backend unit (Windows) job 应转 success，作为最终验收）。

## 5. 非目标

- 不碰 Win7 Sync（parity 对齐已有在途 PR #2274/#2237 等针对 `release/win7`，单主人原则不越界）。
- 不碰 Electron smoke（PR #2279 已在途修复新镜像 sandbox 崩溃，两 PR 独立）。
- 不做全仓库 `str(Path)` 大扫荡；仅修已实测失败且语义确为逻辑/存储路径的 4 处。
