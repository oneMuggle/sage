# Win7 Core 最小安装包变体

> **分支**: `release/win7`（派生分支 `feat/win7-core-variant`）
> **日期**: 2026-11-18
> **目标**: 在 win7 发布流程中新增一个不含内置模型的 "core" 安装包，与现有 `.sagepkg` 组件包通道配合，覆盖"内网终端已有模型 / 仅需运行时"的轻量分发场景。

## 1. 背景与目标

### 1.1 现状
- win7 发布当前产出 2 个全量安装包 + 2 个 `.sagepkg`（`docs/plans/2026-11-17_offline-component-packs.md` §"后续"已预告）。
- 全量安装包（Source 379MB / Cython 335MB）固定内嵌 `resources/models` 下的 OCR + Embedding 模型（约 61MB）。
- `.sagepkg` 是独立的离线签名资产，可被设置页「组件管理」或 SageDoctor 导入到 `<userData>/models/`；运行时查找顺序 `userData > bundled`（`backend/memory/embedder_factory.py:48`、`backend/services/ocr/engines/rapidocr.py:147`）。
- 模型缺位时应用启动不阻断，降级为 `HashEmbedder`（`backend/memory/embedder_factory.py:15`）。

### 1.2 问题
- 内网已经部署了模型（或只使用远端 LLM、不需要本地 embedding/OCR）的终端，仍然被要求分发 379MB 全量包；`.sagepkg` 已就绪但 core 瘦包一直停留在"下一阶段"。

### 1.3 目标
- 在每次 `-win7` tag 发布中，额外产出 `Sage-Setup-<ver>-win7-core.exe`，与全量 Source 包同签发布。
- core 包不含 `resources/models`，体积预期从 379MB 降到 ~318MB。
- 发布说明的 Downloads 表增加 core 行，并注明"安装后导入 `.sagepkg` 以启用语义检索/OCR"。
- 顺带收紧：`.sagepkg` 构建步骤在 `SAGE_COMPONENT_SIGNING_KEY` 缺失时由 `warning + exit 0` 升级为 `error + 非零退出`，避免 release 静默缺失模型补装通道。

## 2. 方案选型

| 选项 | 描述 | 评估 |
| --- | --- | --- |
| A. 新增独立 `build-windows-core` job | 独立 job，复制 Source 流程但不下载模型 | ❌ 配置漂移风险，每次改 Source job 必须同步 |
| **B. Source job 内追加 core 构建步骤** | 全量包打完后再临时清空 `resources/models`，复用同一份 `electron-builder.yml` 再打一次 nsis，只覆盖 `artifactName` | ✅ 改动集中在 1 个 workflow；零配置漂移；构建缓存复用 |
| C. 引入 `electron-builder.core.yml` extends | 新建配置继承主配置并去掉 models filter | ❌ `extraResources` 是数组替换而非合并，维护成本高 |
| D. 把 Cython 包作为"事实上的 core" | 仅文档调整 | ❌ Cython 是实验性代码保护构建，与 core 定位不符 |

**选择 B**：实现成本最低、漂移风险最小；构建顺序保证全量包（379MB）先打出来，再打 core 包，互不影响。

## 3. 涉及文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `.github/workflows/release-win7.yml` | Modify | Source job 追加 3 个步骤；upload-release 改 core 包下载与校验；release body 模板追加 core 行；组件包缺失由 warning 升 error |
| `docs/technical/161-offline-component-packs.md` | Modify | §5.2 增加 core 变体产物清单 |
| `docs/technical/101-win7-offline-maintenance.md` | Modify | 离线维护包清单加 core 包 |
| `docs/technical/26-packaging-matrix.md` | Modify | 打包矩阵加 core 行 |
| `docs/user-manual/54-offline-component-packs.md` | Modify | 导入引导加 core 包说明 |
| `docs/plans/2026-11-18_win7-core-variant.md`（本文件） | Create | 实施计划 |

## 4. 实施步骤

### 4.1 Source job 追加 core 构建（`release-win7.yml`）

在现有 `Upload Source installer as artifact` 之后插入 3 个步骤：

```yaml
      # ── core 变体：不含 models 的瘦安装包 ──────────────────────
      # 模型已装进 resources/models 参与全量 nsis 打包；此处临时移开，
      # 让 electron-builder.yml 的 extraResources `from: resources/models`
      # 指向空目录，从而产出 ~61MB 更小的安装包。
      - name: Stage core variant — move models aside
        shell: pwsh
        run: |
          $moved = Join-Path $env:RUNNER_TEMP 'staged-models'
          if (Test-Path $moved) { Remove-Item -Recurse -Force $moved }
          Move-Item -Path 'resources\models' -Destination $moved -Force
          New-Item -ItemType Directory -Path 'resources\models' | Out-Null
          Write-Host "models moved to $moved; placeholder created"

      - name: Build Windows NSIS core (Win7 LTS - Source, no models)
        run: npx electron-builder --win nsis --publish never --config.win.artifactName='${productName}-Setup-${version}-core.${ext}'

      - name: Restore models after core build
        if: always()
        shell: pwsh
        run: |
          $moved = Join-Path $env:RUNNER_TEMP 'staged-models'
          if (Test-Path 'resources\models') { Remove-Item -Recurse -Force 'resources\models' }
          Move-Item -Path $moved -Destination 'resources\models' -Force
          Write-Host "models restored"

      - name: Upload core installer as artifact
        uses: actions/upload-artifact@v4
        with:
          name: sage-setup-core
          path: release/*/Sage-Setup-*-core.exe
          if-no-files-found: error
```

**要点**：
- `Move-Item` + 重建空目录：确保 electron-builder 的 `from: resources/models` filter 不会因目录不存在报错（`extraResources` filter 对空目录会返回 0 文件，不会把空目录本身打进包）。
- `if: always()` 的 restore 步骤：避免 core 构建失败时，runner 临时目录里的 models 被后续 job 复用污染 cache key。
- core 包名沿用 `Sage-Setup-<ver>-win7-core.exe`（artifactName 展开后）；`release/*/` glob 与现有 Source/Cython 一致。

### 4.2 upload-release 适配

```yaml
  upload-release:
    needs: [build-windows, build-windows-cython]
    # ...
    steps:
      - name: Download Source installer artifact
        ...
      - name: Download Cython installer artifact
        ...
      - name: Download core installer artifact      # 新增
        uses: actions/download-artifact@v4
        with:
          name: sage-setup-core
          path: artifacts/core
      - name: Download component packs artifact
        continue-on-error: true
        ...
      - name: Verify installers downloaded
        run: |
          set -e
          shopt -s nullglob globstar
          src=(artifacts/source/**/*.exe)
          cython=(artifacts/cython/**/*.exe)
          core=(artifacts/core/**/*.exe)
          if [ ${#src[@]} -eq 0 ]; then echo "::error::No source installer found"; exit 1; fi
          if [ ${#cython[@]} -eq 0 ]; then echo "::error::No cython installer found"; exit 1; fi
          if [ ${#core[@]} -eq 0 ]; then echo "::error::No core installer found"; exit 1; fi
          echo "Source:   ${src[0]##*/} ($(stat -c %s "${src[0]}") bytes)"
          echo "Cython:   ${cython[0]##*/} ($(stat -c %s "${cython[0]}") bytes)"
          echo "Core:     ${core[0]##*/} ($(stat -c %s "${core[0]}") bytes)"
```

`files: artifacts/**/*.exe` glob 已经覆盖 artifacts/core/，无需修改；`artifacts/components/**/*` 也不变。

### 4.3 发布说明模板追加 core 行

```diff
-### Downloads — Win7 LTS 提供两个版本
+### Downloads — Win7 LTS 提供三个版本

| File | 模式 | 备注 |
| --- | --- | --- |
| `Sage-Setup-*-win7.exe` | 源码模式 | ✅ **推荐**，含内置模型，离线即开即用 |
| `Sage-Setup-*-win7-core.exe` | 源码模式（无模型） | 轻量 ~318MB；安装后需通过设置页「组件管理」或 SageDoctor 导入 `.sagepkg` 以启用语义检索/OCR |
| `Sage-Setup-*-win7-cython.exe` | Cython 代码保护 | ⚠️ **实验性**，代码保护但有打包风险 |
| `embedding-bge-small-zh-*.sagepkg` | 离线组件包 | 必选（配合 core 包）；语义嵌入模型 |
| `ocr-models-ppocr-*.sagepkg` | 离线组件包 | 可选；OCR 模型组件包 |

如果不确定该选哪个，请优先使用源码模式（`-win7.exe`，无 `-cython` / `-core` 后缀）。
```

### 4.4 收紧组件包构建步骤

```diff
      - name: Build offline component packs
        shell: pwsh
        env:
          SAGE_COMPONENT_SIGNING_KEY: ${{ secrets.SAGE_COMPONENT_SIGNING_KEY }}
        run: |
          if ([string]::IsNullOrWhiteSpace($env:SAGE_COMPONENT_SIGNING_KEY)) {
-           Write-Host "::warning::SAGE_COMPONENT_SIGNING_KEY not configured; skipping component packs"
-           exit 0
+           Write-Host "::error::SAGE_COMPONENT_SIGNING_KEY not configured; cannot publish .sagepkg (required for core installer support)"
+           exit 1
          }
```

### 4.5 文档同步

- `docs/technical/161-offline-component-packs.md` §5.2 产物清单追加：
  - `Sage-Setup-<ver>-win7-core.exe`（轻量版，不含模型）
- `docs/technical/101-win7-offline-maintenance.md` 维护包清单：新增 "core 安装包（无模型）+ `.sagepkg` 模型包" 组合。
- `docs/technical/26-packaging-matrix.md` 矩阵：新增 core 变体行，标注"不含 models"。
- `docs/user-manual/54-offline-component-packs.md`：core 包安装后必导入 `.sagepkg`。

## 5. 风险与边界

### 5.1 预期收益 vs 实际
- **体积收益**：~61MB（模型净体积），379MB → ~318MB。
- **不是量级缩减**：Electron 21 + Python 3.8 + 后端是硬体积，core 不是"几十 MB"的瘦客户端。
- **功能降级**：core 包用户首次启动会看到 HashEmbedder 降级日志（非阻断），需导入 `.sagepkg` 后才能启用语义检索/OCR。

### 5.2 已知边界
- 模型查找顺序 `userData > bundled`，`.sagepkg` 安装到 `userData/models/`，与全量包兼容——core 包用户只需导入即可启用。
- Cython core 变体**不做**：Cython 是实验性代码保护，core 仅配合 Source 模式。如未来 Cython 转正，再考虑。
- main 分支**不**同步：core 变体只针对 win7 分支的内网分发场景，main 的打包矩阵不变。

### 5.3 冒烟用例
1. 本地构建（无 GitHub Actions）：临时 `mv resources/models /tmp/models` → `npx electron-builder --win nsis --publish never --config.win.artifactName='Sage-Setup-0.4.9-core.${ext}'` → 验证 `release/*/Sage-Setup-0.4.9-core.exe` 中不包含 `resources/models/*`（用 `7z l` 列出文件，grep 排除 `models/`）。
2. CI 验证：推 tag `v0.4.9-alpha.84-win7` → 看 release-win7 workflow 的 Source job 是否产出 `sage-setup-core` artifact；看 upload-release 是否上传到 release 页面；检查 assets 列表包含 3 个 exe + 2 个 sagepkg + 1 个 index。
3. 运行时验证：core 包安装 → 启动（HashEmbedder 降级日志） → 导入 embedding `.sagepkg` → 语义检索生效。

### 5.4 回滚
- 删除 Source job 追加的 3 个步骤 + upload-release 的 core 下载步骤 + release body 模板 core 行，恢复到上一版本即可；无数据迁移。

## 6. 任务拆分

- [x] **Task 1**: 修改 `release-win7.yml`：Source job 追加 core 构建 3 步 + 上传 artifact
- [x] **Task 2**: 修改 `release-win7.yml`：upload-release 增加 core 包下载与校验
- [x] **Task 3**: 修改 `release-win7.yml`：发布说明模板追加 core 行
- [x] **Task 4**: 修改 `release-win7.yml`：组件包构建步骤由 warning 升 error
- [x] **Task 5**: 文档同步（161、101、26-packaging-matrix、user-manual/54）
- [x] **Task 6**: 本地冒烟（仅 workflow YAML 语法 + 文档结构，真实构建靠 CI）

## 7. 不在本次范围

- Cython core 变体（留给 Cython 转正评估）。
- main 分支同步（留给 main 侧评审）。
- core 包首次启动引导 UX 改造（HashEmbedder 降级日志已足够；UI 改造列入下一阶段）。
- 自动下载模型（内网场景不适用；在线场景走现有 `electron/modelDownloadIpc.ts`）。
