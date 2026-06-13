# 主分支 Electron 化与 win7-lts 分支策略设计

> 日期：2026-06-13
> 状态：待用户审阅
> 作者：Claude (brainstorming 流程产出)

## 1. 背景与目标

### 1.1 当前状态

| 分支 | 桌面壳 | Python | 活跃度 | 目标平台 |
|---|---|---|---|---|
| `main` | Tauri 2.1.1 | 3.10+ | 高（wiki-llm Phase 8） | Win10+/macOS/Linux |
| `release/win7` | Electron 21.4.4 | 3.10 (从 3.8 升) | 中（13 commit 迁移） | Win7 SP1 x64 |

**两个分支的核心问题**：

1. **维护负担**：两套 IPC shim、两套 CI、两套依赖矩阵、两套构建产物
2. **代码割裂**：main 上开发的新功能（wiki-llm Phase 8 等）无法在 Win7 桌面端用
3. **文档过时**：`release/win7/BRANCH_NOTES.md` 仍写"Tauri 1.6 + Python 3.8"，实际已是 Electron 21 + Python 3.10

### 1.2 目标

- **短期**：把 main 切到与 win7 完全一致的 Electron 21.4.4，前端/桌面壳 100% 统一
- **中期**：win7 走 LTS 模式，依赖版本钉死，新功能 cherry-pick
- **长期**：18 个月后 win7-lts 归档，Win7 用户迁 Web（Chrome 109+ / Firefox ESR 102+）

### 1.3 约束

- 18 个月+ 长期承诺（2026-06-13 → 2027-12-13）
- Win7 产品形态：桌面端 + Web 两种并行
- 桌面端 Win7 兼容性不破坏（Electron 21.4.4 + Python 3.8 必须保留）

## 2. 决策摘要

| 决策点 | 选择 | 理由 |
|---|---|---|
| 分支策略 | 主分支统一技术栈 + win7-lts 维护 | 满足长期承诺 + 减少开发工作量 |
| 桌面壳版本 | main 锁 Electron 21.4.4（与 win7 一致） | 单一 codebase，零 IPC 差异 |
| IPC shim 命名 | 改名为 `desktopInvoke` / `desktopEvent` | 旧名 `tauriInvoke` 误导（实际委托 Electron） |
| CI 架构 | 单 workflow + 多 matrix（按分支守卫） | 减少维护负担；win7 门禁绝对独立 |
| win7 分支名 | 保留 `release/win7`（不重命名） | 避免 Issue/Release 链接断裂 |
| win7 归档窗口 | 18 个月（2027-12-13） | 与产品承诺期一致 |

## 3. 架构设计

### 3.1 分支拓扑（迁移完成后）

```
main (PR #14 起活跃开发)
├── 桌面壳：Electron 21.4.4 + electron-builder 24.13.3
├── Python：3.10+ 主线（CI 也跑 3.8 兼容性检查）
├── 前端：React 18 + Vite + IPC shim (@/lib/desktopInvoke / desktopEvent)
├── 桌面端 IPC 内部：window.electronAPI（preload 注入）
├── CI：.github/workflows/ci.yml 单一工作流，多 matrix
└── 文档：docs/technical/20-electron.md（重写自 20-electron-win7.md）

release/win7 (从原 release/win7 继承，18 个月维护)
├── 钉死：electron@21.4.4, electron-builder@^24.13.3, python==3.8.x
├── 钉死：react@18, vite@5（lockfile 不动）
├── 接收：cherry-pick PR（仅 release commit + 安全修复）
├── CI：与 main 共享 ci.yml（用 if 守卫 win7 专属 job）
└── 文档：docs/technical/21-win7-lts.md（独立 LTS 章节）
```

### 3.2 双分支关系图

```
   feature/xxx ──PR──→ main ──rebase/merge──→ main HEAD
                          │
                          │ (cherry-pick 安全修复/Win7 特定)
                          ↓
                   release/win7
                          │
                          ↓
                  tag v0.X.Y-win7 ──→ GitHub Release
```

### 3.3 关键不变量

- `release/win7` 永远 = `main` 的某个历史 commit + Win7 钉死 overlay
- main 上**新功能不强制 backport**（按需 cherry-pick）
- main 上**破坏性变更不强制同步**到 win7（直到 win7 主动适配）
- win7 端的 `package-lock.json` 与 main 不再共享（独立 lockfile，钉死版本）

## 4. 代码改造（PR #14 一次性迁移）

### 4.1 改动清单

**package.json**（顶层字段 + scripts + devDependencies 三处改动）：

```diff
  {
    "name": "sage",
    "private": true,
    "version": "0.1.1",
    "type": "module",
+   "main": "dist-electron/main.js",
    "scripts": {
      "dev": "vite",
      "build": "tsc && vite build",
      "preview": "vite preview",
-     "postinstall": "node scripts/patch-webkit2js.mjs",
      "lint": "eslint .",
      "lint:fix": "eslint . --fix",
      "typecheck": "tsc --noEmit",
      "test": "vitest",
      "test:run": "vitest run",
      "test:coverage": "vitest run --coverage",
      "format": "prettier --write .",
      "format:check": "prettier --check .",
+     "build:electron": "tsc -p tsconfig.electron.json && node -e \"require('fs').writeFileSync('dist-electron/package.json', JSON.stringify({type:'commonjs'},null,2))\"",
+     "typecheck:electron": "tsc -p tsconfig.electron.json --noEmit",
+     "electron:dev": "npm run build:electron && electron .",
+     "electron:build": "npm run build && npm run build:electron",
+     "electron:dist": "npm run electron:build && electron-builder --publish never"
    },
    "dependencies": {
      "@headlessui/react": "^1.7.17",
-     "@tauri-apps/api": "=2.1.0",
      "@xyflow/react": "^12.11.0",
      ...
    },
    "devDependencies": {
      ...
-     "@tauri-apps/cli": "=2.1.0",
+     "electron": "^21.4.4",
+     "electron-builder": "^24.13.3",
+     "@playwright/test": "^1.60.0",
      ...
    }
  }
```

**.gitignore**：

```diff
+ dist-electron/
+ release/                # electron-builder 产物
+ .playwright/
```

**新增文件**（从 `release/win7` 复制）：

- `electron/main.ts`
- `electron/preload.ts`
- `electron-builder.yml`
- `tsconfig.electron.json`
- `playwright.config.ts`
- `tests/electron/smoke.spec.ts`
- `tests/electron/global.d.ts`
- `src/types/electron-api.d.ts`

**改造文件**：

- `src/lib/tauriInvoke.ts` → 改名为 `src/lib/desktopInvoke.ts`，内部委托 `window.electronAPI.invoke`
- `src/lib/tauriEvent.ts` → 改名为 `src/lib/desktopEvent.ts`，内部委托 `window.electronAPI.listen`
- `vite.config.ts` → 合并 win7 的 electron 适配
- `src-tauri/` → 归档到 `archive/src-tauri-2026-06-13-main-migration/`

**删除文件**：

- `scripts/patch-webkit2js.mjs`（Tauri 专用补丁）

### 4.2 执行步骤

1. 建 PR #14 分支 `feat/main-migrate-to-electron`
2. 先归档 `src-tauri/` → `archive/src-tauri-2026-06-13-main-migration/`
3. 复制 win7 现有 electron 资产到 main
4. 改 package.json：删 tauri 依赖 + scripts，加 electron 依赖 + scripts
5. 改 vite.config.ts：合并 win7 的 base/build 配置
6. 改 IPC shim：旧名字保留为 `@deprecated` re-export，新名字为正式 API
7. 改 ESLint/Prettier 配置：加 `electron/`, `tests/electron/`
8. 改 CI 工作流：合并为单 workflow（详见第 6 节）
9. 本地验证（详见第 8 节验收清单）
10. 删 `scripts/patch-webkit2js.mjs`
11. 更新 README + docs/technical/

### 4.3 测试影响

- 21 个 vitest 测试文件：mock 路径从 `@/lib/tauriInvoke` 改为 `@/lib/desktopInvoke`（6 个月内逐步迁移，旧的通过 `@deprecated` re-export 兜底）
- `tests/electron/smoke.spec.ts`：从 win7 直接复制
- 真机 Win7 烟测仍在 `release/win7` 上跑

### 4.4 回滚策略

- 整 PR 可独立 revert（一笔 commit，标题 `feat: migrate main from Tauri to Electron 21.4.4`）
- 归档文件保留在 `archive/`，可恢复

## 5. IPC shim 命名

### 5.1 决策：改名为 `desktopInvoke` / `desktopEvent`

**理由**：
- 旧名 `tauriInvoke` 误导（实际委托 `window.electronAPI`，与 Tauri 无关）
- 改一次 21 个文件 vs 18 个月内天天看误导名字 —— 短期痛换长期清晰
- 新功能（chat streaming、wiki RAG）已经在写新代码，趁早定名

### 5.2 迁移策略

```typescript
// src/lib/desktopInvoke.ts（新正式 API）
export async function invoke<T>(cmd: string, args?: unknown): Promise<T> {
  if (window.electronAPI?.invoke) {
    return window.electronAPI.invoke(cmd, args)
  }
  throw new Error('Desktop runtime not available')
}

// src/lib/tauriInvoke.ts（保留 6 个月，标 @deprecated）
/** @deprecated use @/lib/desktopInvoke */
export { invoke } from './desktopInvoke'
```

- 旧名 re-export 保留 6 个月（2026-06 ~ 2026-12）
- 期间新代码禁止 `import` 旧名（ESLint 规则禁用 `tauriInvoke` 直接 import）
- 6 个月后（2026-12）删除旧 re-export 文件

## 6. CI 改造

### 6.1 决策：单 workflow + 多 matrix

**文件结构**：

```
.github/workflows/
└── ci.yml          # 唯一 CI 文件
    ├── if: github.ref == 'refs/heads/release/win7'  → 跑 backend-py38 + win7 electron-build
    └── if: github.ref == 'refs/heads/main'          → 跑 backend-modern (3.10/3.11/3.12) + modern electron-build
```

**job 矩阵**：

| job 名 | 触发分支 | 内容 | 强门禁 |
|---|---|---|---|
| `backend-py38` | win7 | Python 3.8 + 锁版本依赖安装 + coverage ≥ 80% | ✅ |
| `backend-modern` | main | Python 3.10/3.11/3.12 矩阵 + coverage ≥ 80% | ✅ |
| `frontend` | 两个分支 | Node 20 LTS + build + lint + test | ✅ |
| `electron-build` | 两个分支 | 跨平台 build (windows/macos/ubuntu) | ✅ |
| `electron-smoke` | 两个分支 | Playwright 启动 Electron + 基本交互 | ✅ |
| `win7-real-machine` | win7 | 触发 `scripts/win7-smoke/` PowerShell 流程（人工/真机） | 文档强门禁 |

### 6.2 关键守卫示例

```yaml
backend-py38:
  if: github.ref == 'refs/heads/release/win7'
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: conda-incubator/setup-miniconda@v3
      with:
        python-version: '3.8'
    - run: |
        conda create -n sage-backend-py38 python=3.8 -y
        conda run -n sage-backend-py38 pip install -r backend/requirements.txt
    - run: conda run -n sage-backend-py38 pytest backend/tests --cov=backend --cov-fail-under=80
```

## 7. win7 分支生命周期

### 7.1 18 个月时间表

| 阶段 | 时间窗 | 目标 | 触发条件 |
|---|---|---|---|
| **Phase 1：共存期** | 2026-06 ~ 2026-12 | main + win7 并行开发，cherry-pick 通道打通 | 默认状态 |
| **Phase 2：减维护期** | 2027-01 ~ 2027-06 | Win7 用户数 < 10% → 减少 patch 频率 | 季度 review |
| **Phase 3：弃用通知期** | 2027-07 ~ 2027-09 | 发"Win7 桌面端 EOL"公告，引导用户迁 Web | 距归档 90 天 |
| **Phase 4：归档期** | 2027-10 ~ 2027-12 | 分支 read-only，GitHub Release 标 "DEPRECATED" | 距归档 60 天 |
| **Phase 5：删除期** | 2027-12-13+ | `git push origin --delete release/win7` | 到期 |

### 7.2 季度 review 检查项

- 提交数 (commits/quarter)：< 5 → 进 Phase 2
- 活跃 Win7 用户数：< 10% → 进 Phase 2
- Win7 烟测通过率：< 95% → 评估提前 EOL
- 安全 CVE 数：> 0/quarter → 评估提前 EOL

### 7.3 Win7 用户迁移到 Web 通道

- Phase 3 时发公告：「Sage 桌面端 Win7 支持将于 2027-12-31 终止，请迁移到 Chrome 109+ / Firefox ESR 102+ 访问 https://sage.example.com」
- 公告模板写入 `docs/user-manual/notifications/2027-09-win7-deprecation.md`
- 部署 Web 服务（Sage 后端 + 前端静态资源到任意 HTTPS 主机）

### 7.4 归档检查清单（Phase 5 执行前）

- [ ] Win7 活跃用户 < 5%（无关键客户依赖）
- [ ] Web 端服务稳定运行 3 个月
- [ ] Win7 桌面端用户已发 3 次 EOL 通知
- [ ] 文档已加 DEPRECATED 横幅
- [ ] GitHub Release 标 "Win7 桌面端最后一次发布 v0.X.Y-win7"
- [ ] 所有 Win7 烟测脚本归档到 `archive/win7-smoke-2027-12-13/`

### 7.5 归档后

- `release/win7` 分支 read-only（GitHub 分支保护）
- Win7 安装包仍可下载（GitHub Releases 不删）
- 新功能只发 Web 版

## 8. 风险与回滚

### 8.1 风险表

| 风险 | 等级 | 影响 | 缓解 / 回滚 |
|---|---|---|---|
| PR #14 改造 main 失败，回滚复杂 | 🟡 中 | main 桌面壳跑不起来 | 整 PR 一次 revert；归档文件可恢复 |
| IPC shim 改名遗漏 | 🟡 中 | 部分功能静默失效 | `@deprecated` re-export 6 个月兜底；ESLint 规则禁用旧名 |
| win7 依赖版本被 main 升级污染 | 🔴 高 | Win7 兼容性破坏 | win7 独立 `package-lock.json` + `npm ci --no-update-notifier`；CI 加版本断言 |
| CI 单 workflow 复杂度过高 | 🟡 中 | 新人看不懂 | 详细 README + 注释；Phase 2 评估拆分为双 workflow |
| Win7 真机烟测 CI 缺失 | 🟡 中 | 18 个月内拿不到 Win7 物理机 = 无法验证 | 已有 `scripts/win7-smoke/` PowerShell 脚本 + 文档 |
| 18 个月承诺期用户群流失 | 🟢 低 | 维护负担低于预期 | Phase 2 提前进入 EOL 流程 |
| Electron 21 安全 CVE | 🟡 中 | 21.4.4 已 EOL | win7 风险声明在 BRANCH_NOTES；CVE 不修，引导用户迁 Web |

### 8.2 回滚剧本

```bash
# 场景 1: PR #14 整体回滚
git revert <pr-14-merge-commit>   # 一笔 revert
git push origin main

# 场景 2: 部分回滚（如 IPC 改名引发测试问题）
git revert <desktop-invoke-rename-commit>

# 场景 3: win7 独立回滚（与 main 无关）
cd release/win7
git revert <cherry-pick-commit>
```

### 8.3 PR #14 合并后 30 天监控指标

- [ ] main 上 `npm run electron:dev` 在 3 OS 都能启动
- [ ] main 上 `npm run electron:dist` 产出 .msi/.dmg/.AppImage
- [ ] 21 个 vitest 测试全过
- [ ] `tests/electron/smoke.spec.ts` 通过
- [ ] `release/win7` 仍能从 main cherry-pick
- [ ] docs/technical/20-electron.md 替代 20-electron-win7.md

## 9. 验收清单（PR #14 合并门禁）

代码层：
- [ ] `package.json` 无 `@tauri-apps/*` 依赖
- [ ] `package.json` 有 `electron@^21.4.4` + `electron-builder@^24.13.3`
- [ ] `electron/main.ts` 编译通过
- [ ] `electron/preload.ts` 编译通过
- [ ] `src/lib/desktopInvoke.ts` 存在
- [ ] `src/lib/desktopEvent.ts` 存在
- [ ] `src/lib/tauriInvoke.ts` 标 `@deprecated` re-export
- [ ] `src/lib/tauriEvent.ts` 标 `@deprecated` re-export
- [ ] `src-tauri/` 已归档到 `archive/src-tauri-2026-06-13-main-migration/`
- [ ] `scripts/patch-webkit2js.mjs` 已删

CI 层：
- [ ] `.github/workflows/ci.yml` 是单文件
- [ ] `backend-py38` job 守卫 `if: github.ref == 'refs/heads/release/win7'`
- [ ] `backend-modern` job 守卫 `if: github.ref == 'refs/heads/main'`
- [ ] `electron-build` 多 OS 矩阵 (windows/macos/ubuntu) 跑通
- [ ] `electron-smoke` 跑通
- [ ] PR 触发条件包含 `release/**`

测试层：
- [ ] 21 个 vitest 测试文件全过
- [ ] 6 个 vitest 文件已迁移到 `@/lib/desktopInvoke` import（其他 15 个通过 re-export 兜底）
- [ ] `tests/electron/smoke.spec.ts` 通过
- [ ] `npm run typecheck` 0 error
- [ ] `npm run lint` 0 warning

文档层：
- [ ] `docs/technical/20-electron.md` 重写自 20-electron-win7.md
- [ ] `docs/technical/21-win7-lts.md` 新增（独立 LTS 章节）
- [ ] `docs/technical/20-win7-tauri-compat.md` 归档
- [ ] `docs/11-structure.md` 加 Electron 章节
- [ ] `docs/design.md` 桌面壳段落更新
- [ ] `README.md` 桌面端启动命令更新
- [ ] `BRANCH_NOTES.md`（win7）内容刷新（"Tauri 1.6" → "Electron 21.4.4"）

跨分支：
- [ ] 从 main 创建一个测试 cherry-pick PR → release/win7 → CI 全过
- [ ] release/win7 上的 `package-lock.json` 独立（与 main 不共享）

## 10. 范围说明

### 10.1 本设计**包含**

- main 分支 Electron 化（PR #14）
- IPC shim 改名（desktopInvoke/desktopEvent）
- CI 单 workflow 改造
- win7 分支保留 + 钉死 overlay
- 18 个月生命周期时间表

### 10.2 本设计**不**包含

- Win7 桌面端 EOL 公告的文案细节（Phase 3 时再定）
- Web 化部署架构（Sage 后端 + 静态前端的 HTTPS 部署）（独立 spec）
- release/win7 上的 release workflow 文件改动（PR #14 不动 release.yml）
- 18 个月后 win7 归档的实际执行（独立 plan）

## 11. 后续 plan 拆分建议

writing-plans skill 应将本设计拆分为 4 个独立 plan：

1. **Plan A**：PR #14 main 迁移（Tauri → Electron）
2. **Plan B**：CI 单 workflow 改造（含 backend-py38 守卫）
3. **Plan C**：IPC shim 改名（desktopInvoke/desktopEvent，分批迁移）
4. **Plan D**：win7 BRANCH_NOTES + docs 同步更新
