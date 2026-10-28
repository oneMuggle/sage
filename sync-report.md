# win7 auto-sync 报告

- 时间：2026-10-28T23:24:39
- source：`origin/main` @ `170589fa`
- target：`origin/release/win7` @ `4d76388d`
- 分支：`sync/win7-main-20261028`
- 待并入 commits：**985**
- 状态：**CONFLICT（172 个文件需人工处理）**

## 自动取 ours 的 D 类冲突（发布/打包冻结件）
- `.github/workflows/release-win7.yml`
- `backend/requirements-optional.txt`
- `backend/requirements-py38.txt`
- `backend/requirements.txt`
- `package-lock.json`
- `package.json`
- `scripts/bundle-python.ps1`
- `scripts/check_py38_compat.py`

## 需人工处理的冲突

| 文件 | 类别 | 建议 |
|------|------|------|
| `.github/dependency-audit-policy.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `.github/workflows/ci.yml` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `.github/workflows/release.yml` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `.github/workflows/win7-sync.yml` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `CHANGELOG.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `architecture-baseline.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/adapters/out/memory/adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/adapters/out/skill/inproc.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/adapters/out/storage/memory_adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/adapters/out/tool/inproc_adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/agents/profiles.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/api/chat_attachment_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/chat_session_lifecycle.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/chat_stream_support.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/diagnostic_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/git_status_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/hooks_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/legacy_memory_list_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/legacy_memory_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/legacy_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/llm_proxy_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/office_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/permission_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/project_ai_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/settings_models.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/wiki_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/worktree_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/zotero_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/application/kernel/events.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/application/services/chat_service.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/chat/topic_detection.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/cli/doctor.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/core/legacy/agent.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/core/legacy/llm_total_timeout.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/data/agent_repo.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/database.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/design_repo.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/migrations/runner.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/session_event_backfill.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/session_repo.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/settings_canonicalizer.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/design/design_studio.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/standalone_bundler.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/systems.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/templates.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/hooks/runner.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/main.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/mcp/discovery.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/mcp/oauth.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/mcp/oauth_loopback.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/mcp/oauth_store.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/mcp/servers/zotero/server.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/mcp/workspace_scope.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/async_extractor.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/episodic.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/extractor.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/manager.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/model_catalog/pricing.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/model_catalog/probes.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/model_catalog/repository.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/model_catalog/resolver.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/model_catalog/schemas.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/model_catalog/snapshots.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/model_catalog/sources.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/model_catalog/transfer.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/ppt_template.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/toc_refresh.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/orchestration/orch_settings.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/plugins/lifecycle.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/plugins/manifest.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/plugins/registry.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/remote_mcp/listener.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/remote_mcp/protocol.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/remote_mcp/tools.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/scheduler/evolution.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/services/arena_accounts.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/services/backup_service.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/services/permission_gate.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/services/project_wiki_generator.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/services/trust_escalation.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/services/usage_tracker.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/services/workspace_info.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/skills/discovery.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/skills/enhanced_registry.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/skills/skill_md/script_runner.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/skills/skill_md/skills_dir_policy.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/skills/skill_md/validation.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/contract/test_settings_schema_parity.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/integration/test_evolution_scheduler_runs.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/integration/test_web_access_journey.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/api/test_search_routes.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_adapter_tag_graph.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_browser_tool.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_credential_vault.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_hooks_builtin.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_hooks_feedback.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_hooks_lifecycle.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_inproc_tool_adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_legacy_routes_async_safety.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_mcp_oauth.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_mcp_oauth_loopback.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_memory_adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_orch_settings.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_project_advisor.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_project_knowledge_extractor.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_project_task_decomposer.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_py38_compat_gate.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_remote_mcp_server.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_safe_writer.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_shell_resolver.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_tool_policy.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_vision_ingest_security.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_web_cache.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_web_tool.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/tools/test_python_adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/tools/test_runtime_tool_contract.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/agent_tool.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/browser_cdp.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/config_tool.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/credential_vault.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/executor.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/registry.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/shell_resolver.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/web_render.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/utils/py_compat.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/wiki/chat.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/wiki/literature_aggregator.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/wiki/meetings_extractor.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/wiki/review.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/zotero/client.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/zotero/exceptions.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-10-26_session-rules-manage-r106.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-10-27_planner-scout-iteration-knobs.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-10-28_performance-stats.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/plugin-evo-index.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/15-quality-gates.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/97-plugin-manifest.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/user-manual/20-settings.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/commandRoutes/chat.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/ipc-manifest.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/main.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/preload.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/runtime-check.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/update/providers/genericHttp.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/update/providers/gitee.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/update/providers/github.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/update/providers/gitlab.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `scripts/architecture-check.mjs` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `scripts/check_dependency_audit.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `scripts/silent-exceptions-baseline.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `scripts/tests/test_check_dependency_audit.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/entities/setting/storage.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/entities/setting/types.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/features/send-message/__tests__/useChat.taskBoardEvents.test.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/pages/settings/ModelsTab.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/pages/settings/PluginsTab.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/pages/settings/settingsSearchIndex.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/api/types.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/api/types/chatAndEventTypes.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/lib/i18n/locales/en/settingsAndModels.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/lib/i18n/locales/en/workspaceAndTools.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/lib/i18n/locales/zh/settingsAndModels.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/lib/i18n/locales/zh/workspaceAndTools.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/lib/store.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/types/electron-api.d.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/widgets/chat/WorkspaceBranchPicker.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/widgets/chat/__tests__/Message.test.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/widgets/chat/progress/TaskTreeSection.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/widgets/session/SessionItem.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/widgets/settings/HookHistoryPanel.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |

处理步骤：`git checkout sync/win7-main-20261028` → 解决冲突 → `python scripts/py38_compat_rewrite.py backend packages/sage-core` → `python scripts/check_py38_compat.py` → 提交。


> 由 `scripts/win7/auto_sync.py` 生成。合并后请跑完整 pytest / vitest，并与 `docs/win7-sync/parity.md` 中的宿主环境性失败清单对照。