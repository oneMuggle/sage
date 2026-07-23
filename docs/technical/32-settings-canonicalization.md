# 32. Settings Schema 规范化（snake↔camel 翻译 + 白名单）

> Settings 持久化的"单一事实源"是前端 `AppSettings` (camelCase)。后端 PUT/GET 必须与其 1:1 对齐。本模块在读写两侧做 snake↔camel 翻译 + 白名单校验, 兼容历史 snake_case 数据, 阻止新污染。

---

## 背景

Sage 在 2026-06-23 PR 引入 v3 架构 (AppSettings → 后端 PUT/GET), 但后端 schema 用 `extra="allow"` 接受一切字段, 前端浅 merge `{...local, ...remote}`, 导致:

1. **历史 snake_case 污染** — `data/sage.db/preferences.app_settings` 行残留 `base_url`/`api_key`/`endpoint_id`/`model_selections`/`chat_model` 等老客户端写入的 snake 字段, 与 AppSettings camelCase 类型不匹配.
2. **后端 schema 接受一切** — legacy `LegacySettingsRequest` 与 hex `SettingsRequest` 都是 `extra="allow"`, 没做 snake↔camel 翻译.
3. **前端浅 merge** — `loadSettings` 用 `{...local, ...remote}` 让陈旧 remote 永远覆盖 local.

效应: sidebar 左下角圆点永久显示"未配置", Chat 顶部黄色告警条永远显示.

## 解决方案

三层叠加修复 (main + win7 双分支):

### 后端

**新增 `backend/data/settings_canonicalizer.py`** — 纯函数模块:

| 函数 | 职责 |
|---|---|
| `to_camel(value) -> Any` | 递归 snake→camel (dict 翻译 key, list 元素递归, 其他原样) |
| `from_camel(value) -> Any` | 反向翻译 (ALIASES 双向) |
| `validate_settings_shape(settings) -> None` | AppSettings 白名单校验; 不在白名单 → raise `ValueError` |
| `detect_legacy_snake_pollution(settings, path="") -> List[str]` | 递归检测 snake_case 字段路径 (调试用, 默认不 log) |

**`ALIASES` 字段映射表** (16 条 snake↔camel):
- 顶层 8 个: `model_selections`, `max_context`, `proxy_mode`, `proxy_url`, `tls_version`, `auto_memory`, `confirm_delete`, `compact_mode`
- modelSelections 子层 3 个: `chat_model`, `vision_model`, `embedding_model`
- EndpointConfig 子层 4 个: `base_url`, `api_key`, `discovered_models`, `last_discovered_at`
- ModelSelection 子层 2 个: `endpoint_id`, `model_id`

**白名单** (5 个 `FrozenSet[str]`):
- `LEGAL_TOP_KEYS` — 13 个 AppSettings 顶层字段 (含 streaming, endpoints, modelSelections, wiki 等)
- `LEGAL_ENDPOINT_KEYS` — 6 个 (id, name, baseUrl, apiKey, discoveredModels, lastDiscoveredAt)
- `LEGAL_MODEL_SELECTION_KEYS` — 2 个 (endpointId, modelId)
- `LEGAL_DISCOVERED_MODEL_KEYS` — 3 个 (id, capabilities, endpointId)
- `LEGAL_WIKI_KEYS` — 1 个 (useFolderPicker)

**路由接入** (legacy + hex 对称):
- **GET**: `repo.get_json()` → `isinstance(dict)` guard → `detect_legacy_snake_pollution` (gate-controlled log) → `to_camel` → 返回
- **PUT**: `repo.get_json()` (existing) → `isinstance(dict)` guard (否则 empty dict) → `req.model_dump(exclude_none=True)` → 剥离 legacy 3 字段 (api_base_url/api_key/model 仅审计, 不进 DB) → `{**existing, **payload}` → `to_camel` → `validate_settings_shape` (400 on ValueError) → `repo.set_json`

### 前端

**新增 `src/entities/setting/deepMerge.ts`** — 字段级递归 + array id-dedup + remote-wins 冲突告警:
- 双方都是 plain object → 字段级递归
- 双方都是 array (例 `endpoints[]`) → 按 `id` 去重, 同 id 递归, base-only 保留, override-only 追加
- 标量 / array leaf → override 完全替换
- 冲突时 `console.warn` + `policy` 决策 (默认 remote-wins)

**改 `src/entities/setting/storage.ts:loadSettings`**:
- `deepMerge<Partial<AppSettings>>(local, remote, { policy: 'remote-wins' })`
- `mergeWithDefaults(merged)` → `writeLocalCacheSync(finalSettings)` (兜底持久化)
- `try/catch` around `settingsClient.getSettings()` (defense-in-depth, settingsClient 已内置 IPC 兜底)

### 数据流

```
前端 loadSettings() mount:
  remote = settingsClient.getSettings()
        ↓ IPC /api/v1/settings
  后端 legacy/hex GET → to_camel(DB row) → 返回 camelCase
        ↓ settingsClient ipcCall (5s timeout, 失败返 null)
  if remote:
    merged = deepMerge(local, remote, remote-wins)  // remote 赢
  else:
    merged = local (maybe auto-migrate 到 backend)
  writeLocalCacheSync(mergeWithDefaults(merged))
  return merged
```

## 已知约束 / 后续

- **DRY**: hex vs legacy handler 有重复 — 留给单独 refactor PR
- **3 legacy 字段无 EOL**: api_base_url/api_key/model 在 PUT 仍接受但仅审计, 不进 DB; EOL 时间跟前端 AppSettings 迁移一起定
- **安全 follow-up**:
  - `deepMerge` 冲突告警会 `JSON.stringify` base/override, 若路径是 `apiKey` 可能把凭据写进 console — 需路径级脱敏
  - `deepMerge` 没有显式跳过 `__proto__`/`prototype`/`constructor` 键 — 来自 untrusted source 时可能原型污染, 需 denylist
- **SQLite 明文 apiKey** — 既有设计, 不在本 PR 范围

## 参考

- Design spec: `docs/superpowers/specs/2026-07-22-settings-schema-canonicalization-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-22-settings-schema-canonicalization.md`
- PR #206 (main)
