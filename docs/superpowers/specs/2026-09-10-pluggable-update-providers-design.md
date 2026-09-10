# Sage 可配置更新源设计

> **状态**：待 review
> **日期**：2026-09-10
> **作者**：Claude Code + Sage Team
> **目标读者**：Sage 桌面端开发与维护者

## 1. 背景与目标

### 1.1 问题

Sage 当前升级系统（[2026-09-05-update-system-design.md](./2026-09-05-update-system-design.md)）的更新源**硬编码**在客户端：

- 元数据 API：`https://updates.sage.app/api/v1/updates/latest?channel=…`
- 安装包 CDN：`https://updates.sage.app/releases/…`
- URL 白名单仅接受 `updates.sage.app` 主机名（`electron/updateManager.ts:953-960`）

这把所有 Sage 用户绑定到 Sage 团队自托管的更新服务。需要支持：

- **企业内网自托管**（无外网、需审计、需国产化）
- **国内加速**（Gitee Releases）
- **自建团队**（GitLab 自部署）
- **开源仓库托管**（GitHub Releases）

### 1.2 目标

引入 **Provider 插件化** 架构，让用户能在 Settings 增删切换更新源，第一版支持：

1. GitHub Releases（含 GitHub.com 与 Enterprise）
2. Gitee Releases
3. GitLab Releases（含自建 GitLab 实例）
4. Generic HTTP（保留现有 `updates.sage.app` 协议，向后兼容在网客户端）

### 1.3 非目标

- OTA 增量更新 / delta patching
- 多 provider 并行检查取最高版本
- 静默迁移老配置
- 远程 provider marketplace
- Ed25519 / ECDSA 多签名算法（仅 Generic HTTP 走 RSA-SHA256）

### 1.4 设计原则

- **YAGNI**：只做四类 provider + 多实例 + 默认 active
- **可控性**：技术用户偏好透明，删除 default 必须先切换
- **安全性**：token 加密存储、URL 白名单、签名按 provider 区分
- **向后兼容**：现网 `updates.sage.app` 用户升级后行为不变
- **渐进发布**：feature flag 控制 UI 可见性，分阶段铺开

## 2. 关键决策摘要

| # | 维度 | 决策 |
|---|---|---|
| 1 | 架构 | Provider 插件化（UpdateProvider 接口） |
| 2 | 配置时机 | 完全运行时可改（Settings 增删切换） |
| 3 | 首批 provider | GitHub / Gitee / GitLab / Generic HTTP 全要 |
| 4 | 签名策略 | Generic 强签 RSA-SHA256；平台 provider 信任平台 CDN + UI 警示 + 用户显式勾选 |
| 5 | Channel 映射 | 每个 provider 自定义（GitHub prerelease→beta/alpha，latest→stable） |
| 6 | 多实例 | 多 provider 实例 + 默认 active（手动检查可临时指定） |

## 3. 整体架构

### 3.1 系统分层

```
┌────────────────────────────────────────────────────────────┐
│ Renderer (React)                                            │
│  Settings/UpdatesTab.tsx                                    │
│  Settings/ProvidersManager.tsx         ← 新增               │
│  UpdateDialog.tsx                                          │
└──────────────────────┬─────────────────────────────────────┘
                       │ preload window.electronAPI.providers.*
                       ▼
┌────────────────────────────────────────────────────────────┐
│ Main Process                                                │
│  updateIpc.ts            (现有，不变)                       │
│  providerIpc.ts          ← 新增（8 channel）                │
│       │                                                     │
│       ▼                                                     │
│  UpdateManager (改造：接受 activeProvider 注入)             │
│   ├─ ProviderStore       ← 新增（持久化 + 加解密）          │
│   ├─ ProviderRegistry    ← 新增（type → factory 映射）      │
│   └─ 4 个 UpdateProvider adapter：                          │
│       ├─ GitHubReleasesProvider     ← 新增                  │
│       ├─ GiteeReleasesProvider      ← 新增                  │
│       ├─ GitLabReleasesProvider     ← 新增                  │
│       └─ GenericHttpProvider        ← 现有逻辑迁移          │
│   installer / rollback / strategy (不变)                    │
└────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────┐
│ Network                                                     │
│  api.github.com / gitee.com/api / gitlab.com/api / 自托管   │
└────────────────────────────────────────────────────────────┘
```

### 3.2 数据流（正常升级）

1. 主进程启动 → `ProviderStore.list()` → 找 `isDefault` cfg → `ProviderRegistry.build()` → 注入 `UpdateManager`
2. 用户点"立即检查" → IPC `update:check` → `UpdateManager.checkForUpdates(channel)`
3. `activeProvider.checkForUpdates(channel)` → 平台 provider 调 GitHub/Gitee/GitLab API；Generic HTTP 调 `manifestUrl` → 返回 `NormalisedRelease`
4. 用户点"下载" → IPC `update:download` → `activeProvider.downloadAsset(asset)` → 写到本地缓存
5. **仅 Generic HTTP**：`verifyArtifact(localPath, signature, publicKey)` 走 RSA-SHA256
6. **平台 provider**（如勾选 `requireArtifactSignature`）：同样走签名校验
7. **所有 provider**：如有 `checksum` 字段做 SHA-256 比对
8. 通过 → 触发 electron-updater install path

### 3.3 元数据服务（保持不变）

`backend/services/update_metadata.py` 与 `backend/api/v1/updates.py` 继续作为 Generic HTTP provider 的服务端实现，**不重构**。后续可独立扩展。

## 4. 组件细节

### 4.1 `UpdateProvider` 接口

```typescript
// electron/update/providers/base.ts
export type ProviderType = 'github' | 'gitee' | 'gitlab' | 'generic-http';

export interface ProviderChannel {
  id: string;                 // 'stable' | 'beta' | 'alpha'
  label: string;
  description: string;
}

export interface NormalisedRelease {
  version: string;
  channel: string;
  publishedAt: string;        // ISO8601
  releaseNotes?: string;
  assets: Array<{
    id: string;
    name: string;             // 'Sage-Setup-0.4.9.exe'
    size: number;
    downloadUrl: string;
    checksum?: { algo: 'sha256' | 'sha512'; value: string };
    signature?: string;       // base64 detached
  }>;
  raw?: unknown;
}

export interface UpdateProvider {
  readonly type: ProviderType;
  readonly id: string;
  readonly displayName: string;
  readonly channels: ProviderChannel[];
  checkForUpdates(channel: string, opts?: { signal?: AbortSignal }): Promise<NormalisedRelease | null>;
  downloadAsset(release: NormalisedRelease, assetId: string, opts?: {
    onProgress?: (bytes: number, total: number) => void;
    signal?: AbortSignal;
  }): Promise<string>;
  verifyArtifact?(assetPath: string, signature: string, publicKey: string): Promise<boolean>;
  ping(opts?: { signal?: AbortSignal }): Promise<{ ok: boolean; latencyMs: number; error?: string }>;
}
```

### 4.2 Provider 配置数据结构

```typescript
// electron/update/providerConfig.ts
export interface ProviderInstanceConfig {
  id: string;                    // uuid v4
  type: ProviderType;
  displayName: string;
  enabled: boolean;
  isDefault: boolean;             // 全局唯一
  createdAt: string;
  updatedAt: string;
  config:
    | GithubConfig
    | GiteeConfig
    | GitlabConfig
    | GenericHttpConfig;
}

export interface GithubConfig {
  owner: string;
  repo: string;
  token?: string;                 // safeStorage 加密
  channelMap: Record<string, boolean>;
  requireArtifactSignature: boolean;
}

export interface GiteeConfig {
  owner: string;
  repo: string;
  token: string;                  // Gitee API 强制鉴权
  channelMap: Record<string, boolean>;
  requireArtifactSignature: boolean;
}

export interface GitlabConfig {
  baseUrl: string;                // 'https://gitlab.com' 或自建
  projectId: string | number;
  token: string;
  channelMap: Record<string, boolean>;
  requireArtifactSignature: boolean;
}

export interface GenericHttpConfig {
  manifestUrl: string;
  publicKey: string;              // PEM/SPKI，明文存
  channelMap: Record<string, boolean>;
  requireArtifactSignature: true; // 常量
}
```

### 4.3 IPC Channel

| Channel | 请求 | 响应 |
|---|---|---|
| `provider:list` | — | `ProviderInstanceConfig[]`（token masking `'***masked***'`） |
| `provider:get` | `{ id: string }` | `ProviderInstanceConfig \| null` |
| `provider:add` | `Omit<…,'id'\|'createdAt'\|'updatedAt'>` | `{ id: string }` |
| `provider:update` | `{ id; patch }` | `{ ok: true }` |
| `provider:remove` | `{ id }` | `{ ok: true }`（若 default 报错） |
| `provider:set-default` | `{ id }` | `{ ok: true }` |
| `provider:test` | `{ id }` | `{ ok; latencyMs; error? }` |
| `update:check-with` | `{ providerId; channel? }` | 复用 `UpdateCheckResult` |

### 4.4 ProviderStore / ProviderRegistry

```typescript
// electron/update/providerStore.ts
export class ProviderStore {
  async list(): Promise<ProviderInstanceConfig[]>;
  async get(id: string): Promise<ProviderInstanceConfig | null>;
  async add(cfg: ...): Promise<string>;
  async update(id: string, patch: ...): Promise<void>;
  async remove(id: string): Promise<void>;
  async setDefault(id: string): Promise<void>;
  private ensureUniqueDefault(...): void;
  private encryptSensitive(cfg): ProviderInstanceConfig;
  private decryptSensitive(cfg): ProviderInstanceConfig;
}

// electron/update/providers/registry.ts
export class ProviderRegistry {
  private factories: Map<ProviderType, (cfg) => UpdateProvider>;
  register(type: ProviderType, factory: ...): void;
  build(config: ProviderInstanceConfig): UpdateProvider;
}
```

### 4.5 持久化策略

- 存 `electron-store`，key `update.providers`
- `token` / `publicKey`（仅 Generic）走 `safeStorage.encryptString`
  - Linux 密钥环不可用时降级：明文写到 `app.getPath('userData')/update-providers.json`、文件权限 0600、首次启动 `logger.warn` 一次
- `isDefault` 写时校验唯一

## 5. 数据流（关键路径）

### 5.1 启动初始化

```
UpdateManager.init()
  ├─ ProviderStore.list() → decrypt
  ├─ 找 isDefault cfg
  │   ├─ 存在 → ProviderRegistry.build(cfg) → activeProvider
  │   └─ 不存在 → fallback 内置 Generic HTTP（updates.sage.app，内存对象，不持久化）
  ├─ 挂 IPC
  └─ 启动后台自动 check（若策略启用）
```

### 5.2 检查更新

```
update:check IPC → UpdateManager.checkForUpdates()
  ├─ activeProvider.checkForUpdates(channel='stable')
  │   ├─ GitHub: GET /repos/{owner}/{repo}/releases/latest
  │   ├─ Gitee:  GET /repos/{owner}/{repo}/releases/latest (token 必填)
  │   ├─ GitLab: GET {baseUrl}/api/v4/projects/{id}/releases (PRIVATE-TOKEN)
  │   └─ Generic: GET {manifestUrl}?channel=stable + RSA-SHA256 验证
  ├─ 平台 provider：parse tag → version, map prerelease → channel
  ├─ 错误处理：
  │   ├─ 401/403 → "凭证无效，请在更新源管理中更新 token"
  │   ├─ 404 → "仓库/项目不存在或路径错误"
  │   ├─ timeout → 30s 后重试 1 次
  │   └─ 5xx → "更新源暂时不可用"
  └─ updateState 推 renderer
```

### 5.3 下载

```
update:download IPC → UpdateManager.downloadUpdate()
  ├─ activeProvider.downloadAsset(release, assetId, { onProgress, signal })
  ├─ 写 cache/sage-update-{version}.tmp
  ├─ （仅 Generic HTTP）verifyArtifact(localPath, signature, publicKey)
  ├─ （平台 provider 若 requireArtifactSignature）同上
  ├─ （所有 provider）checksum 比对（如有）
  ├─ 校验失败 → 删 .tmp + 报错
  └─ 通过 → 触发 electron-updater install path（feed URL = file://）
```

### 5.4 切换 Provider

```
provider:set-default {id}
  ├─ ProviderStore.setDefault(id)   # 持久化 + 唯一性
  ├─ UpdateManager.switchProvider(id)
  │   ├─ 解密 + registry.build
  │   ├─ 取消进行中的下载/检查（AbortSignal）
  │   ├─ 替换 activeProvider 内存实例
  │   └─ 触发后台自动 check（若策略启用）
  └─ 推 update:state-changed，renderer toast："已切换到 {name}"
```

## 6. 错误处理

| 错误源 | 处理 |
|---|---|
| token 过期 / 撤销 | 红色横幅 + 引导跳 ProvidersManager；不自动重试 |
| 404 | UI："更新源配置错误（HTTP 404），请检查 repo/path" |
| 网络超时 | 黄色横幅："连接超时，30s 后将自动重试 1 次" |
| 5xx | UI："更新源暂时不可用（HTTP {status}）" |
| **签名失败** | **硬阻断**："签名校验失败，已拒绝此更新" + 安全事件日志 |
| 用户保存非法配置 | 表单红框，阻止保存 |
| 删除 default | 阻止 + 提示"请先切换到其他 provider" |
| safeStorage 不可用 | token 明文 + 路径 600 + 首次 warn |
| 磁盘满 | catch ENOSPC → 删 .tmp → "磁盘空间不足" |
| provider 内部抛 | UpdateManager 捕获 + 返回通用错误 |

## 7. 测试策略

### 7.1 单元测试

- `backend/test_update_providers_github.ts`：parse / channel map / asset filter / 401 / 404 / AbortSignal
- `backend/test_update_providers_gitee.ts`：同
- `backend/test_update_providers_gitlab.ts`：含自建 baseUrl
- `backend/test_update_providers_generic.ts`：含签名验证路径
- `backend/test_update_provider_store.ts`：encrypt/decrypt / 唯一 default 校验
- `backend/test_update_provider_registry.ts`：factory 映射

### 7.2 集成测试（nock 拦截）

- `backend/test_update_manager_integration.ts`：
  - 切换 active provider
  - 切换中取消 in-flight 下载
  - 无 provider 时 fallback Generic
  - Generic HTTP 改造后回归
  - progress events 顺序

### 7.3 端到端（Playwright）

- `e2e/journeys/update-providers.spec.ts`：
  - 添加 GitHub → 设 default → 检查可用
  - 切到自建 GitLab → 旧 provider 不被查询
  - 删除 default 被阻止
  - 凭证失效 → UI 引导

### 7.4 回归保护

- Generic HTTP **必须**在 E2E 中走一次真实环境（不 mock 签名）
- 现有 update-flow 集成测试保留；仅把"默认 = hardcoded updates.sage.app"改为"通过 ProviderStore 读 built-in Generic"

## 8. 实施阶段

| Phase | 内容 | 工作量 |
|---|---|---|
| **1** 抽象层骨架 | `providers/{base,registry,genericHttp}.ts` + `providerStore.ts` + `providerConfig.ts` + `providerIpc.ts` + UpdateManager 注入 + 内置 Generic fallback | 1.5 周 |
| **2** UI + ProviderStore 测试 | `ProvidersManager.tsx` + preload 类型 + ProviderStore 单元 / 集成测试 + UI 验收 | 1 周 |
| **3** 三个平台 provider + 测试 | GitHub / Gitee / GitLab adapter + nock 集成 + 安全审计（URL 白名单 / safeStorage） | 2 周 |
| **4** 端到端 + 文档 + 发布 | E2E + docs/technical + docs/user-manual + CHANGELOG + alpha 灰度 | 0.5 周 |

**总工作量约 5 周**（一个熟练 dev 估算）。

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| UpdateManager 改造引入回归 | 现网用户升级后无法更新 | Phase 1 完做 main ↔ old flow 并行（flag OFF 时走旧代码）；新 flow 单独 release |
| Generic 迁移漏掉签名校验 | 安全事件 | Phase 1 验收必须含"Generic 签名校验回归测试"，不 mock 签名 |
| safeStorage 不可用导致 token 明文 | 用户凭证泄露 | Phase 1 + safeStorage fallback 测试；README 明示 Linux 用户需密钥环 |
| UI 暴露给不熟用户 | 改坏 default 后无法升级 | 删除 default 阻止 + 凭证失效引导 + E2E 覆盖"用户能自救" |
| Phase 3 进度超期 | 二期功能拖延 | Phase 3 拆 PR；任一 provider 可独立 ship |

## 10. Feature Flag

```typescript
// electron/update/featureFlag.ts
export const ENABLE_UPDATE_PROVIDERS_UI = process.env.SAGE_EXPERIMENTAL_PROVIDERS === '1'
  || app.isPackaged === false; // dev 默认开
```

- Phase 1-2 完成：flag 控制 ProvidersManager UI 可见性；主进程 ProviderStore 总是启用（保证 Generic fallback 走新路径）
- Phase 3 完成：默认全开

## 11. 迁移 / 兼容性

- **不**做静默迁移（不读取老配置写 ProviderStore）
- **不**删老代码路径：硬编码 `updates.sage.app` 替换为内置 Generic HTTP 工厂调用，但调用接口和签名保持不变
- **不**破坏 `data/update-metadata/` 协议
- **不**动后端 manifest 服务 / release.yml / release-win7.yml
- 后端 manifest 服务继续作为 Generic provider 服务端

## 12. 与现有约定同步

- 不动 `.claude/CLAUDE.md` 现有约定（Python 环境 / 端口 / 并行开发 / release/win7）
- 新增"## 更新源配置"小节（如需）
- 不动 `electron-builder.yml`（`publish: null` 仍生效）

## 13. 后续可能扩展（二期）

- 平台分发策略：根据 locale / platform 自动选 provider
- provider marketplace / 远程注册中心
- Ed25519 / ECDSA 多签名算法
- 自动迁移老配置到 ProviderStore
- provider 模板（公司 IT 群发 update-providers.json 覆盖默认）

---

## 附录 A：文件路径速查

| 类别 | 文件 |
|---|---|
| 新建 - 接口/registry | `electron/update/providers/{base,registry}.ts` |
| 新建 - provider adapter | `electron/update/providers/{github,gitee,gitlab,genericHttp}.ts` |
| 新建 - 持久化 | `electron/update/{providerStore,providerConfig}.ts` |
| 新建 - IPC | `electron/update/providerIpc.ts` |
| 新建 - feature flag | `electron/update/featureFlag.ts` |
| 改造 | `electron/update/updateManager.ts`（注入 + 调用 provider） |
| 改造 | `electron/main.ts`（挂 providerIpc） |
| 新建 UI | `src/pages/settings/ProvidersManager.tsx` |
| 改造 UI | `src/preload/index.ts`（暴露 providers.*） |
| 改造类型 | `src/shared/types/electron-api.d.ts` |
| 单元测试 | `backend/test_update_providers_*.ts` |
| 集成测试 | `backend/test_update_manager_integration.ts` |
| E2E | `e2e/journeys/update-providers.spec.ts` |
| 文档 | `docs/technical/XX-pluggable-update-providers.md` |
| 用户手册 | `docs/user-manual/XX-update-providers.md` |