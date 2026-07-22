# Sage Settings Schema 规范化（snake↔camel 翻译 + GET/PUT 白名单 + Frontend deep-merge）— Design Spec

- **Date:** 2026-07-22
- **Branch(es):** `fix/settings-schema-canonicalization` (从 `main` 切) + `fix/win7-settings-schema-canonicalization`（从 `release/win7` 切，main squash-cherry-pick）
- **Status:** Designed（待用户 review spec → writing-plans → 实施）
- **Author:** Claude（与用户共同 brainstorming 6 节达成）

## 1. 背景与目标

### 1.1 问题

本机启动 Electron 后侧栏左下角显示"未配置"。诊断后定位到三层叠加：

1. **DB 历史 snake_case 污染**：早期客户端按 snake_case schema 直接写入 `data/sage.db` 的 `preferences.app_settings` 行（`base_url` / `api_key` / `endpoint_id` / `model_selections` / `chat_model` 等），从未被翻译成前端 `AppSettings` 用的 camelCase。
2. **后端 legacy schema 接受一切 `extra`**：`backend/api/legacy_routes.py` 的 `LegacySettingsRequest(class Config: extra = "allow")` 与 hex 路由同款的 `extra="allow"`，让前端的 camelCase payload 能"裸透传"进 DB，但**没做 snake↔camel 翻译**——结果是 DB 里两种命名同时存在。
3. **前端 `loadSettings` 浅 merge**：`src/entities/setting/storage.ts:108` 用 `{ ...local, ...remote }` 让陈旧 remote 永远覆盖 local，且 `mergeWithDefaults` 的字段级 fallback（`partial.endpoints ?? DEFAULT.endpoints`）只看局部键名冲突，看不到嵌套字段的命名差异。

效应：`resolveEndpoint(chatModel, endpoints)` 找到的是 snake_case 端点，对象**没有 `baseUrl` / `apiKey` 字段**——只有 `base_url` / `api_key`。Sidebar `Sidebar.tsx:62` 的 `if (!chatEndpoint?.baseUrl || !chatEndpoint.apiKey)` 永远 true，左下角圆点永久 `not-configured`，Chat 顶部黄色告警条 (`Chat.tsx:157`) 永远显示。

### 1.2 目标

1. 后端 `GET /api/v1/settings` 永远返回 camelCase，与前端 `AppSettings` 类型 1:1 对齐。
2. 后端 `PUT /api/v1/settings` 严格按 AppSettings 白名单收口，不再 `extra="allow"` 接受未知字段。
3. 历史 snake_case 数据在 GET 时**即时翻译**到 camelCase 返回（不需一次性迁移，落盘时由下一次 PUT 自然覆盖）。
4. 前端 `loadSettings` 改成 deep-merge + 字段级冲突告警，避免陈旧 remote 单方面覆盖 local。
5. 双分支（`main` + `release/win7`）都修复；走项目惯例的 main 提 PR + win7 单 squash cherry-pick。
6. 不引入一次性 migration 脚本（用户决定）——读侧翻译足够。

### 1.3 非目标

- 不引入一次性 `scripts/migrate_settings_schema.py`（YAGNI；GET 翻译已覆盖历史数据）
- 不更换 localStorage / electron-store / IndexedDB（YAGNI）
- 不实现 CRDT / vector clock 多机冲突（单机 Electron 工具不需要）
- 不修改 `Config.extra="allow"` 之外的 hex/legacy schema 字段定义（仅收紧到白名单 + 加翻译层）
- 不动 `backend/data/database.py`（默认 DB 路径逻辑不变）
- 不改 settings.ts UI 层（`/settings` 各 Tab 已有正确 camelCase 操作）

## 2. 架构

```
┌──────────────────────────────────────────────────────────────┐
│ Renderer (Electron)                                          │
│  src/entities/setting/types.ts → AppSettings (单一事实源)    │
│  src/entities/setting/storage.ts → loadSettings deep-merge   │
└───────────────┬──────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│ FastAPI backend                                              │
│  legacy_routes.{legacy_get_settings, legacy_update_settings}│
│              → settings_canonicalizer.to_camel/from_camel    │
│  hex_routes.{get_settings, update_settings}                  │
│              → 同上                                          │
│              ↓                                               │
│  SettingsRepository.set_json / get_json (不变)               │
│              ↓                                               │
│  SQLite preferences.app_settings (现在永久存 camelCase)      │
└──────────────────────────────────────────────────────────────┘
```

**SoT 决策**：前端 `AppSettings`（camelCase）是契约唯一来源；后端 PUT/GET 必须与其对齐。DB 存储格式 = camelCase（落盘后即规范）。历史残留 snake_case 在 GET 翻译层吸收，无需落盘改写。

## 3. Components & Interfaces

### 3.1 新增 `backend/data/settings_canonicalizer.py`

纯函数模块，无外部依赖，独立可测。

```python
ALIASES: Dict[str, str] = {
    # 顶层
    "model_selections": "modelSelections",
    "max_context": "maxContext",
    "proxy_mode": "proxyMode",
    "proxy_url": "proxyUrl",
    "tls_version": "tlsVersion",
    "auto_memory": "autoMemory",
    "confirm_delete": "confirmDelete",
    "compact_mode": "compactMode",
    # modelSelections 子层
    "chat_model": "chatModel",
    "vision_model": "visionModel",
    "embedding_model": "embeddingModel",
    # EndpointConfig 子层
    "base_url": "baseUrl",
    "api_key": "apiKey",
    "discovered_models": "discoveredModels",
    "last_discovered_at": "lastDiscoveredAt",
    # ModelSelection 子层
    "endpoint_id": "endpointId",
    "model_id": "modelId",
}

# 与 src/entities/setting/types.ts:AppSettings 锁死,后续修改 AppSettings 字段必须同步
LEGAL_TOP_KEYS: FrozenSet[str] = frozenset({
    # General
    "streaming", "autoMemory", "confirmDelete", "compactMode",
    # Endpoint & Model
    "endpoints", "modelSelections", "maxContext", "temperature",
    # Network
    "proxyMode", "proxyUrl", "tlsVersion",
    # Wiki
    "wiki",
    # Internal
    "version",
})  # 13 个顶层字段; 增量同步 AppSettings 时须更新此处
LEGAL_ENDPOINT_KEYS: FrozenSet[str] = frozenset({
    "id", "name", "baseUrl", "apiKey", "discoveredModels", "lastDiscoveredAt",
})  # EndpointConfig 6 个
LEGAL_MODEL_SELECTION_KEYS: FrozenSet[str] = frozenset({"endpointId", "modelId"})

def to_camel(value: Any) -> Any:
    """dict 递归按 ALIASES 翻译 + list 元素递归 + 其他原样"""

def from_camel(value: Any) -> Any:
    """反向, ALIASES.items() 反转得到逆向表"""

def validate_settings_shape(settings: dict) -> None:
    """未在 LEGAL_*_KEYS → raise ValueError """

def detect_legacy_snake_pollution(settings: dict) -> List[str]:
    """返回发现的 snake_case 字段路径列表 (开发模式 log.warning) """
```

### 3.2 修改 `backend/api/legacy_routes.py`

```python
async def legacy_update_settings(req: LegacySettingsRequest):
    payload = req.dict(exclude_none=True)  # 仅 3 schema 字段 (api_base_url/api_key/model)
    existing = SettingsRepository().get_json("app_settings") or {}
    merged = {**existing, **payload}
    camel_merged = settings_canonicalizer.to_camel(merged)
    settings_canonicalizer.validate_settings_shape(camel_merged)
    SettingsRepository().set_json("app_settings", camel_merged, category="general")

async def legacy_get_settings() -> Optional[dict]:
    raw = SettingsRepository().get_json("app_settings")
    if raw is None: return None
    settings_canonicalizer.detect_legacy_snake_pollution(raw)  # dev-only warn
    return settings_canonicalizer.to_camel(raw)
```

### 3.3 修改 `backend/api/hex_routes.py` 中 `SettingsRequest`

`class Config: extra = "allow"` → **删除**，改用 `model_config = ConfigDict(extra="forbid")` (pydantic v2) 或 `class Config: extra = "forbid"` (pydantic v1, win7)。

两个 PUT 入口 (`update_settings`) 同样套 `to_camel(merged) → validate_settings_shape → set_json` 链。

### 3.4 修改 `src/entities/setting/storage.ts`

```ts
type ConflictPolicy = 'remote-wins' | 'local-wins' | 'merge';

function deepMerge<T>(base: T, override: T, policy: ConflictPolicy = 'remote-wins'): T {
  // 1. 双方都是对象 → 字段级递归
  // 2. 同 id array items → 按 id 去重 (例 endpoints[])
  // 3. 叶节点 → override 完全替换
  // 4. 冲突 (同 id 不同内容) → console.warn + policy 决策
}

export async function loadSettings(): Promise<AppSettings> {
  const remote = await settingsClient.getSettings();  // 必然 camelCase
  const local = readLocalCacheSync();
  if (!remote && !local) return mergeWithDefaults({});
  if (!remote) return mergeWithDefaults(local!);
  if (!local) return mergeWithDefaults(remote);
  const merged = deepMerge(local, remote);
  const final = mergeWithDefaults(merged);
  writeLocalCacheSync(final);  // 把清洗过的"权威"持久化回 local
  return final;
}
```

`updateSettings` / `saveSettings` 不变（已正确双写 localStorage + IPC）。

### 3.5 新增 / 修改测试

| 文件 | 状态 | 目标 |
|---|---|---|
| `backend/tests/unit/test_settings_canonicalizer.py` | 新增 | ≥15 cases: 嵌套 dict / list 递归 / round-trip / 白名单拒绝 / snake 污染检测 |
| `backend/tests/integration/test_settings_route_legacy.py` | 修改 | 既有 `test_put_settings_then_get` 断言更新为 GET 返回 camelCase；新增 5 cases |
| `src/entities/setting/__tests__/storage-deepmerge.test.ts` | 新增 | ≥10 cases: deepMerge 行为 + 冲突检测 + DEFAULT 兜底 |
| `tests/e2e/settings-schema-canonicalization.e2e.ts` | 新增 | Playwright spec: addInitScript 注入历史 snake → 验证清洗行为 (复用现有 e2e 模式) |

## 4. Data Flow

### 4.1 前端 mount → `loadSettings`

```
mount → useSettings() → loadSettings()
  ├─ 1. remote = await settingsClient.getSettings()
  │    GET /api/v1/settings → 后端 to_camel → 返回 camelCase
  ├─ 2. local = readLocalCacheSync()  // localStorage['sage-settings']
  ├─ 3. 三 cases:
  │   ① remote && !local     → mergeWithDefaults(remote)
  │   ② !remote && local     → mergeWithDefaults(local) + Toast "设置未同步"
  │   ③ remote && local      → deepMerge(local, remote, 'remote-wins')
  ├─ 4. deepMerge 冲突检测:
  │   - endpoints[] 同 id: deep 字段比较 → 不同则 console.warn + Toast + 仍 remote 胜
  ├─ 5. writeLocalCacheSync(merged)  // 把权威远程值覆盖回 localStorage
  └─ 6. return merged  → React state
```

### 4.2 UI 保存 → `updateSettings({...})`

```
UI 保存 → updateSettings(partial) [useSettings]
  ├─ 1. setSettings((prev) => ({ ...prev, ...partial }))   // React state 立刻
  └─ 2. await saveSettings(partial)
       ├─ writeLocalCacheSync(merged)                       // localStorage camelCase
       └─ settingsClient.setSettings(partial)
            └─ PUT /api/v1/settings
                 ├─ payload = req.dict(exclude_none=True)  // 3 schema 字段
                 ├─ existing = repo.get_json() or {}
                 ├─ merged = {**existing, **payload}
                 ├─ camel_merged = to_camel(merged)
                 ├─ validate_settings_shape(camel_merged)   // fail-fast 400
                 └─ repo.set_json(camel_merged, 'general')
```

### 4.3 Sidebar 重算

```
settings 变化 → Sidebar useEffect [chatEndpoint?.baseUrl, chatEndpoint.apiKey, chatModel.modelId]
  ├─ chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints)
  ├─ if (!chatEndpoint?.baseUrl || !chatEndpoint.apiKey):
  │     setConnectionStatus('not-configured'); return
  └─ testEndpointConnection(...)  → setConnectionStatus('connected' | 'error')
```

### 4.4 关键不变式

| 保证 | 实现 |
|---|---|
| DB 永远 camelCase (新写) | PUT 翻译后落盘 |
| GET 永远 camelCase | 取出时即时翻译 |
| 前端不被脏数据踩 | deepMerge + 冲突告警 |
| 旧 snake 数据兼容 | GET 即时翻译，无需落盘改写 |
| 多机共享 DB 一致 | remote wins over local |

## 5. Error Handling

### E1 — 后端 PUT
| 失败 | 修后行为 |
|---|---|
| 未知字段 (frontend 误塞) | `validate_settings_shape` → 400 `{"detail": "unknown field 'foo'"}` |
| 类型错 | Pydantic 自动 422 |
| snake_case 残留 (老 IPC) | `to_camel()` 后整树翻译 |
| DB 写入失败 | 5xx + `settings_persist_failed` 审计事件 |
| `app_settings` JSON 损坏 (手改文件) | catch `ValueError` → 视为 null → 触发前端 DEFAULT 路径 |

### E2 — 后端 GET
| 失败 | 修后行为 |
|---|---|
| DB 行不存在 | 返回 `null`（不变） |
| DB 行 JSON 损坏 | catch `ValueError` → 返回 `null`（统一 fallback） |
| `to_camel()` 遇未知字段 | `detect_legacy_snake_pollution` → `logger.warning` 但仍返回 |

### E3 — 前端 mount
| 失败 | 修后行为 |
|---|---|
| 后端 5xx / 超时 | `console.error` + Toast "设置未能同步到后端"；走 localStorage |
| 后端返回未知字段 (服务端被扩展) | `validateRemoteShape` → `console.error` + 仍用 |
| localStorage 解析失败 | DEFAULT（不变） |
| localStorage 中有老 snake_case | deepMerge 检测 + `console.warn` + remote 胜（最终清掉 local 污染） |
| 同 id endpoint 字段冲突 | `console.warn` + Toast "设置冲突，采用服务端值" |

### E4 — 前端保存
| 失败 | 修后行为 |
|---|---|
| IPC 5xx / 超时 | `console.error` + Toast（仍 update React state，不阻塞 UI） |
| localStorage quota | `console.error` 不阻塞 UI |

### E5 — Sidebar 连接测试
| 失败 | 修后行为 |
|---|---|
| `apiKey` 401/403 | `connectionStatus='error'` + Toast "鉴权失败" |
| 网络 DNS / CORS | catch → `error`（不变） |

### E6 — 开发期可观测性

- `backend/data/settings_canonicalizer.py` 含 `DEBUG_LEGACY_POLLUTION` env 开关；默认 False，开启后 `detect_legacy_snake_pollution` 在生产也强制 log
- 测试套件 fixture `clean_app_settings_db`：每测试开始前 `DELETE FROM preferences WHERE key='app_settings'`

## 6. Testing Strategy

### T1 — `test_settings_canonicalizer.py` (≥15 cases)
to_camel 嵌套 dict / list 递归 / round-trip / None + 空 dict + 空 list / validate 白名单拒绝 / detect_legacy_snake_pollution nested 检测 / ALIASES 双向一一对应无丢失

### T2 — `test_settings_route_legacy.py` (修改 + 5 新)
既有 `test_put_settings_then_get` 改断言为 GET 返回 camelCase；新增 `test_get_translates_snake_to_camel_for_legacy_data` / `test_put_with_unknown_field_rejected_400` / `test_put_with_snake_field_translated` / `test_round_trip_preserves_discovered_models_array` / `test_get_returns_null_on_corrupted_json`

### T3 — `storage-deepmerge.test.ts` (≥10 cases)
deepMerge remote/local 各种组合 / 同 id endpoints 不同 baseUrl 冲突 + 告警 / 字段合并各保留 / mergeWithDefaults 类型严格

### T4 — e2e `settings-schema-canonicalization.e2e.ts` (1 spec)
addInitScript 注入历史 snake_case localStorage → 启动 Settings → 验证 GET 返回 camelCase + Conflict Toast

### T5 — 回归覆盖
- `backend/tests/integration/test_preferences_endpoint.py` 修订：测试 key 命名按 camelCase
- 既有 `storage.test.ts` 增 5 个 deepMerge 边界 case（不删老的）

### T6 — 质量门禁
- Backend: `ruff check backend/` + `pytest backend/tests/unit/test_settings_canonicalizer.py backend/tests/integration/test_settings_route_legacy.py -q`
- Frontend: `npm run type-check && npm run lint && npx vitest run src/entities/setting/__tests__/`
- E2E: `npm run test:e2e -- tests/e2e/settings-schema-canonicalization.spec.ts`
- CI: 4 jobs 全绿

### T7 — 不写测试的清单
- Vite dev 重启后状态（手工冒烟）
- 实时多 Electron 窗口同步（无需求）
- settings JSON > 1MB（协议上不会出现）

## 7. Cross-branch Execution

**模式**：项目惯例的 main 提 PR + win7 单 squash cherry-pick（参考 memory 中 PR #93 / #99 / #117 / #191-#198）

### Phase 0 (本地 main feature 分支)
1. `git switch main && git pull --rebase origin main && git switch -c fix/settings-schema-canonicalization`
2. 落实 §3.1-§3.5 全部文件 + 测试 T1-T5
3. 本地 4 道关卡全绿
4. `git commit -m "fix(settings): snake↔camel translation + GET/PUT whitelist + deep-merge ..."`

### Phase 1 (main PR)
5. `git push -u origin fix/settings-schema-canonicalization`
6. `gh pr create --base main --title ... --body ...`
7. CI 等绿（Frontend TS / Electron build x2 / Electron smoke 4 jobs）
8. `code-reviewer` agent review → 修 critical/high
9. 用户 merge squash

### Phase 2 (win7 squash cherry-pick)
10. `git switch release/win7 && git pull --rebase origin release/win7`
11. `git switch -c fix/win7-settings-schema-canonicalization && git cherry-pick <main-merge-sha>`
12. 处理冲突: `legacy_routes.py` pydantic v1 vs v2 语法（`Config` vs `model_config`，`req.dict()` vs `req.model_dump()`），其它文件通常 0 冲突
13. `conda activate sage-backend-py38 && /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_settings_canonicalizer.py backend/tests/integration/test_settings_route_legacy.py -q`
14. `git commit -m "fix(win7): cherry-pick #XXX (settings schema canonicalization)"`
15. `LEFTHOOK=0 git push -u origin fix/win7-settings-schema-canonicalization`（如遇钩子挂起 — per memory）
16. `gh pr create --base release/win7 --title ... --body ...` ⚠️ 显式 `--base` 不容错
17. 等 win7 CI 绿（4 jobs）
18. `code-reviewer` agent review

### Phase 3 (收尾)
19. 更新 `MEMORY.md`: `Sage: settings schema canonicalization merged (YYYY-MM-DD)` 条目，含双 PR # 编号 + 6 节设计要点
20. win7 打 patch tag: `v0.4.5-alpha.30-win7`（per release-tier phase 3）；main tag 由用户定
21. 真机冒烟（Windows VM 跑 Vite dev 验证 sidebar 圆点）

### 风险表（per memory 教训）

| 风险 | 缓解 |
|---|---|
| `Config.extra="allow"` 是 bug 温床 | 收紧白名单 + 单测覆盖 |
| `LEFTHOOK=0 push` workaround | win7 push 时如挂起即用 |
| solo-owner PR merge 死锁 | `gh pr merge --admin` 兜底 |
| pydantic v1 兼容 | cherry-pick 后立即跑 py38 全套测试 |

## 8. 估计工作量

- Phase 0: 4 小时（6 文件 + 30 测试用例）
- Phase 1: 1-2 小时
- Phase 2: 1 小时（含冲突解决）
- Phase 3: 30 分钟
- **合计：** 一个工作日内可完成
