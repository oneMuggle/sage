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
