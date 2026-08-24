# Task 1 Fix Round 1 Report

状态：DONE
日期：2026-08-24
分支：`worktree-agent-a6879777a8b23daec`
基线：`f643f175`

## 修复内容

- 已将 Task 1 commit rebase 到 `f643f175`，保留 Task 0 history。
- `backend/requirements-py38.txt` 增加 `backports.zoneinfo>=0.2.1; python_version<"3.9"`、`tzdata>=2024.1; sys_platform=="win32"`、`certifi>=2024.7.4`。
- 新增 `backend/api/settings_models.py`：`EndpointPayload` 使用 `Literal["openai-compatible", "anthropic", "gemini", "ollama"]`，并以 `List[EndpointPayload]` 收紧 settings payload。`class Config` 保持 Pydantic 1/2 兼容。
- 将 timezone、protocol、localModelPath value validation 下沉到 `settings_canonicalizer.py`，避免 Pydantic 2-only `field_validator`；legacy endpoint payload 保持 `extra="allow"`，让未知字段继续由 canonicalizer 返回历史 HTTP 400。
- `localModelPath` 增加平台规则：Win32 拒绝 `/`，Linux/macOS 拒绝 `\\`。
- `_is_ca_bundle_available()` 增加 `ssl.get_default_verify_paths().cafile/capath` 系统 CA fallback；`_is_tls_certificate_error()` 优先沿异常 cause/context 检测 `ssl.SSLCertVerificationError`，保留字符串 fallback。
- TLS 集成测试强制 `detail["type"] == "tls_certificate_failed"`。
- `mergeWithDefaults()` 对 endpoints 与 modelSelections 使用 `deepMerge`，不再整体替换 endpoints。
- 新增 canonicalizer、TLS helper、storage merge 回归测试。

## 验证结果

后端 focused matrix（`sage-backend` 环境）：

```text
92 passed, 8 warnings
```

覆盖：canonicalizer、TLS diagnostics、LLM proxy integration、legacy settings integration。

Hex settings endpoint：

```text
API_MODE=hex pytest backend/tests/integration/test_settings_endpoint.py backend/tests/integration/test_settings_route_hex.py
4 passed
```

默认 legacy settings endpoint：

```text
pytest backend/tests/integration/test_settings_endpoint.py
2 skipped (API_MODE=legacy 的预期行为)
```

前端 storage：

```text
npm test -- --run src/entities/setting/__tests__/storage.test.ts
16 passed
```

TypeScript 与 lint：

```text
npm run typecheck       通过
npm run lint            0 errors, 5 个既有 warning
```

其它检查：

```text
python -m compileall -q backend/api backend/data       通过
git diff --check                                      通过
```

## 剩余问题

无本轮阻塞问题。lint 的 5 个 warning 位于未改动的 ChatInput、TodoListSection、CommandPalette 文件；Pydantic 2 对双版本 `class Config` 会产生兼容层 deprecation warning，这是为 Python 3.8/Pydantic 1 保持同一模型定义的有意取舍。
