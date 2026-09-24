# Win7 双版本打包 + 后端启动诊断 — 实施计划

> **关联 Spec：** `docs/superpowers/specs/2026-09-24-win7-dual-build-and-diagnostics-design.md`
> **分支：** `feat/win7-dual-build-diagnostics`（from `release/win7`）
> **目标：** 修复 Cython 打包缺失，实现双版本发布，加入启动诊断

---

## 实施步骤

### Phase 1：修复 `scripts/bundle-python.ps1`

> **实测：** 当前 worktree 的 `scripts/bundle-python.ps1`（375 行，源自 `release/win7` HEAD alpha.54）已包含 7 项修复中的 6 项。本阶段实际只需补 `packagingMode` 字段。

- [x] 1.1 `_pth` 加 `..` 条目（清理旧条目后追加）— 已在位（L133-158）
- [x] 1.2 保护模式前复制系统 Python Include/ + libs/ 到 embeddable — 已在位（使用 setup-python FULL Python）
- [x] 1.3 sage_core site-packages 复制（保护模式：.pyd + __init__.py；非保护：源码）— 已在位（L242-269）
- [x] 1.4 每个外部调用加 `$LASTEXITCODE` 检查 — 已在位（全脚本）
- [x] 1.5 `.pyd` 数量验证（编译后）— 已在位（L208-213）
- [x] 1.6 canary 验证（`import backend.main` + 保护模式 `.pyd` 断言）— 已在位（L355-370）
- [x] 1.7 保护模式下创建空 `resources/sage-core/` — 已在位（L216）
- [x] 1.8 编译后清理 Include/ + libs/ — 已在位
- [x] 1.9 build-manifest.json 加 `packagingMode` 字段 — 本次新增

### Phase 2：双版本 CI（`.github/workflows/release-win7.yml`）

- [ ] 2.1 拆为 `build-windows`（source）+ `build-windows-cython` 两个并行 job
- [ ] 2.2 Cython job 用 `--config.win.artifactName` 覆盖产物名（`-cython` 后缀）
- [ ] 2.3 upload job 合并两 job 产物，Release Notes 区分两版本

### Phase 3：运行时诊断（`electron/backendDiagnostics.ts` + `electron/main.ts`）

- [x] 3.1 新建 `backendDiagnostics.ts`，实现 `collectAndWriteDiagnostic()`
- [x] 3.2 `spawnBackend()` 中 `broken-installer` 分支调用诊断
- [x] 3.3 后端健康检查超时分支调用诊断
- [x] 3.4 后端非零退出分支调用诊断 + stderr buffer 通过 `recordBackendStderr()` 注入
- [x] 3.5 `showStartupFailureDialog` 增加 `diagnosticPath` 参数与"打开诊断目录"按钮

### Phase 4：验证

- [ ] 4.1 TypeScript 编译通过（`npm run build:electron`）
- [ ] 4.2 前端测试通过（`npm test`）
- [ ] 4.3 Commit + push + PR
- [ ] 4.4 CI 绿 → merge
- [ ] 4.5 打 tag → 发布 win7 安装包

---

## 进度

- 2026-09-24：计划完成，开始实施
