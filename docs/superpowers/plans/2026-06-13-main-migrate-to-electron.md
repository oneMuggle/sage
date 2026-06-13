# Plan A: PR #14 main 迁移（Tauri → Electron 21.4.4）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `main` 分支的桌面壳从 Tauri 2.1.1 完全切到 Electron 21.4.4，与 `release/win7` 统一。

**Architecture:** 一次性 PR #14 包含归档 src-tauri/、复制 win7 electron 资产、改 package.json、合并 vite 配置。IPC shim 改名（desktopInvoke/desktopEvent）放在 Plan C，本 Plan A 保持 `tauriInvoke`/`tauriEvent` 名字以便 21 个测试文件零修改通过。

**Tech Stack:** Electron 21.4.4 + electron-builder 24.13.3 + Node 20 LTS + Vite 5 + React 18

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `archive/src-tauri-2026-06-13-main-migration/` | Create (move) | Tauri 2.1.1 完整代码（保留可恢复） |
| `electron/main.ts` | Create (copy from win7) | Electron 主进程（FastAPI 子进程 + BrowserWindow + IPC） |
| `electron/preload.ts` | Create (copy from win7) | contextBridge 注入 electronAPI |
| `electron-builder.yml` | Create (copy from win7) | 跨平台打包配置 |
| `tsconfig.electron.json` | Create (copy from win7) | Electron TypeScript 配置 |
| `playwright.config.ts` | Create (copy from win7) | Playwright-Electron 烟测配置 |
| `tests/electron/smoke.spec.ts` | Create (copy from win7) | 启动 + 加载 + 基本交互测试 |
| `tests/electron/global.d.ts` | Create (copy from win7) | Playwright 全局类型 |
| `src/types/electron-api.d.ts` | Create (copy from win7) | `window.electronAPI` 类型声明 |
| `package.json` | Modify | 删 `@tauri-apps/*`，加 `electron`/`electron-builder` |
| `vite.config.ts` | Modify | 合并 win7 的 base/build 配置 |
| `.gitignore` | Modify | 加 `dist-electron/`, `release/`, `.playwright/` |
| `src-tauri/` | Delete (move to archive) | 整个目录 |
| `scripts/patch-webkit2js.mjs` | Delete | Tauri 专用补丁，Electron 不需要 |
| `src/lib/tauriInvoke.ts` | Keep as-is | 内部已委托 `window.electronAPI.invoke`（无需改） |
| `src/lib/tauriEvent.ts` | Keep as-is | 内部已委托 `window.electronAPI.listen`（无需改） |
| `README.md` | Modify | 桌面端启动命令更新 |
| `docs/design.md` | Modify | 桌面壳段落更新 |

---

## Task 1: 建 feature 分支

**Files:** 无

- [ ] **Step 1: 切换到 main 并更新**

```bash
cd /home/fz/project/sage
git switch main
git pull --rebase origin main
```

Expected: 已切到 main 且与 origin 同步

- [ ] **Step 2: 建 feature 分支**

```bash
git switch -c feat/main-migrate-to-electron
```

Expected: 已切到 `feat/main-migrate-to-electron`

- [ ] **Step 3: 验证状态干净**

```bash
git status
```

Expected: `nothing to commit, working tree clean`

---

## Task 2: 归档 src-tauri/ 到 archive/

**Files:**
- Move: `src-tauri/*` → `archive/src-tauri-2026-06-13-main-migration/`

- [ ] **Step 1: 用 git mv 归档整个目录（保留历史）**

```bash
git mv src-tauri archive/src-tauri-2026-06-13-main-migration
```

Expected: 输出 `Renaming src-tauri/...` 多行（无错误）

- [ ] **Step 2: 验证归档成功**

```bash
ls archive/src-tauri-2026-06-13-main-migration/ | head
```

Expected: 输出包含 `Cargo.toml`, `Cargo.lock`, `build.rs`, `src/`, `icons/`

- [ ] **Step 3: 验证 src-tauri/ 已消失**

```bash
ls src-tauri 2>&1 || echo "GONE (expected)"
```

Expected: `GONE (expected)`

- [ ] **Step 4: 提交归档**

```bash
git add archive/src-tauri-2026-06-13-main-migration
git commit -m "chore(main): archive src-tauri/ to archive/ for electron migration

- 归档日期：2026-06-13
- 归档原因：main 切到 Electron 21.4.4 (与 win7 一致)
- 归档路径：archive/src-tauri-2026-06-13-main-migration/
- 恢复方式：git mv archive/src-tauri-2026-06-13-main-migration src-tauri"
```

Expected: 1 commit, ~25 files renamed

---

## Task 3: 复制 win7 的 electron 资产到 main

**Files:**
- Create: `electron/main.ts` (from win7)
- Create: `electron/preload.ts` (from win7)
- Create: `electron-builder.yml` (from win7)
- Create: `tsconfig.electron.json` (from win7)
- Create: `playwright.config.ts` (from win7)
- Create: `tests/electron/smoke.spec.ts` (from win7)
- Create: `tests/electron/global.d.ts` (from win7)
- Create: `src/types/electron-api.d.ts` (from win7)

- [ ] **Step 1: 从 win7 分支导出 electron/ 目录**

```bash
git show release/win7:electron/main.ts > electron/main.ts
git show release/win7:electron/preload.ts > electron/preload.ts
git show release/win7:electron-builder.yml > electron-builder.yml
git show release/win7:tsconfig.electron.json > tsconfig.electron.json
git show release/win7:playwright.config.ts > playwright.config.ts
git show release/win7:tests/electron/smoke.spec.ts > tests/electron/smoke.spec.ts
git show release/win7:tests/electron/global.d.ts > tests/electron/global.d.ts
git show release/win7:src/types/electron-api.d.ts > src/types/electron-api.d.ts
mkdir -p electron tests/electron src/types
```

Expected: 8 个文件创建成功，无报错

- [ ] **Step 2: 验证文件非空**

```bash
wc -l electron/main.ts electron/preload.ts electron-builder.yml tsconfig.electron.json playwright.config.ts tests/electron/smoke.spec.ts tests/electron/global.d.ts src/types/electron-api.d.ts
```

Expected: 每个文件 50+ 行（main.ts 约 350 行）

- [ ] **Step 3: 暂存新增文件（先不 commit）**

```bash
git add electron/ tests/ src/types/electron-api.d.ts electron-builder.yml tsconfig.electron.json playwright.config.ts
git status --short
```

Expected: 输出以 `A` 开头的新增文件行

---

## Task 4: 改 package.json（删 tauri，加 electron）

**Files:**
- Modify: `package.json`（顶层 + scripts + dependencies + devDependencies）

- [ ] **Step 1: 用 Edit 工具修改 package.json**

打开 `package.json`，做以下 diff：

**顶层字段加 `main`**（在 `"type": "module"` 之后）：

```diff
   "type": "module",
+  "main": "dist-electron/main.js",
   "scripts": {
```

**scripts 段：删 postinstall，加 electron 脚本**：

```diff
     "preview": "vite preview",
-    "postinstall": "node scripts/patch-webkit2js.mjs",
     "lint": "eslint .",
     ...
     "format:check": "prettier --check ."
+    "build:electron": "tsc -p tsconfig.electron.json && node -e \"require('fs').writeFileSync('dist-electron/package.json', JSON.stringify({type:'commonjs'},null,2))\"",
+    "typecheck:electron": "tsc -p tsconfig.electron.json --noEmit",
+    "electron:dev": "npm run build:electron && electron .",
+    "electron:build": "npm run build && npm run build:electron",
+    "electron:dist": "npm run electron:build && electron-builder --publish never"
   },
```

**dependencies：删 `@tauri-apps/api`**：

```diff
     "@headlessui/react": "^1.7.17",
-    "@tauri-apps/api": "=2.1.0",
     "@xyflow/react": "^12.11.0",
```

**devDependencies：删 `@tauri-apps/cli`，加 `electron` / `electron-builder` / `@playwright/test`**：

```diff
     "@eslint/js": "^9.39.4",
+    "@playwright/test": "^1.60.0",
     "@testing-library/jest-dom": "^6.9.1",
     ...
-    "@tauri-apps/cli": "=2.1.0",
+    "electron": "^21.4.4",
+    "electron-builder": "^24.13.3",
     "eslint": "^9.39.4",
```

- [ ] **Step 2: 验证 package.json JSON 合法**

```bash
node -e "JSON.parse(require('fs').readFileSync('package.json', 'utf8')); console.log('valid JSON')"
```

Expected: `valid JSON`

- [ ] **Step 3: 验证 tauri 依赖完全消失**

```bash
grep -E "@tauri-apps|patch-webkit2js" package.json && echo "STILL HAS TAURI" || echo "TAURI REMOVED"
```

Expected: `TAURI REMOVED`

- [ ] **Step 4: 验证 electron 依赖已加**

```bash
grep -E '"electron"|electron-builder' package.json
```

Expected: 至少 3 行匹配（devDependencies electron、electron-builder、scripts electron:dev/build/dist）

---

## Task 5: 改 .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: 加 electron-builder 产物 + playwright 缓存**

在文件末尾追加：

```gitignore
# Electron builder
dist-electron/
release/

# Playwright
.playwright/
test-results/
playwright-report/
```

- [ ] **Step 2: 验证**

```bash
tail -10 .gitignore
```

Expected: 包含 `dist-electron/`, `release/`, `.playwright/`, `test-results/`, `playwright-report/`

---

## Task 6: 改 vite.config.ts（合并 win7 的 electron 适配）

**Files:**
- Modify: `vite.config.ts`

- [ ] **Step 1: 查看当前 main 的 vite.config.ts**

```bash
cat vite.config.ts
```

Expected: 输出当前配置（可能没有 `base` 字段，或有 Tauri 适配）

- [ ] **Step 2: 查看 win7 的 vite.config.ts**

```bash
git show release/win7:vite.config.ts
```

Expected: 输出 win7 的配置（已含 Electron 适配，如 `base: './'`）

- [ ] **Step 3: 合并配置**

如果 win7 有 `base: './'` 字段，加到 main 的 `defineConfig({})` 块内：

```typescript
export default defineConfig({
  // ... existing config
  base: './',  // Electron 加载本地资源需要相对路径
  // ... existing config
})
```

如果 win7 还有其他 Electron 相关字段（build target, server config 等），逐个复制。

- [ ] **Step 4: 验证 vite 配置类型正确**

```bash
npx tsc --noEmit vite.config.ts
```

Expected: 无错误

---

## Task 7: 删 scripts/patch-webkit2js.mjs

**Files:**
- Delete: `scripts/patch-webkit2js.mjs`

- [ ] **Step 1: 删除文件**

```bash
git rm scripts/patch-webkit2js.mjs
```

Expected: 输出 `rm 'scripts/patch-webkit2js.mjs'`

- [ ] **Step 2: 验证已删**

```bash
ls scripts/patch-webkit2js.mjs 2>&1 || echo "GONE"
```

Expected: `GONE`

---

## Task 8: 跑 npm install 验证依赖

**Files:** 无（仅验证）

- [ ] **Step 1: 清理旧 node_modules（可选）**

```bash
rm -rf node_modules/.package-lock.json
```

- [ ] **Step 2: 跑 npm install**

```bash
npm install
```

Expected: 成功，下载 electron + electron-builder + @playwright/test

- [ ] **Step 3: 验证 electron 已装**

```bash
npx electron --version
```

Expected: `v21.4.4` 或 `21.x.x`

- [ ] **Step 4: 验证 tauri 包不再存在**

```bash
ls node_modules/@tauri-apps 2>&1 || echo "TAURI REMOVED FROM node_modules"
```

Expected: `TAURI REMOVED FROM node_modules`

---

## Task 9: 跑 typecheck 验证 TypeScript 编译

**Files:** 无（仅验证）

- [ ] **Step 1: 跑前端 typecheck**

```bash
npm run typecheck
```

Expected: 0 error

- [ ] **Step 2: 跑 Electron typecheck**

```bash
npm run typecheck:electron
```

Expected: 0 error

- [ ] **Step 3: 如果有错，修复**

常见错误：missing types, 引用了不存在的 .d.ts。检查 `src/types/electron-api.d.ts` 是否与 `electron/preload.ts` 的 `contextBridge.exposeInMainWorld` 字段一致。

---

## Task 10: 跑 lint 验证

**Files:** 无（仅验证）

- [ ] **Step 1: 跑 lint**

```bash
npm run lint
```

Expected: 0 error, 0 warning

- [ ] **Step 2: 如果有错，修复**

常见错误：`electron/` 和 `tests/electron/` 目录未在 `eslint.config.js` 的 include 列表里。

如果需要，加 `electron/**/*.ts` 和 `tests/electron/**/*.ts` 到 ESLint 的 include 模式。

---

## Task 11: 跑 vitest 21 个测试

**Files:** 无（仅验证）

- [ ] **Step 1: 跑测试**

```bash
npm run test:run
```

Expected: 21 files / 99 tests 全部通过

- [ ] **Step 2: 验证测试数量**

```bash
npm run test:run 2>&1 | grep -E "Test Files|Tests"
```

Expected: 看到 `Test Files: 21 passed` 和 `Tests: 99 passed`

- [ ] **Step 3: 如果有测试失败**

`tauriInvoke.ts` 内部已委托 `window.electronAPI`，不应有变化。检查：
- mock 路径仍然是 `@/lib/tauriInvoke`（**不改**，Plan C 才改）
- `window.electronAPI` 在测试环境被 stub 成 `undefined`，`invoke()` 会抛"electronAPI not available"——这是 vitest 期望行为

---

## Task 12: 跑 Electron smoke test

**Files:** 无（仅验证；Playwright 启动 Electron）

- [ ] **Step 1: 跑 Playwright electron 测试**

```bash
npx playwright test tests/electron/smoke.spec.ts --project=electron
```

Expected: 1 test passed（在 headless 环境）

- [ ] **Step 2: 如果失败**

检查：
- `playwright.config.ts` 的 `webServer` 是否正确指向 FastAPI 启动命令
- `tests/electron/smoke.spec.ts` 是否引用 `tests/electron/global.d.ts` 的 `electron` project

---

## Task 13: 验证 npm run electron:dev 启动

**Files:** 无（手动验证）

- [ ] **Step 1: 启动后端（独立 terminal）**

```bash
conda activate sage-backend
cd /home/fz/project/sage
python backend/main.py
```

Expected: 后端监听 127.0.0.1:8765，`/health` 返回 200

- [ ] **Step 2: 启动 Electron（独立 terminal）**

```bash
cd /home/fz/project/sage
npm run electron:dev
```

Expected: Electron 窗口打开，加载 Vite dev URL (http://localhost:1420)，前端 React 应用渲染

- [ ] **Step 3: 验证基本交互**

在 Electron 窗口中：
- 点击 Settings → 验证 IPC invoke 工作
- 切到 Wiki → 验证 RAG 工作

- [ ] **Step 4: 关闭 Electron**

Expected: 后端子进程被 Electron main 干净关闭（无 zombie 进程）

```bash
ps aux | grep -E "python.*backend" | grep -v grep
```

Expected: 无 python backend 进程残留

---

## Task 14: 验证 npm run electron:dist 跨平台 build

**Files:** 无（手动验证；当前 OS 才能 build 当前 OS 产物）

- [ ] **Step 1: 跑 build**

```bash
cd /home/fz/project/sage
npm run electron:dist
```

Expected: 产出 `release/` 目录，含安装包

- [ ] **Step 2: 验证产物**

```bash
ls -la release/ 2>/dev/null | head
```

Expected: 看到 `.exe`（Windows）/ `.dmg`（macOS）/ `.AppImage`（Linux）之一，取决于当前 OS

- [ ] **Step 3: 验证 dist-electron/ 输出**

```bash
ls dist-electron/
```

Expected: 看到 `main.js`, `preload.js`, `package.json`（TypeScript 编译产物）

---

## Task 15: 更新 README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 找到桌面端启动段落**

```bash
grep -n "tauri\|npm run tauri" README.md
```

Expected: 找到包含 Tauri 命令的段落

- [ ] **Step 2: 替换为 Electron 命令**

找到段落，把：

```markdown
- 桌面端（开发）：`npm run tauri dev`
- 桌面端（生产）：`npm run tauri build`
```

替换为：

```markdown
- 桌面端（开发）：`npm run electron:dev`
- 桌面端（生产）：`npm run electron:dist`
```

- [ ] **Step 3: 删 Tauri 段落**

搜索整篇 README，把所有 `tauri` 字样（Tauri 2 升级章节等）替换为 `Electron`，或删除已过时的 Tauri-specific 段落。

---

## Task 16: 更新 docs/design.md 桌面壳段落

**Files:**
- Modify: `docs/design.md`

- [ ] **Step 1: 找到桌面壳段落**

```bash
grep -n "Tauri\|tauri" docs/design.md
```

Expected: 找到 Tauri 相关段落

- [ ] **Step 2: 替换为 Electron**

把段落中所有 `Tauri 2.x` 改为 `Electron 21.4.4`，把 `webview2-com` 改为 `Chromium 106`，把 `WRY runtime` 改为 `BrowserWindow + preload`。

---

## Task 17: 提交 PR #14

**Files:** 暂存所有变更

- [ ] **Step 1: 检查 git 状态**

```bash
git status
```

Expected: 看到 `M` (modified) 和 `A` (added) 文件，不应有 `D` (deleted) 来自本分支（除了 `scripts/patch-webkit2js.mjs`）

- [ ] **Step 2: 暂存所有**

```bash
git add -A
```

- [ ] **Step 3: 提交**

```bash
git commit -m "feat: migrate main from Tauri 2.1.1 to Electron 21.4.4

对齐 release/win7 技术栈：
- 删 src-tauri/，归档到 archive/src-tauri-2026-06-13-main-migration/
- 加 electron@21.4.4 + electron-builder@24.13.3 + @playwright/test@1.60.0
- 复制 win7 的 electron/main.ts, preload.ts, electron-builder.yml
- 复制 win7 的 tests/electron/smoke.spec.ts
- 改 vite.config.ts 加 base: './'
- 删 scripts/patch-webkit2js.mjs (Tauri 专用)
- 改 README.md + docs/design.md 桌面壳段落

桌面壳：main 与 win7 100% 统一
IPC shim 改名（desktopInvoke/desktopEvent）见 Plan C
CI 单 workflow 改造见 Plan B
文档同步（BRANCH_NOTES + 20-electron.md）见 Plan D

验证通过：
- npm run typecheck: 0 error
- npm run typecheck:electron: 0 error
- npm run lint: 0 error
- npm run test:run: 21 files / 99 tests passed
- npm run electron:dev: 启动成功
- npm run electron:dist: 产出 .exe/.dmg/.AppImage

Refs: docs/superpowers/specs/2026-06-13-electron-branch-strategy-design.md"
```

Expected: 1 commit

- [ ] **Step 4: 推 feature 分支**

```bash
git push -u origin feat/main-migrate-to-electron
```

Expected: 推送到 origin，建立 tracking

- [ ] **Step 5: 创建 PR #14**

```bash
gh pr create --title "feat: migrate main from Tauri 2.1.1 to Electron 21.4.4" --body "$(cat <<'EOF'
## 背景

main 切到 Electron 21.4.4，与 release/win7 统一。前端/桌面壳 100% 一致。

## 改动

- 删 src-tauri/ → archive/src-tauri-2026-06-13-main-migration/
- 加 electron@21.4.4 + electron-builder@24.13.3 + @playwright/test
- 复制 win7 的 electron/ + tests/electron/ + electron-builder.yml
- 改 vite.config.ts (base: './')
- 删 scripts/patch-webkit2js.mjs

## 验证

- [x] typecheck 通过
- [x] lint 通过
- [x] vitest 21 files / 99 tests 通过
- [x] electron:dev 启动成功
- [x] electron:dist 跨平台 build 成功

## 后续 plan

- Plan B: CI 单 workflow 改造
- Plan C: IPC shim 改名（desktopInvoke/desktopEvent）
- Plan D: win7 BRANCH_NOTES + 20-electron.md 文档同步

Refs: docs/superpowers/specs/2026-06-13-electron-branch-strategy-design.md
EOF
)"
```

Expected: PR URL 输出

---

## Self-Review Checklist (执行前)

- [ ] Task 1-17 全部步骤可执行（无占位符/TBD）
- [ ] 每个文件路径在主分支存在或将要被创建
- [ ] 命令在 bash 5 + Node 20 环境能跑
- [ ] 21 个 vitest 测试无需修改（IPC shim 名字保留 `tauriInvoke`）
- [ ] 归档路径 `archive/src-tauri-2026-06-13-main-migration/` 与 win7 一致命名规则
- [ ] PR 标题用 conventional commit `feat:` 前缀
- [ ] PR body 引用 spec 文件路径
