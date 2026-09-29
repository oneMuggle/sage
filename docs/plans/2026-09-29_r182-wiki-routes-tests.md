# R182 — `backend/api/wiki_routes.py` 单元测试（1655 行，此前零覆盖）

## 背景

`wiki_routes.py` 是 Wiki 子系统的全部 HTTP 面（文件 CRUD / 项目管理 / 搜索 /
lint / review / 引用定位 / 摄入队列 / chat 流 / clip / vision / recent-projects），
`git ls-files` 全仓无任何测试引用。本轮补齐单测，不改生产代码。

## 方案

- 纯 helper 直测：`_canonical_project_root` / `_path_is_within` /
  `_reject_symlink_components` / `_resolve_project_file` /
  `_resolve_source_file` / `_http_exception_from_llm` / `_cleanup_temp_paths` /
  `_check_project_impl`（路径安全核心，全部无 IO 依赖，symlink 用例在
  Windows 无符号链接权限时 skip）。
- 路由测试：`FastAPI() + include_router(wiki.router) + TestClient`，
  `authorize_registered_project` / `record_recent` / `load_recent` /
  `register_quietly` / `search_wiki` / `chat_with_wiki_stream` /
  `cascade_delete_source` / `caption_image` 按 namespace monkeypatch；
  IngestQueue / WikiLint / WikiReview / create_wiki_structure 走真实
  tmp_path 文件系统（JSON/纯 fs，无外部依赖）。
- 不覆盖：`/ingest/stream`、`/research`、`/communities`、`/insights`、
  `/graph`（重 LLM/图集成，mock 面过大，留待集成测试）；不影响本文件
  其余约 60% 路由与全部路径安全 helper 的覆盖。

## 验证

- `pytest tests/unit/api/test_wiki_routes.py`
- 仓库根 `ruff check backend/tests/unit/api/test_wiki_routes.py` + format

纯测试新增，无生产代码改动，不需要 win7 cherry-pick。
