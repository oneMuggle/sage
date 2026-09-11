# 可插拔更新源系统（Pluggable Update Providers）

> **创建日期**: 2026-09-11
> **状态**: ✅ 已交付（Phase 1 #588 + Phase 2 #613 + Phase 3 #616/#617/#618/#619 + Phase 4 #620 完整闭环）
> **关联分支**: `feat/pluggable-update-providers` → 5 个独立 PR

---

## 1. 总览

把"硬编码 `https://updates.sage.app`"的更新源解耦成 4 平台 pluggable provider 系统：

- **generic-http**：内置官方源（RSA-SHA256 签名 manifest）
- **github**：GitHub Releases API（公开仓库无需 token，私有用 Bearer）
- **gitee**：码云 Releases API v5（`?access_token=` query string）
- **gitlab**：GitLab Releases API v4（`PRIVATE-TOKEN` header，支持自建 baseUrl）

用户可在 Settings → 更新源 tab 添加、设为默认、测试连接、删除自定义源；官方源作为不可删除的兜底（`isDefault=true`）。

### 阶段交付

| Phase | 内容 | PR |
|---|---|---|
| Phase 1 | 抽象层骨架（`UpdateProvider` interface + `ProviderRegistry` + `ProviderStore` + `providerIpc` + 4 平台骨架） | #588 |
| Phase 2 | UI（Settings ProvidersManager）+ preload API + token 加密安全审计 + feature flag 入口 | #613 |
| Phase 3.1 | GitHub provider 完整实现 | #616 |
| Phase 3.2 | Gitee provider 完整实现 | #617 |
| Phase 3.3 | GitLab provider 完整实现（自建 baseUrl 支持） | #618 |
| Phase 3.4 | feature flag 全开（dev/prod 默认 ON） | #619 |
| Phase 4.1 | E2E 旅程（hermetic Playwright） | #620 |
| Phase 4.4 | CHANGELOG + alpha tag | 待发 |

---

## 2. 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                       Renderer (React)                           │
│  Settings → Providers tab → ProvidersManager.tsx                 │
│  - 列表 / 设为默认 / 测试连接 / 删除 / 添加                        │
│  - 调用 window.electronAPI.providers.{list,get,add,setDefault,…}  │
└─────────────────────────┬───────────────────────────────────────┘
                          │  preload bridge (contextBridge)
┌─────────────────────────▼───────────────────────────────────────┐
│                    Main (Electron)                                │
│  providerIpc (ipcMain.handle)                                    │
│   ├─ providers.list/get   → ProviderStore                       │
│   ├─ providers.add        → ProviderStore + ProviderRegistry    │
│   ├─ providers.setDefault → ProviderStore                       │
│   ├─ providers.remove     → ProviderStore                       │
│   └─ providers.test       → provider.checkForUpdates() / ping() │
└─────────────────────────┬───────────────────────────────────────┘
                          │
       ┌──────────────────┼──────────────────────┐
       ▼                  ▼                      ▼
┌─────────────┐   ┌────────────────┐    ┌──────────────────┐
│ ProviderStore│   │ ProviderRegistry│    │  UpdateManager    │
│ (electron-   │   │ - generic-http │    │  (status state    │
│  store +     │   │ - github       │    │   machine)        │
│ safeStorage) │   │ - gitee        │    └─────────┬──────────┘
└─────────────┘   │ - gitlab       │              │
                  └────────┬───────┘              │
                           │                       │
                           ▼                       │
                  ┌────────────────────┐            │
                  │ UpdateProvider     │            │
                  │  (platform impl)   │            │
                  │  - checkForUpdates │◄───────────┘
                  │  - downloadAsset   │
                  │  - ping            │
                  └─────────┬──────────┘
                            │ HTTPS
       ┌────────────────────┼──────────────────────┐
       ▼                    ▼                      ▼
  updates.sage.app    github.com/api/v3       gitee.com/api/v5   gitlab.com/api/v4
  (generic-http,      releases                releases           releases
   RSA-SHA256)         (Bearer opt)            (?access_token)    (PRIVATE-TOKEN)
```

---

## 3. 模块清单

### 3.1 类型层（`electron/update/`）

| 文件 | 职责 |
|---|---|
| `providerConfig.ts` | `GithubConfig` / `GiteeConfig` / `GitlabConfig` / `GenericHttpConfig` 4 个 discriminated union；`isXxxConfig` 类型守卫 |
| `providers/base.ts` | `UpdateProvider` interface（`checkForUpdates` / `downloadAsset` / `ping`），`NormalisedRelease` / `ProviderChannel` / `ProviderError` |
| `providers/registry.ts` | `ProviderRegistry` — 工厂注册表 (`register(type, factoryFn)`) |
| `providers/genericHttp.ts` | generic-http 实现（RSA-SHA256 签名校验 + 进度回调 + 错误映射） |
| `providers/github.ts` | GitHub Releases API（stable=`/releases/latest`, prerelease=`/releases?per_page=10` + `pickNewestPrerelease`） |
| `providers/gitee.ts` | Gitee Releases API v5（access_token query string） |
| `providers/gitlab.ts` | GitLab Releases API v4（PRIVATE-TOKEN header + URL-encoded projectId + upcoming_release 字段） |
| `providerStore.ts` | electron-store + safeStorage 加密存储（token 等敏感字段） |
| `providerIpc.ts` | IPC handlers + `maskToken()` 阻止 raw token 泄露到 renderer |
| `featureFlag.ts` | `ENABLE_UPDATE_PROVIDERS_UI()` — 默认 ON，env `SAGE_EXPERIMENTAL_PROVIDERS=0` 强制关闭 |

### 3.2 主进程挂载（`electron/main.ts`）

```ts
// Phase 3 完整版（provider 注册块）
providerRegistry.register('generic-http', (cfg) => createGenericHttpProvider({...}));
providerRegistry.register('github',       (cfg) => createGithubReleasesProvider({...}));
providerRegistry.register('gitee',        (cfg) => createGiteeReleasesProvider({...}));
providerRegistry.register('gitlab',       (cfg) => createGitlabReleasesProvider({...}));
updateManager = new UpdateManager({ providerStore, providerRegistry });
if (ENABLE_UPDATE_PROVIDERS_UI()) {
  cleanupProviderIpc = registerProviderIpc(ipcMain, { providerStore, updateManager });
}
```

### 3.3 渲染层（`src/`）

| 文件 | 职责 |
|---|---|
| `src/shared/types/electron-api.ts` | `ProviderConfigSummary` 类型 + `window.electronAPI.providers` shape |
| `src/shared/updateFeatureFlag.ts` | renderer 端 flag（默认 ON，`window.__DISABLE_PROVIDERS__=true` 强制关闭） |
| `src/pages/settings/ProvidersManager.tsx` | UI（表格 + 添加按钮 + 操作列），所有 testid 暴露给 E2E |
| `src/pages/settings/Settings.tsx` | tab 容器 — `ENABLE_UPDATE_PROVIDERS_UI() && activeTab === 'providers'` 时挂载 |

### 3.4 测试覆盖

| 类型 | 文件 | 数量 |
|---|---|---|
| Unit (main) | `electron/update/__tests__/*.test.ts` | 12 文件, 40 测试 |
| Unit (provider) | `electron/update/__tests__/providers/{genericHttp,github,gitee,gitlab}.test.ts` | 4 文件, 19 测试 |
| Unit (renderer) | `src/pages/settings/__tests__/ProvidersManager.test.tsx` | 1 文件 |
| E2E (hermetic) | `e2e/hermetic/providers-manager.e2e.ts` | 1 文件, 2 journey（tab 可见 + 完整闭环） |

---

## 4. 接口契约

### 4.1 `UpdateProvider` 接口

```ts
interface UpdateProvider {
  readonly type: 'generic-http' | 'github' | 'gitee' | 'gitlab';
  readonly id: string;
  readonly displayName: string;
  readonly channels: ProviderChannel[];

  checkForUpdates(channel: string, opts?: { signal?: AbortSignal }): Promise<NormalisedRelease | null>;
  downloadAsset(release: NormalisedRelease, assetId: string, opts?: { signal?: AbortSignal; onProgress?: (received: number, total: number) => void }): Promise<string>;
  ping(opts?: { signal?: AbortSignal }): Promise<{ ok: boolean; latencyMs: number; error?: string }>;
}
```

### 4.2 `NormalisedRelease`

```ts
interface NormalisedRelease {
  version: string;             // 去掉前缀 'v'
  channel: string;             // 'stable' | 'beta' | 'alpha'
  publishedAt: string;         // ISO8601
  releaseNotes?: string;
  assets: Array<{
    id: string;
    name: string;              // 平台过滤: .exe/.dmg/.AppImage 或 'Setup'
    size: number;
    downloadUrl: string;
  }>;
  raw: unknown;                // 原始响应（调试用）
}
```

### 4.3 `channelMap` 语义（统一所有平台）

`channelMap` 的值表示 **该 channel 是否允许 prerelease**：

| channel | channelMap 值 | 平台行为 |
|---|---|---|
| `stable` | `false`（默认） | `/releases/latest` 或 `/releases`（list）+ 过滤 prerelease |
| `alpha`/`beta` | `true` | `/releases?per_page=10` + 选 prerelease |

GitHub / Gitee 用 `prerelease` 布尔字段区分；GitLab 用 `upcoming_release` 字段区分。

### 4.4 IPC 命令（`window.electronAPI.providers.*`）

| 命令 | 入参 | 返回 | 备注 |
|---|---|---|---|
| `list()` | — | `ProviderConfigSummary[]` | 全部源（内置 + 用户），token 已 mask |
| `get(id)` | `id: string` | `ProviderConfigSummary \| null` | |
| `add(payload)` | `Omit<ProviderConfigSummary, 'id' \| 'createdAt' \| 'updatedAt'>` | `ProviderConfigSummary` | id 后端生成 |
| `remove(id)` | `id: string` | `{ status: 'ok' }` | 内置源 (`__builtin__`) 拒绝删除 |
| `setDefault(id)` | `id: string` | `{ status: 'ok' }` | 唯一默认 |
| `test(id)` | `id: string` | `{ ok: boolean; latencyMs: number; error?: string }` | 走 provider 的 `checkForUpdates()` + `ping()` |

### 4.5 错误信封（`ProviderError`）

```ts
class ProviderError extends Error {
  constructor(message: string, public readonly status?: number) { ... }
}
```

- HTTP 401/403 → `凭证无效（HTTP {status}）`
- HTTP 404 → `{仓库/项目}不存在`
- 其他 5xx → `平台返回 HTTP {status}`
- 网络错 → fetch reject 透传

---

## 5. 安全设计

### 5.1 token 加密

`ProviderStore` 用 Electron `safeStorage`（macOS Keychain / Windows DPAPI / Linux kwallet/gnome-libsecret）加密 token 字段，写入 electron-store 的 JSON 文件前先 encrypt。读取时 decrypt，且 IPC 返回前 `maskToken()` 把 `config.token` 字段替换成 `'***masked***'` —— renderer 永远不接触 raw token。

### 5.2 IPC contextBridge 隔离

`providers.*` 命令经 preload 的 `contextBridge.exposeInMainWorld('electronAPI', { providers: { … } })` 暴露，不绕过 sandbox。

### 5.3 输入校验

`providerConfig.ts` 的 4 个 `isXxxConfig` 类型守卫在 IPC handler 入口处校验 payload；任意 type-confusion 攻击都会被类型守卫拦截（type guard + 字段必填检查 + 类型断言）。

### 5.4 路径沙箱

`downloadAsset` 写入 `cache/sage-update-{version}.tmp`（相对路径），不走绝对路径构造；后续 UpdateManager 接 file path 后由 Electron `app.updateFromFile()` 处理（已存在流程，未在本系统重复）。

---

## 6. 与现有 UpdateManager 的集成

- `UpdateManager.checkForUpdate()` 调用 → `providerRegistry.create(config.type).checkForUpdates(channel)`
- `UpdateManager.applyUpdate(asset)` → `provider.downloadAsset(release, assetId, { onProgress })` → file path → 现有 electron-updater 链路
- `UpdateManager.currentProviderId` 决定下次走哪个 provider；切换 provider 不需重启
- `providerStore` 是 single source of truth，所有 provider 实例从它派生

### 6.1 channelMap 实际使用

```ts
// 用户添加 GitHub provider:
{
  channelMap: { stable: false, beta: true, alpha: true }
}
```

实现：

```ts
const wantPrerelease = cfg.channelMap[channel] ?? false;
```

- `wantPrerelease === false`：取 list endpoint，过滤 `prerelease !== true`
- `wantPrerelease === true`：取 list endpoint，`pickNewestPrerelease`（按 publishedAt 降序排，取第一个 prerelease）

---

## 7. 失败模式与降级

| 场景 | 行为 |
|---|---|
| `ENABLE_UPDATE_PROVIDERS_UI()` 关 | `providerIpc` 不挂载 → 调用 `window.electronAPI.providers.*` 直接 undefined → UI 静默（Settings tab 不显示） |
| Provider 注册失败（`create(cfg)` throw） | `UpdateManager.init()` catch 后 log error + 切到内置 generic-http 兜底 |
| provider checkForUpdates 返回 401/403/404 | `ProviderError` 抛出 → UI 显示 "凭证无效" 弹窗，**不**自动回退到内置源（让用户主动修） |
| provider checkForUpdates 返回 null | UI 显示 "已是最新" |
| 多个用户源 + 默认源被删 | `setDefault` 自动迁移到第一个 enabled user source；都没有 → 退回内置 |

---

## 8. Feature flag 与回滚

```bash
# 关闭 UI（紧急回滚）
SAGE_EXPERIMENTAL_PROVIDERS=0 ./node_modules/.bin/electron --no-sandbox .

# renderer 端也可单独关闭（preload 注入 --sage-disable-providers-ui=1）
```

回滚后用户看到的是 1.0 时代的更新流程（无 ProvidersManager tab，无 pluggable UI）。

---

## 9. E2E 覆盖范围

`e2e/hermetic/providers-manager.e2e.ts`（Playwright `e2e-root` project）：

1. **Tab 可见** — feature flag 全开后，`Settings → 更新源` 出现，内置 Official 行可见
2. **完整闭环** — Add GitHub（mock prompt 链）→ SetDefault（默认标记迁移）→ Test（ok alert）→ Remove（confirm dialog）→ 行消失

mock 通过 `page.addInitScript` 注入 `window.electronAPI.providers.{list,get,add,remove,setDefault,test}` 全部 6 个方法，模拟主进程行为；IPC 调用序列被记录到 `window.__providersCalls` 供断言。

---

## 10. 后续可扩展点

- **Wizard UX** — 当前 `ProvidersManager.onAdd()` 仍用 `window.prompt()` 串 6 步（type/displayName/owner/repo/token/...）。Phase 4 wizard 计划：用 `<input type="password">` + 4 步引导，token 不再 echo。
- **provider 健康度周期巡检** — 当前仅在用户点 "测试连接" 时触发；后续可加 7-day 自动 ping + 在 Settings 顶部 banner 提示失败。
- **离线 cache** — ProviderStore 可加 24h 缓存 manifest，避免每次启动都拉网络。
- **provider hot-swap** — UpdateManager 已支持，但 IPC 路径在 runtime 切换 provider 时需要 rebuild state machine；目前仅在 init 时建一次。

---

## 11. 文件索引

| 路径 | 行数（approximate） | 说明 |
|---|---|---|
| `electron/update/providerConfig.ts` | ~80 | 4 平台配置类型 + 类型守卫 |
| `electron/update/providers/base.ts` | ~50 | UpdateProvider interface |
| `electron/update/providers/registry.ts` | ~30 | 工厂注册表 |
| `electron/update/providers/genericHttp.ts` | ~250 | 内置官方源（RSA-SHA256） |
| `electron/update/providers/github.ts` | ~170 | GitHub API |
| `electron/update/providers/gitee.ts` | ~140 | Gitee API |
| `electron/update/providers/gitlab.ts` | ~140 | GitLab API |
| `electron/update/providerStore.ts` | ~150 | electron-store + safeStorage |
| `electron/update/providerIpc.ts` | ~120 | IPC + maskToken |
| `electron/update/featureFlag.ts` | ~40 | env-based flag |
| `src/shared/updateFeatureFlag.ts` | ~25 | renderer 端 flag |
| `src/pages/settings/ProvidersManager.tsx` | ~200 | UI |
| `src/pages/settings/__tests__/ProvidersManager.test.tsx` | ~80 | UI unit |
| `e2e/hermetic/providers-manager.e2e.ts` | ~237 | E2E journey |

---

## 12. 关联章节

- [`./20-electron.md`](./20-electron.md) — Electron 桌面壳（含 UpdateManager 启动流程）
- [`./30-release-tiers.md`](./30-release-tiers.md) — alpha/beta/stable 渠道定义（channelMap 直接对应 stable/alpha/beta 三个 channel）
- [`./44-bash-tool.md`](./44-bash-tool.md) — 类似的 plugin/registry 架构参考
- [`./47-git-worktree-workflow.md`](./47-git-worktree-workflow.md) — 本系统的 5 个 PR 都在 worktree 下完成