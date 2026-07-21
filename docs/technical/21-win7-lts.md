# Win7 LTS 维护

> Win7 SP1 x64 用户专属章节。`release/win7` 分支 18 个月维护窗口（2026-06-13 → 2027-12-13）。

---

## 1. Win7 LTS 分支定位

| 项       | 值                                                |
| -------- | ------------------------------------------------- |
| 分支     | `release/win7`                                    |
| 起点     | PR #13 合并日 (2026-06-13)                        |
| 终点     | 2027-12-13（分支归档）                            |
| 桌面壳   | Electron 21.4.4（与 main 一致）                   |
| Python   | 3.8.x（钉死在 `backend/requirements-py38.txt`）   |
| WebView  | 无（Electron 自带 Chromium 106）                  |
| 入口文档 | [`../technical/20-electron.md`](./20-electron.md) |

## 2. 与 main 的关系

- **main** 持续迭代，Electron 21.4.4 锁定 + Python 3.10+ 演进
- **release/win7** 只接受：
  - 安全修复（Electron 21 已知 CVE 修复不来自官方，由项目评估决定）
  - Win7 特定 bug 修复
  - Python 3.8 兼容性微调
- **不接受**：
  - 新功能
  - 依赖大版本升级（Electron 22+, Python 3.9+）
  - 性能重构
  - a11y 改进

**同步方式**：单 commit cherry-pick，commit message 加 `(cherry picked from main commit XXX)`。

## 3. Win7 启动验证（人工步骤）

> Win7 self-hosted runner 当前不可用，**Win7 启动验证 = 人工步骤**。

1. CI 跑通 `ci.yml`（backend-py38 + desktop-build + electron-smoke 都 success）
2. 维护者下载 artifact `electron-${{ matrix.os }}`（含 .msi / .exe / .AppImage）
3. 拷贝到 **Windows 7 SP1 x64 物理机或 VM**
4. 双击 `.exe`（NSIS 安装包），验证：
   - Electron 21.4.4 启动
   - sage 主窗口出现
   - 基本聊天功能可用
   - Wiki 标签页可打开
5. 在 release/win7 分支的 issue/PR 中报告验证结果

未来拿到 Win7 物理机/VM 后，把 `runs-on: windows-latest` 改回 `runs-on: [self-hosted, windows-7]` 即可恢复完整自动化。

## 4. 18 个月归档时间表

| 阶段                    | 时间窗            | 目标                                    |
| ----------------------- | ----------------- | --------------------------------------- |
| **Phase 1：共存期**     | 2026-06 ~ 2026-12 | main + win7 并行开发                    |
| **Phase 2：减维护期**   | 2027-01 ~ 2027-06 | Win7 用户 < 10%，减 patch 频率          |
| **Phase 3：弃用通知期** | 2027-07 ~ 2027-09 | 发"Win7 桌面端 EOL"公告                 |
| **Phase 4：归档期**     | 2027-10 ~ 2027-12 | 分支 read-only，Release 标 "DEPRECATED" |
| **Phase 5：删除期**     | 2027-12-13+       | `git push origin --delete release/win7` |

## 5. Win7 用户迁移到 Web 通道

Phase 3 时：

- 发公告：「Sage 桌面端 Win7 支持将于 2027-12-31 终止」
- 引导用户迁移到 **Chrome 109+ / Firefox ESR 102+** 访问 `https://sage.example.com`
- Chrome 109（2023-03 发布）是**最后支持 Win7** 的版本
- 部署 Web 服务（Sage 后端 + 前端静态资源到任意 HTTPS 主机）

## 6. 风险声明

⚠️ **本分支基于已 EOL 的技术栈**——Electron 21.4.4 + Python 3.8 + Chromium 106 + Node 16.20.2。
新发现的 Electron 21 CVE **不会得到官方修复**（Electron 22+ 已 EOL Win7）。用户应：

- 在隔离网络/虚拟机中使用
- 定期备份数据
- 不要用于处理敏感信息

## 7. Win7 真机烟测脚本

> 真机烟测由 `scripts/win7-smoke/` PowerShell 脚本驱动，详见 [`../../scripts/win7-smoke/README.md`](../../scripts/win7-smoke/README.md)。

- `deploy.ps1` — 部署到 Win7 物理机
- `install.ps1` — 安装 sage
- `launch-test.ps1` — 启动 + 验证
- `verify-ollama.ps1` — 验证 Ollama API
- `teardown.ps1` — 清理

## 8. VC++ Redistributable(自 0.1.2 起自动 bundling)

NSIS 安装包内含 `vc_redist.x64.exe`(由 `build/installer.nsh` customInstall 宏在
安装阶段静默运行)。用户**无需**手动下载 VC++。

构建侧细节:

- `scripts/fetch-vcredist.ps1` 在 CI(`windows-latest`)和本地 Win 构建前下载
- `resources/vc_redist.x64.exe` 已 gitignore(~14MB 二进制)
- 已装更新版本的用户:MSI 返回 1638,customInstall 宏忽略并继续

人工烟测时(`scripts/win7-smoke/install.ps1`)无需再单独验证 VC++ 安装路径,
但**首次跑**仍要确认安装日志出现:
`Installing Microsoft Visual C++ 2015-2022 Redistributable (x64)...`

详见 [`26-packaging-matrix.md`](./26-packaging-matrix.md)§2。

## 9. Release 工作流

`release/win7` 分支的 release 由 **`.github/workflows/release-win7.yml`** 触发，独立于 main。

| 项              | 值                                                                                |
| --------------- | --------------------------------------------------------------------------------- |
| 触发 tag        | `v*-win7`（如 `v0.4.3-alpha.1-win7`、`v0.5.0-beta.1-win7`、`v0.5.0-win7`）       |
| Runner          | `windows-latest` (cross-build, 同 main)                                           |
| 产物            | `Sage-Setup-${version}-win7.exe` (NSIS, x64)                                      |
| Release 入口    | https://github.com/oneMuggle/sage/releases?q=tag%3Av*-win7                         |
| Release 状态    | draft（人工 review 后 publish）                                                   |
| 与 main 共用    | electron-builder.yml / build/installer.nsh / scripts/fetch-vcredist.ps1           |
| EOL 动作        | 2027-12-13 后 `git push origin --delete release/win7` + 删 `release-win7.yml`      |

### 9.1 触发步骤

1. 切到 `release/win7` 分支: `git switch release/win7`
2. 拉 main 的最新 commit: `git fetch origin main && git rebase origin/main`（如有冲突手动解决）
3. 决定版本号: cherry-pick 后 bump `MAJOR.MINOR.PATCH` 与 main 同步 + 加 `-win7` 后缀 + tier 与 main 一致
   - 例 1：main 发 `v0.5.0-alpha.1` → 同日 win7 发 `v0.5.0-alpha.1-win7`（alpha 阶段 win7 也参与）
   - 例 2：main 发 `v0.5.0-beta.1` → 1 周后 win7 发 `v0.5.0-beta.1-win7`（beta 延迟 1 周）
   - 例 3：纯 win7 blocker 修复可打 `v0.4.3-alpha.1-win7`（4 档 alpha 而非 hotfix patch）
4. 打 tag: `git tag -a v0.5.0-alpha.1-win7 -m "v0.5.0-alpha.1-win7 — Win7 cherry-pick from main v0.5.0-alpha.1"`
5. push tag: `git push origin v0.5.0-alpha.1-win7`
6. 监控 Actions: `gh run watch`
7. CI 通过后到 GitHub Releases 找到 draft，**人工 review release notes** 后 publish

### 9.2 失败处理

| 失败位置                          | 处理                                                                              |
| --------------------------------- | --------------------------------------------------------------------------------- |
| Win7 烟测未通过                   | 不 publish；hotfix 修；重新打 tag（`v0.5.0-alpha.2-win7` 段内数字 +1）            |
| NSIS 产物里没有 win7 后缀         | 检查 release-win7.yml 的 `env.ARTIFACT_SUFFIX` 是否正确设为 `win7`                |
| Release 误发到 main channel       | 删 release + 删 tag：`gh release delete v0.5.0-alpha.1-win7 && git push origin :v0.5.0-alpha.1-win7` |

### 9.3 与 main release 的对比

| 维度         | main release                | LTS release                 |
| ------------ | --------------------------- | --------------------------- |
| 触发 branch  | `main`                      | `release/win7`              |
| 触发 tag     | `v*` (排除 `*-win7`)         | `v*-win7`                    |
| Workflow     | `release.yml`               | `release-win7.yml`          |
| 平台         | Linux / Windows NSIS / macOS (Phase 3+) | Windows NSIS only          |
| 产物后缀     | `-win10` (Windows)          | `-win7` (Windows)           |
| 频率         | 每次 main 发版              | Win7 LTS 4 档全跟随 main（alpha/rc/stable 同日，beta 1 周后）|
| EOL          | 持续                        | 2027-12-13                  |

### 9.4 Pre-release tier mapping (Win7 LTS)

Win7 LTS 与 main 走**完全平行**的 4 档发布线，MAJOR.MINOR.PATCH 与 main 同步：

| main tag | win7 LTS tag | 间隔 | 备注 |
|----------|--------------|------|------|
| `v0.5.0-alpha.1` | `v0.5.0-alpha.1-win7` | **同日** | alpha 阶段 win7 LTS 也参与 |
| `v0.5.0-beta.1` | `v0.5.0-beta.1-win7` | **1 周** | 缩短为 1 周（vs 旧 2 周） |
| `v0.5.0-rc.1` | `v0.5.0-rc.1-win7` | **同日** | rc 阶段已稳定，平台差异可快速 cherry-pick |
| `v0.5.0` | `v0.5.0-win7` | **同日** | cherry-pick 完成后立即 |

**核心约束**：

- win7 LTS 的 tag **必须**从 main 的对应 tag cherry-pick 后打
- **MAJOR.MINOR.PATCH 强同步**：win7 LTS 的 `X.Y.Z` 必须等于 main 的 `X.Y.Z`，tier 编号（alpha.1 / beta.2 / rc.1）也必须一致
- 纯 win7 修复走 4 档（默认 alpha），不再是 hotfix patch
- 4 档全 win7 参与，破除旧的 "alpha 阶段 win7 不跟随" 限制

### 9.5 升档脚本使用

Win7 LTS 派生使用 `scripts/release/infer_tier.py` 推断档位（脚本只建议 main 使用，win7 派生直接按本节映射表执行）：

```bash
# 1. 在 main 上推断档位（确认何时 cherry-pick 到 win7）
python scripts/release/infer_tier.py \
  --since-tag v0.4.0-alpha.1 \
  --target-minor 0.5.0 \
  --milestone-closed "M1,M2" \
  --open-blockers 0

# 2. cherry-pick main 的 stable / RC / beta tag commits 到 release/win7
git switch release/win7
git cherry-pick <main-tag-commit-sha>

# 3. 打 win7 LTS tag（带 -win7 后缀）
git tag -a v0.5.0-beta.1-win7 -m "v0.5.0-beta.1-win7 — Win7 cherry-pick from main v0.5.0-beta.1"
git push origin v0.5.0-beta.1-win7

# 4. release-win7.yml 自动构建 + 标记 prerelease
```

详细的预发布构建矩阵（artifact 后缀 / cache key 隔离）见 [`26-packaging-matrix.md` §7](./26-packaging-matrix.md)；4 档分级系统的完整说明见 [`30-release-tiers.md`](./30-release-tiers.md)。

## 10. Python 3.8 后端兼容与 CI 锁定（2026-07-20）

Win7 LTS 的 Python 3.8.10 embeddable 与 main 的 Python 3.11 不能共享同一份依赖锁文件。本节记录 F1（PR #190 + #189）的修复要点 + v0.4.5-alpha.1 + PR #191/#192 的 bundling 回归修复要点。

### 10.1 Python 3.8 锁定依赖（`backend/requirements-py38.txt`）

| 包 | 锁定版本 | 原因 |
| --- | --- | --- |
| `fastapi` | `0.85.0` | 0.86+ 需要 `pydantic>=2` |
| `pydantic` | `1.10.13` | 1.x → Pydantic v1 API（`model.dict()`、`Config` 类、`validator`）；v2 需要 Python 3.9+ 部分语法糖 |
| `networkx` | `3.1` | 3.2+ 需要 Python 3.9+ |
| `hnswlib` | `0.8.0` | 0.9+ 无 cp38 wheel |
| `requests` | `2.32+` | TLS 验证修复 + Win7 兼容 |
| `prometheus-client` | `0.21.1` | 0.22+ 需要 Python 3.9+（关键 — 0.25.0 会让整个 pip install 回滚） |

> **不要**把 main 的 `backend/requirements.txt` 自动同步到 win7。两者技术栈分叉。

### 10.2 PEP 604 / 585 / collections.abc 注解

Python 3.8 不支持 PEP 604 union syntax（`int | None`）和 PEP 585 generic builtin（`list[int]`）。F1 做了：

- **5 处** PEP 604 → `Optional[...]` / `Union[...]`
- **9 处** PEP 585 → `typing.List/Dict/Set/Tuple/Type`
- **Pydantic v1** API 兼容性（`model.dict()` 而非 `model_dump()`，`Config` 类而非 `model_config`）

辅助工具：`scripts/py38_compat_rewrite.py`（mass-rewriter，用于未来其他 sync 批次）。

### 10.3 bundle-python.ps1 Pester 回归 guards

`scripts/bundle-python.Tests.ps1` 静态分析回归 guards，**16 个测试**：

1. **AST parse** — 语法错误立即报错
2. **`$ErrorActionPreference = "Stop"`** at top
3-5. **三处 `$LASTEXITCODE` throw**：get-pip.py install / pip install -r / pip install -e sage-core
   - PowerShell 的 `ErrorActionPreference = "Stop"` **不会**自动捕获外部调用退出码
   - 没有这三处，pip 失败会被静默吞掉 → v0.4.0-lts+ 30s 后端超时 root cause
6. **`$verifyExit = $LASTEXITCODE`** + `if ($verifyExit is nonzero) throw`
7. **`python38._pth` 配置**：
   - 取消注释 `#import site`（激活 site-packages）
   - 写入 `..`（resources/ 父目录）作为 sys.path 入口
   - **不**写入 `..\backend` 或 `..\sage-core`（sys.path 必须含 package 父目录，不能含 package 本身）
   - `Where-Object -ne '..'` 保证幂等（重跑 bundle 不会重复加行）
8. **`backend.main` canary**：verify 步骤 `import backend.main`，任何 _pth 错误立即 bundle 时爆炸
9. **dead-code cleanup**：脚本不应生成 `start-backend.bat`（electron/main.ts spawn python.exe 直接，从不调用 .bat）
10. **electron-builder.yml**：NSIS extraResources 不打包 `resources/start-backend.bat`
11. **requirements pin**：`prometheus-client==0.21.1`（必须）

### 10.4 Bundling 回归修复链（v0.4.5-alpha.1 期间发现）

| 日期 | Commit / PR | 修复内容 |
| --- | --- | --- |
| 2026-07-06 | `973d44c` | 三处 `$LASTEXITCODE` throw + 移除 start-backend.bat |
| 2026-07-07 | `2689cb8` | `_pth` 写入 `..\backend` / `..\sage-core` + `backend.main` canary |
| 2026-07-07 | `a20c061` | `_pth` 改为单条 `..`（resources/ 父目录）— Python import 语义要求 |
| 2026-07-20 | PR #191 (`0f25f7a`) | cherry-pick 546f8e5 静默回退了以上三 fix，恢复之 |
| 2026-07-21 | PR #192 (`2b9d637`) | Pester T10 双引号 → 单引号字符串字面（PowerShell `\\\$CanonicalResources` 变量插值转义，正则编译失败） |

### 10.5 验证矩阵

| 验证项 | 工具 | 触发 | 当前状态 |
| --- | --- | --- | --- |
| Pester 16 测试 | `Invoke-Pester scripts/bundle-python.Tests.ps1` | ci.yml `bundle-script-test` job on push to release/win7/main | ✅ 全过（run 29792790778） |
| Backend Python 3.8 单测 | `pytest backend/` | ci.yml `backend-py38` job | ✅ 全过（run 29792790778） |
| 真实 Win7 bundling | `release-win7.yml` Bundle Python step | 打 `v*-win7` tag | ⏳ 待下次 release 验证 |
| Electron smoke | `tests/electron/smoke.spec.ts` | ci.yml `electron-smoke` job | ⚠️ Pre-existing flaky（10/10 历史失败，但 PR #191 merge 后成功） |

### 10.6 Fix-forward Checklist（所有 Win7 bundling 脚本同步时）

每次 `bundle-python.ps1` / `bundle-python-main.ps1` / `bundle-python-py38.ps1` 跨分支同步时，**必须**fix-forward 以下历史修复，否则会重新引入：

- [ ] `$CanonicalResources = '..'`（不是 `..\backend` / `..\sage-core`）
- [ ] 三处 `$LASTEXITCODE -ne 0` throw
- [ ] `$verifyExit = $LASTEXITCODE` + canary check
- [ ] `import backend.main` 在 verify 步骤
- [ ] `Where-Object -ne '..'` 幂等
- [ ] 不生成 `start-backend.bat`
- [ ] electron-builder.yml `extraResources` 不含 `start-backend.bat`

详见 memory `sage-bundling-script-fix-forward.md`。
