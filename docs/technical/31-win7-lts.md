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

## 10. 近期 cherry-pick 进度（2026-08 → 2026-09）

> 此章节记录 main → release/win7 的 backport 流水，作为后续 cherry-pick 的参考样本。
> 完整 PR 列表（main 端）见 [`30-release-tiers.md`](./30-release-tiers.md) §8；
> 完整 commit log 见 `git log origin/release/win7 --oneline`。

### 10.1 已合入 win7 的 PR 批次

| Cherry-pick PR | main 源 PR | 范围 | 关键改动 |
|---|---|---|---|
| [#490](https://github.com/oneMuggle/sage/pull/490) | #489 | 对标第四轮 | U17 上下文指示 / U19 逐 hunk 撤销 / S8 分会话通知 / L4' 缓存前缀 / U18/U12/F10/F11/U7 |
| [#491](https://github.com/oneMuggle/sage/pull/491) | #466/#482 | Office + 编排 | Word 3 修复（font/parse/format）+ review `task_id` UNIQUE 约束幂等化 |
| [#495](https://github.com/oneMuggle/sage/pull/495) | #485/#486/#492 | main 对齐一批 | `backend.tools` 循环导入根修（py3.11 CI red 同步 win7）/ mypy MYPYPATH / legacy 超时 / bundled office 依赖 |
| [#501](https://github.com/oneMuggle/sage/pull/501) | #496/#498 | CI 性能 + 护栏 | 编排确认门控超时可配 / pytest-timeout 护栏 / pytest-xdist 并行 |
| [#504](https://github.com/oneMuggle/sage/pull/504) | #503 | Doctor timeout | Electron 端 `5s → 20s` + `SAGE_DOCTOR_TIMEOUT_MS` 可配 |
| [#506](https://github.com/oneMuggle/sage/pull/506) | #502 | Academic-search skill | skill_save 工具 + 学术检索 builtin；win7 侧修复 `with` 语法 py38 兼容 |
| [#508](https://github.com/oneMuggle/sage/pull/508) | (win7 特有) | PEP 604/585 清理 | AST 重写清 53 文件 105 处违规（历史 cherry-pick 累积） |
| [#509](https://github.com/oneMuggle/sage/pull/509) | (win7 特有) | 护栏集成 CI | 把 `scripts/check_py38_compat.py` 集成到 `backend-py38` job（854 文件 ~3s 扫） |
| [#510](https://github.com/oneMuggle/sage/pull/510) | (win7 特有) | pydantic v1 conlist | `_constrained_list` helper 替换 `Field(min_length=...)` 等 v2-only 语法 |
| [#514](https://github.com/oneMuggle/sage/pull/514) | #513 | Doctor spawn + tray | doctor spawn 改用 `userData` + tray 图标打包进 `app.asar` |
| [#515](https://github.com/oneMuggle/sage/pull/515) | #507 | Phase 2 bundled | docxtpl/PyMuPDF/reportlab/certifi 打入 Win7 安装包；contract test 三处 win7 适配 |

### 10.2 工作流模式（实战沉淀）

| 模式 | 描述 | 典型 PR |
|---|---|---|
| **冲突解决优先取 main 侧** | main 通常更详细（含更多注释 + 后续依赖声明），win7 侧往往是早期行数精简版 | #507（`requirements-bundled.txt` 取 main 的 9 行注释 + certifi） |
| **跨文件 contract test 必须 win7 适配** | main 的契约测试常硬编码 `backend/requirements.txt` 作为 source-of-truth，win7 真正源是 `backend/requirements-py38.txt` | #507（`_PARSE_REQ` 自动检测 `requirements-py38.txt` 存在性） |
| **C extension 包存在 py38 wheel 截止** | PyMuPDF 1.24.x 是 Py3.8 wheel 最后一版；bundled floor 与 dev pin 必须有意分裂 | #507（PyMuPDF `==1.24.11` vs `>=1.25.0`，需在测试中显式 skip operator check） |
| **dev pin → installer floor 推广** | 同一包在 source-of-truth 用 `==`（可复现），bundled 用 `>=`（patch 升级自动），contract test 必须接受四种 op 组合 | #507（加 `(==, >=)` case：bundled floor ≤ dev pin） |
| **win7 特有 PR 不必 cherry-pick 回 main** | `_constrained_list` / `check_py38_compat.py` 是 Py3.8 专属，main 不需要 | #505/#508/#509/#510 |
| **PEP 604/585 自动重写** | 历史 cherry-pick 累积的 `X \| Y` / `list[int]` 写法，由 `scripts/check_py38_compat.py` AST 扫描 + `py38_compat_rewrite.py` libcst 自动清 | #508（53 文件 105 处违规 → 0） |
| **零依赖护栏脚本** | CI 步骤只用 stdlib AST，避免 ruff/libcst 版本漂移 | #505/#509 |
| **CI 步骤用 `bash -el {0}`** | 加载 conda env 后再跑 `pytest` / `python scripts/...` | #509 |

### 10.3 新增工具（win7 侧）

| 路径 | 用途 |
|---|---|
| `scripts/check_py38_compat.py` | AST 扫 PEP 604/585 违规（零依赖，~3s 扫 854 文件） |
| `scripts/py38_compat_rewrite.py` | libcst 自动重写（带 typing import 行加 `from typing import ...` 触发 ruff F811） |
| `backend/_constrained_list.py` | pydantic v1 替代 v2 `Field(min_length=...)` 的 `List[X]` 长度约束 helper |

### 10.4 当前开放 PR（待用户 merge）

| PR | 状态 | 关联 main |
|---|---|---|
| [#512](https://github.com/oneMuggle/sage/pull/512) | open / CI 全绿 | electron/main.ts 完整对齐（demo mode + IPC guards + OfficeIpc + WIKI_STREAM_ERROR 统一错误格式，491 行差异 27 类别） |
| [#515](https://github.com/oneMuggle/sage/pull/515) | open / CI 全绿 | #507（Phase 2 bundled deps + certifi） |

> Cherry-pick 原则（见 §2）:**单 commit cherry-pick, commit message 加 `(cherry picked from main commit XXX)`**。
> 避免把 main 的 release 元数据（CHANGELOG / version bump）带回 win7。
