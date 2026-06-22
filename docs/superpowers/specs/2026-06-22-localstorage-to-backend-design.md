# localStorage 配置存储迁移至后端 SQLite 设计

> 日期：2026-06-22
> 状态：待用户审阅
> 作者：Claude (brainstorming 流程产出)

## 1. 背景与目标

### 1.1 当前状态

Sage 前端使用 `localStorage` 持久化三类配置：

| 文件 | Key | 内容 |
|---|---|---|
| `src/entities/setting/storage.ts` | `sage-settings` | `AppSettings`（含 `endpoints[].apiKey`、`proxyUrl`、`maxContext` 等 12 个字段，schema v3.0.0） |
| `src/shared/lib/store.ts` | `sage-current-session-id` | zustand store 初始化时的当前会话 ID |
| `src/app/providers/ThemeProvider.tsx` | `sage-theme` | 主题模式 `light`/`dark`/`system` |

`localStorage` 在浏览器/Chromium 中**按 origin 绑定**。Sage 的 origin 至少存在三套：

| 形态 | Origin | 触发条件 |
|---|---|---|
| 开发模式 | `http://localhost:1420` | `npm run dev` |
| 打包 Electron | `file://.../dist/index.html` | `npm run tauri build` 后的安装包 |
| 自定义端口 | `http://localhost:<用户改的端口>` | 用户改 `VITE_DEV_SERVER_URL` |

**核心问题**：任何 origin 变化都会让 `localStorage` 不可见，用户的 `apiKey`、端点配置、主题偏好都会"消失"。

### 1.2 目标

1. **跨形态一致性**：dev / 打包 / 换端口三种形态共享同一份配置
2. **真值源统一**：后端 SQLite 是 source of truth，前端 `localStorage` 降级为离线缓存
3. **零回归**：UI 行为、配置 schema、性能不降低
4. **架构对齐**：与项目"前端薄、后端厚"的分层一致（chat / sessions / memory 全部在后端）

### 1.3 非目标

- apiKey 加密（用户决策：暂不加密，留作后续 P2）
- 多窗口 OT 同步（YAGNI：最后写胜出）
- 配置文件跨机器同步（云同步不在本 spec 范围）

### 1.4 约束

- Electron 21.4.4 + Win7 兼容矩阵不能破坏
- 后端 FastAPI 已在 `127.0.0.1:8765` 跑（subprocess 形态）
- IPC 桥（`electron/commands.ts` + `sage:invoke`）已稳定，新增 cmd 是低成本操作
- 不能引入新的前端重型依赖（不引 `electron-store`、不引 `IndexedDB` polyfill）

## 2. 决策摘要

| 决策点 | 选择 | 理由 |
|---|---|---|
| 持久化层 | 后端 SQLite `preferences` 表（已存在） | 复用现成表 + 仓储模式 |
| apiKey 加密 | 暂不加密 | 用户决策；记录为 P2 follow-up |
| 旧数据迁移 | 静默自动迁移 | 用户决策；首次启动检测到 localStorage 有数据自动上传 |
| 迁移范围 | 三处一起迁移（settings + theme + sessionId） | 用户决策；统一 IPC + 一致的 offline 兜底 |
| 多窗口同步 | 最后写胜出 | YAGNI，避免 OT 复杂度 |
| 离线缓存 | localStorage 保留作降级 + 迁移冗余 7 天 | 7 天后清理（可选 P5 任务） |
| Schema 版本 | 保留前端 `SETTINGS_VERSION = '3.0.0'` + 迁移函数 | 迁移发生在加载时（前端），后端只存最新格式 |

## 3. 架构设计

### 3.1 数据流总览

```
┌────────────────┐                    ┌─────────────────────────┐
│  React Frontend│                    │  FastAPI Backend        │
│                │   IPC (sage:invoke)│                         │
│  settingsClient├──cmd:get_settings──▶│  /api/v1/settings       │
│  (async)       │   cmd:set_settings │                         │
│                │                    │  hex_routes.py          │
│  localStorage  │  ◀─ 失败时降级 ────│      ↓                  │
│  (offline cache)│                   │  settings_repo.py       │
└────────────────┘                    │      ↓                  │
                                      │  preferences (SQLite)   │
                                      └─────────────────────────┘
```

**关键原则**：
- 后端 SQLite 是**真值源**
- 前端 `localStorage` 是**离线缓存**，不再是真值
- IPC 失败 → 自动降级到 `localStorage`，UI 永不卡死
- 写入是"同步写 cache + 异步写 backend"双写

### 3.2 后端架构

#### 3.2.1 新增 `backend/data/settings_repo.py`

参考 `session_repo.py` 模式（`backend/data/session_repo.py:1-15`），实现以下接口：

```python
class SettingsRepository:
    """基于 preferences 表的 KV 仓储。"""

    def get(self, key: str) -> Optional[str]:
        """读取 value (TEXT)；不存在返回 None。"""

    def get_json(self, key: str) -> Optional[Any]:
        """读取并 JSON.parse；解析失败返回 None。"""

    def set(self, key: str, value: str, value_type: str = "string",
            category: str = "general") -> None:
        """upsert (key, value, value_type, category, updated_at=now)。"""

    def set_json(self, key: str, value: Any,
                 category: str = "general") -> None:
        """set 的 JSON 便捷包装。"""

    def delete(self, key: str) -> None:
        """删除单条；不存在不报错。"""

    def list_by_category(self, category: str) -> dict[str, str]:
        """批量读取（用于调试/管理 UI）。"""
```

**内部约定**：
- `app_settings` 用 `value_type='json'`，`category='general'`
- `theme_mode` 用 `value_type='string'`，`category='ui'`
- `current_session_id` 用 `value_type='string'`，`category='session'`
- 模块级 `KEYS = { 'app_settings', 'theme_mode', 'current_session_id' }` 白名单，防止任意 key 写入

#### 3.2.2 修改 `backend/api/hex_routes.py`

| 端点 | 改动 |
|---|---|
| `PUT /settings` | **从"只发审计"升级为"真持久化"**（hex_routes.py:174）：先调 `settings_repo.set_json('app_settings', payload)`，再 emit `settings_changed` 事件。`api_key` 字段不进审计 payload（沿用 hex_routes.py:192 的逻辑） |
| `GET /settings` | **新增**：`settings_repo.get_json('app_settings')` → 命中返回 `AppSettings`，未命中返回 `null`（前端走 DEFAULT_SETTINGS） |
| `GET /preferences/{key}` | **新增**：通用 KV 读取，限定白名单 keys |
| `PUT /preferences/{key}` | **新增**：通用 KV 写入，限定白名单 keys；value 走 `value` 字段（string） |

**白名单保护**：端点层校验 `key in settings_repo.KEYS`，不合法返回 400。这避免前端任意写入污染 `preferences` 表。

#### 3.2.3 修改 `backend/data/database.py`

当前 `Database.__init__`（database.py:13-21）硬编码 `data/sage.db`。**修改**：

```python
def __init__(self, db_path: str | None = None):
    if db_path is None:
        env_path = os.environ.get("SAGE_DB_PATH")
        if env_path:
            db_path = env_path
        else:
            # dev 默认路径：项目根目录下的 data/sage.db（保持现状）
            base_dir = Path(__file__).parent.parent.parent
            data_dir = base_dir / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "sage.db")
    self.db_path = db_path
```

并在文件顶部加 `import os`。**不破坏**现有调用方（`get_database()` factory 不变）。

### 3.3 Electron 集成

#### 3.3.1 `electron/commands.ts` 新增 4 条 IPC 路由

```ts
// chat/settings/preferences 三个 cmd
get_settings: { method: 'GET',  path: () => '/api/v1/settings' },
set_settings: { method: 'PUT',  path: () => '/api/v1/settings' },
get_preference: {
  method: 'GET',
  path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
},
set_preference: {
  method: 'PUT',
  path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
},
```

**安全性**：路由层**不**额外校验 key 范围；白名单校验在后端 hex_routes 完成。

#### 3.3.2 `electron/main.ts` 启动后端时传 `SAGE_DB_PATH`

修改 `spawnBackend()`（main.ts:95-136）：

```ts
const env = {
  ...process.env,
  SAGE_DB_PATH: process.env.SAGE_DB_PATH
    ?? path.join(app.getPath('userData'), 'sage.db'),
};
proc = spawn(pyLauncher ?? condaCmd, args, { env, ... });
```

`app.getPath('userData')` 在 dev / 打包下分别落到：
- dev: `~/.config/sage/sage.db`（Linux）/ `~/Library/Application Support/sage/sage.db`（macOS）/ `%APPDATA%\sage\sage.db`（Windows）
- 打包: 同上路径的 sage 目录

**这样** dev 与打包形态的 backend 都看到同一个 `app.getPath('userData')`，配置自然一致。

### 3.4 前端架构

#### 3.4.1 新增 `src/shared/api/settingsClient.ts`

```ts
// 公开接口
export interface SettingsClient {
  getSettings(): Promise<AppSettings | null>;
  setSettings(partial: Partial<AppSettings>): Promise<void>;
  getPreference<T extends string>(key: PreferenceKey): Promise<T | null>;
  setPreference(key: PreferenceKey, value: string): Promise<void>;
}

// 内部：探测后端是否可达（5s 超时），用于首次自动迁移判定；不导出
async function probeBackend(): Promise<boolean> { ... }

export const LOAD_TIMEOUT_MS = 5000;

// 内部实现
async function ipcCall<T>(cmd: string, args?: object): Promise<T> {
  return Promise.race([
    invoke<T>(cmd, args ?? {}),
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('IPC timeout')), LOAD_TIMEOUT_MS),
    ),
  ]);
}
```

**关键设计**：
- 5s 超时防止 UI 永远等待
- 错误不抛给上层，转换为 `null`（读取）或 `console.warn`（写入）
- `probeBackend` 用 `GET /preferences/app_settings`（任意一个白名单 key 都行）做健康检查

#### 3.4.2 重写 `src/entities/setting/storage.ts`

```ts
const CACHE_KEY = SETTINGS_STORAGE_KEY;     // 'sage-settings'
const MIGRATION_MARKER = 'sage-settings.migrated';
const CACHE_RETENTION_DAYS = 7;

// loadSettings 改 async；旧签名加 deprecated 注释
export async function loadSettings(): Promise<AppSettings> {
  const remote = await settingsClient.getSettings();
  if (remote) {
    // 写本地 cache + 触发自动迁移（如果需要）
    await syncLocalCache(remote);
    return remote;
  }
  // 降级到 localStorage
  return readLocalCache() ?? { ...DEFAULT_SETTINGS };
}

export async function saveSettings(partial: Partial<AppSettings>): Promise<void> {
  // 1. 立即同步写 local cache（永不阻塞 UI）
  const merged = { ...loadLocalCacheSync(), ...partial };
  writeLocalCacheSync(merged);
  // 2. 异步推后端
  try {
    await settingsClient.setSettings(partial);
  } catch (e) {
    console.warn('[settings] setSettings failed, local cache only:', e);
  }
}
```

**API 兼容性**：保留 `loadSettings` 旧同步签名（返回默认值）作为 fallback，标记 `@deprecated`；`useSettings` 必须用新 async 接口。

#### 3.4.3 新增 `src/entities/theme/storage.ts`

从 `ThemeProvider.tsx` 抽出：

```ts
const CACHE_KEY = 'sage-theme';

export async function loadTheme(): Promise<ThemeMode | null> { ... }
export async function saveTheme(mode: ThemeMode): Promise<void> { ... }
```

#### 3.4.4 新增 `src/entities/session/storage.ts`

从 `store.ts` 抽出：

```ts
const CACHE_KEY = 'sage-current-session-id';

export async function loadCurrentSessionId(): Promise<string | null> { ... }
export async function saveCurrentSessionId(id: string | null): Promise<void> { ... }
```

#### 3.4.5 修改 `src/features/manage-settings/useSettings.ts`

```ts
export interface UseSettingsReturn {
  settings: AppSettings;
  isLoading: boolean;
  updateSettings: (partial: Partial<AppSettings>) => Promise<void>;
  resetSettings: () => Promise<void>;
}

export function useSettings(): UseSettingsReturn {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    loadSettings().then((s) => {
      if (!cancelled) {
        setSettings(s);
        setIsLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, []);

  const updateSettings = useCallback(async (partial) => {
    const next = { ...settings, ...partial };
    setSettings(next);
    await saveSettings(partial);
  }, [settings]);

  // resetSettings 同样改 async
  // ...
}
```

#### 3.4.6 修改 `src/app/providers/ThemeProvider.tsx`

```tsx
export function ThemeProvider({ children, defaultMode = 'system' }: Props) {
  const [mode, setModeState] = useState<ThemeMode>(defaultMode);  // 占位
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(...);

  useEffect(() => {
    loadTheme().then((m) => { if (m) setModeState(m); });
  }, []);

  const setMode = (next: ThemeMode) => {
    setModeState(next);
    void saveTheme(next);  // 异步触发，不阻塞
  };
  // ...
}
```

#### 3.4.7 修改 `src/shared/lib/store.ts`

`currentSessionId` 初始值改为 `null`（不再从 localStorage 同步读），用 `useEffect` 异步加载：

```ts
export const useStore = create<StoreState>((set) => ({
  currentSessionId: null,  // 不再用同步 IIFE 读 localStorage
  // ...
  setCurrentSessionId: (id) => {
    set({ currentSessionId: id });
    void saveCurrentSessionId(id);  // 异步持久化
  },
}));

// 在 Chat 页或 useStore 初始化处触发
useEffect(() => {
  loadCurrentSessionId().then((id) => {
    if (id) useStore.getState().setCurrentSessionId(id);
  });
}, []);
```

**注**：在 `src/App.tsx` 顶层 `useEffect` 触发 `loadCurrentSessionId()` 初始化（App 是所有页面的根，确保 store 准备好）。

### 3.5 数据 Schema

复用现有 `preferences` 表（`backend/data/database.py:138-148`）：

```sql
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'string',
    description TEXT,
    category TEXT DEFAULT 'general',
    created_at INTEGER NOT NULL,
    updated_at INTEGER
)
```

新增 3 行 key：

| key | value 形态 | value_type | category | 备注 |
|---|---|---|---|---|
| `app_settings` | `AppSettings` JSON 字符串 | `json` | `general` | 包含 `version` 字段做 schema 升级 |
| `theme_mode` | `light`/`dark`/`system` | `string` | `ui` | |
| `current_session_id` | session id（UUID） | `string` | `session` | |

**Schema 版本管理**：`SETTINGS_VERSION = '3.0.0'` 仍由前端管理；`migrateFromV1/V2` 仍在 `src/entities/setting/storage.ts`，迁移发生在加载时。后端只存 v3 格式。

## 4. 数据流详解

### 4.1 读取路径（应用启动）

```
mount
  └─ settingsClient.get(key)
       ├─ try: ipc invoke → backend GET /preferences/{key} → 5s 超时
       │     ├─ 成功: 返回 value, 同步把 value 写 localStorage (cache)
       │     └─ 失败/超时: 读 localStorage → 命中返回, 未命中返回 null
       └─ 兜底: 返回 DEFAULT_SETTINGS / 'system' / null
```

**首次启动的特殊路径**（自动迁移）：

```
1. App 启动 → 三处 storage 各自 loadSettings/loadTheme/loadCurrentSessionId
2. settingsClient.get('app_settings') 第一次成功拿到后端响应
3. 检查 localStorage.sage-settings.migrated_to_backend 标志
4. 若未设 且 localStorage.sage-settings 有值:
     a. settingsClient.setSettings(localData)  // 一次性上传
     b. 写 localStorage.sage-settings.migrated_to_backend = ISO_TIMESTAMP
     c. 保留原 localStorage.sage-settings 数据 7 天
5. theme / current_session_id 同样按需迁移
```

### 4.2 写入路径（用户改配置）

```
user updates settings
  ├─ 同步 (UI immediate):
  │     1. setState (React 重新渲染)
  │     2. localStorage.setItem(key, value)  // 同步写，永不阻塞
  └─ 异步 (backend eventual consistency):
        3. settingsClient.setSettings/setPreference
              ├─ 成功: 静默
              └─ 失败: console.warn，下一次启动时重试（读路径会带过去）
```

**为什么双写**：UI 必须立即响应（用户看到变化），后端是异步同步真值。即使后端写入失败，UI 已经更新且 local cache 有最新值。

### 4.3 错误处理矩阵

| 场景 | 读取行为 | 写入行为 | UI 表现 |
|---|---|---|---|
| 后端未启动（`SAGE_SKIP_BACKEND=1`） | 100% localStorage | 写 localStorage，IPC 调用快速失败 | 正常（无感知） |
| 后端启动但健康超时 | 5s 后降级 localStorage | 写 localStorage + warn | 正常（无感知） |
| IPC 调用中后端崩 | 当前请求失败，state 维持 local 值 | 写 localStorage + warn | 正常（无感知） |
| localStorage 损坏（JSON parse fail） | 静默回退默认值 | 写 localStorage 时覆盖坏值 | 正常（无感知） |
| localStorage 不可用（隐私模式） | 完全走后端 | 写后端，无 offline cache | 正常（无感知） |
| 后端 schema 校验失败 | 返回 400，前端收到错误 | 不写 localStorage | toast 报错 |
| 多窗口并发写 | N/A | **最后写胜出**（接受） | 正常（无感知） |

## 5. 测试策略

### 5.1 Unit Tests

| 测试文件 | 覆盖点 |
|---|---|
| `backend/tests/unit/test_settings_repo.py`（新） | `get/set/delete/list` round-trip；JSON 解析失败；白名单 key |
| `src/shared/api/__tests__/settingsClient.test.ts`（新） | 5s 超时；IPC 错误降级；并发请求合并 |
| `src/entities/setting/__tests__/storage.test.ts`（重写） | async loadSettings 三路径（backend 命中 / localStorage 命中 / 默认值）；自动迁移；7 天保留 |
| `src/entities/theme/__tests__/storage.test.ts`（新） | async load/save；fallback |
| `src/entities/session/__tests__/storage.test.ts`（新） | async load/save；null 处理 |
| `src/features/manage-settings/__tests__/useSettings.test.ts`（改） | isLoading 状态；update 流；reset |
| `src/app/providers/__tests__/ThemeProvider.test.tsx`（新） | async 初始化；setMode 触发 saveTheme |
| `src/shared/lib/__tests__/store.test.ts`（改） | currentSessionId 异步初始化 |

### 5.2 Integration Tests

| 测试文件 | 覆盖点 |
|---|---|
| `backend/tests/integration/test_settings_endpoint.py`（新） | E2E: `GET/PUT /settings` round-trip 持久到 SQLite；`api_key` 不进审计；白名单 400 |
| `backend/tests/integration/test_preferences_endpoint.py`（新） | `GET/PUT /preferences/{key}` 通用 KV；白名单外返回 400 |
| `backend/tests/integration/test_db_path.py`（新） | `SAGE_DB_PATH` 环境变量生效；默认值保持 |
| `electron/__tests__/commands.test.ts`（补） | 4 个新 IPC cmd 路由存在；guard 测试防漏前缀 |

### 5.3 E2E 迁移测试（手动 / 手动脚本）

- 手动准备：v1 格式 `sage-settings` localStorage 数据
- 启动应用 → 验证：localStorage 数据被自动上传到后端；`migrated_to_backend` 标志被设置
- 卸载/重装应用 → 验证：后端数据仍可用（用 `SAGE_DB_PATH` 指向相同目录）

## 6. 迁移策略

### 6.1 静默自动迁移

**触发条件**：
- 应用启动 + 首次成功 IPC 到达后端
- `localStorage.sage-settings.migrated_to_backend` 标志**未**设置
- `localStorage.sage-settings` 有数据

**流程**：
1. `loadSettings()` 检测到后端无数据
2. 读 `localStorage.sage-settings`，过 `mergeWithDefaults` 做兼容
3. `settingsClient.setSettings(migrated)` 上传
4. 成功 → 写 `localStorage.sage-settings.migrated_to_backend = new Date().toISOString()`
5. 失败 → 留待下次启动重试

**保留期**：
- 迁移后保留 `localStorage.sage-settings` 原数据 **7 天**
- 7 天后由前端 hook 在下次启动时清理（写入空字符串后 delete）
- 7 天内若后端数据丢失，可手动从 localStorage 恢复（管理 UI 后续 P2）

### 6.2 回退方案

若新版本上线后发现严重问题：

| 步骤 | 操作 |
|---|---|
| 1 | 把 `storage.ts` 的 `loadSettings` 切回旧的 localStorage 同步读 |
| 2 | `useSettings` 改回同步；`isLoading` 暂时移除 |
| 3 | `ThemeProvider` / `store.ts` 同理 |
| 4 | 后端 `hex_routes` 的新端点保留（不破坏，不影响回退） |

回退可在 1 个 commit 内完成，**不**涉及数据库 schema 变更。

## 7. 阶段化落地

| 阶段 | 内容 | 风险 | 预计工作量 |
|---|---|---|---|
| **P1 后端骨架** | `settings_repo.py` + 4 个新端点 + `commands.ts` 4 条 IPC + `database.py` env var + unit/integration 测试 | 低（无前端变更） | 1-2 天 |
| **P2 前端切换** | `settingsClient.ts` + 3 个 storage 重写/新增 + 3 个 hook 改 async + 测试 | 中（UI loading 状态需小心） | 2-3 天 |
| **P3 迁移路径** | 首次启动自动迁移 + 7 天保留 | 低（有兜底） | 0.5 天 |
| **P4 打包路径** | `electron/main.ts` 传 `SAGE_DB_PATH` | 中（packaged 模式才验证） | 0.5 天 |
| **P5 清理**（1 个月后） | 移除 7 天保留 / 收紧白名单 / 加管理 UI | 低 | 后续 |

## 8. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| async 初始化导致首屏闪一下默认值 | 中 | 在 `useSettings`/`ThemeProvider` 暴露 `isLoading`，由消费页面选择 skeleton 或延迟渲染 |
| 后端 IPC 失败率提升（如 SAGE_SKIP_BACKEND 模式） | 低 | 双写 + 5s 超时，UI 永不阻塞 |
| 并发写冲突（多窗口） | 低 | 最后写胜出，记录在 spec 决策 |
| 后端 SQLite 文件权限 | 中 | 文档化：`app.getPath('userData')` 目录权限在 Windows 受用户账户保护，Linux/macOS 取决于 umask |
| 7 天保留过期清理逻辑 | 低 | 简单 try/catch，失败不阻塞主流程 |
| apiKey 明文存 SQLite | 中 | 按用户决策暂不加密；P2 补 `cryptography.fernet` 加密层 |

## 9. 后续 P2 任务（不在本 spec 范围）

- apiKey 加密（`cryptography.fernet`，密钥从 `SAGE_SETTINGS_KEY` env 读）
- 配置文件导入/导出（用户跨机器迁移）
- 多窗口实时同步（SSE / WebSocket）
- 管理 UI：显示当前 preferences、强制清理 localStorage
- CI 增加 `preferences` 表迁移回归测试

## 10. 验收标准

- [ ] 后端：`GET/PUT /settings` round-trip 持久化到 SQLite
- [ ] 后端：`GET/PUT /preferences/{key}` 白名单保护生效
- [ ] 后端：`api_key` 字段不进审计日志
- [ ] Electron：4 个新 IPC cmd 在 `COMMAND_ROUTES` 注册
- [ ] Electron：packaged 模式下后端写入 `app.getPath('userData')/sage.db`
- [ ] 前端：3 处 storage async 接口可用
- [ ] 前端：localStorage 降级路径在 SAGE_SKIP_BACKEND 模式验证通过
- [ ] 前端：自动迁移在带 v1/v2 localStorage 数据的浏览器跑通
- [ ] Electron：SAGE_SKIP_BACKEND 模式下前端不报错（完全降级到 localStorage）
- [ ] 测试：unit + integration 全绿；覆盖 ≥80%
- [ ] 文档：`docs/technical/09-frontend.md` 增加"配置存储"小节
- [ ] 文档：`docs/technical/10-api.md` 增加新端点
