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

## Task 1 Fix Round 2（2026-08-24）

状态：DONE

### 本轮修复

- `backend/api/settings_models.py` 全部字段改为 Python 3.8 可解析的 `Optional`/`List`/`Literal` 注解，移除所有 PEP 604 `|`。
- 新增 `model_dump_compat()`：Pydantic 2 优先 `model_dump()`，Pydantic 1 fallback `dict()`；hex/legacy settings routes 的序列化均改用该 helper。
- 保留 `EndpointPayload.protocol` 的 `Literal` 约束、timezone/protocol/localModelPath canonicalizer 校验和 Pydantic 1/2 双版本 `class Config`。
- `_proxy_streaming` 在首 chunk 后上游异常时记录结构化 `llm_proxy_stream_error` teardown 日志，把异常传给 context manager，并确保连接只关闭一次；不尝试二次写 HTTP status。
- 新增首 chunk 后断流回归测试，锁定已发送 chunk、异常透传和 deterministic close。
- 新增 `model_dump_compat` 的 v2 优先与 v1-shaped fallback 测试。

### 验证

```text
pytest backend/tests/unit/test_settings_canonicalizer.py backend/tests/integration/test_llm_proxy_routes.py
73 passed

pytest backend/tests/integration/test_llm_proxy_routes.py
25 passed

API_MODE=hex pytest backend/tests/integration/test_settings_endpoint.py backend/tests/integration/test_settings_route_hex.py
4 passed

pytest backend/tests/integration/test_settings_route_legacy.py
10 passed

npm run typecheck
通过

npm run lint
0 errors, 5 个既有 warnings

ruff check（本轮 Python 改动文件）
All checks passed

compileall + git diff --check
通过
```

当前 conda 环境为 `sage-backend`（Python 3.10），本机未提供 `sage-backend-py38`，因此未直接启动 Python 3.8；共享模型已通过静态扫描确认无 PEP 604 注解，并使用 Python 3.8 兼容 typing 写法。Pydantic 1 的运行时 fallback 由 helper 单测覆盖，未修改 `release/win7`。

### 剩余问题

无阻塞问题。lint 的 5 个 warning 均位于本轮未修改的 ChatInput、TodoListSection、CommandPalette 文件；Pydantic 2 的 `class Config` deprecation warning 是为 Pydantic 1/2 共用模型而保留的兼容写法。
